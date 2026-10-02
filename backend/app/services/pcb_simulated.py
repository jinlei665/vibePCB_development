# -*- coding: utf-8 -*-
"""PCB 模拟引擎（无 KiCad 环境）。

架构文档原设想 kinet2pcb 作为模拟引擎，但 kinet2pcb 顶层硬 import pcbnew，
无 KiCad 完全不可用；本模块改为：kiutils 直接从 skidl 网表组装 .kicad_pcb。
（kinet2pcb 仅保留在 pcbnew 真实引擎链路中。）

流程：
1. 解析 KiCad 网表（自研迷你 s-表达式解析器）→ 元件 + 网络 + 节点；
2. 从内置封装库快照（templates/footprint_libs）加载 .kicad_mod；
3. 分区网格布局（电源/主控/传感/显示/执行/接口）；
4. router.py 曼哈顿布线；
5. kiutils Board 组装输出 + DRC 基础检查。
"""
from __future__ import annotations

import copy
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.items.brditems import Segment, Via
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from ..services import router as router_mod

logger = logging.getLogger(__name__)

FP_LIBS_DIR = Path(__file__).resolve().parent.parent / "templates" / "footprint_libs"


# ---------------------------------------------------------------- s-expression
def _parse_clean(text: str):
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    root: List = []
    stack: List[List] = [root]
    for tk in tokens:
        if tk == "(":
            new: List = []
            stack[-1].append(new)
            stack.append(new)
        elif tk == ")":
            if len(stack) > 1:
                stack.pop()
        else:
            if len(tk) >= 2 and tk.startswith('"') and tk.endswith('"'):
                tk = tk[1:-1].replace('\\"', '"')
            stack[-1].append(tk)
    return root


def _find_all(node: list, key: str):
    """深度优先找所有 (key ...) 子式。"""
    out = []
    if isinstance(node, list):
        if node and node[0] == key:
            out.append(node)
        for child in node:
            out.extend(_find_all(child, key))
    return out


def _first(node: list, key: str):
    found = _find_all(node, key)
    return found[0] if found else None


def _token(node: list, key: str, default=None):
    hit = _first(node, key) if node else None
    if hit and len(hit) > 1:
        return hit[1]
    return default


# ---------------------------------------------------------------- 数据结构
@dataclass
class NetNode:
    ref: str
    pin: str


@dataclass
class PcbNet:
    code: int
    name: str
    nodes: List[NetNode] = field(default_factory=list)


@dataclass
class PcbComponent:
    ref: str
    value: str
    footprint: str          # "Lib:Footprint"
    properties: Dict[str, str] = field(default_factory=dict)


@dataclass
class Netlist:
    components: List[PcbComponent] = field(default_factory=list)
    nets: Dict[str, PcbNet] = field(default_factory=dict)   # name -> PcbNet


def parse_netlist(path: Path) -> Netlist:
    root = _parse_clean(Path(path).read_text(encoding="utf-8"))
    nl = Netlist()
    for comp in _find_all(root, "comp"):
        ref = _token(comp, "ref", "")
        value = _token(comp, "value", "")
        fp_node = _first(comp, "footprint")
        fp = fp_node[1] if fp_node and len(fp_node) > 1 else ""
        nl.components.append(PcbComponent(ref=ref, value=value, footprint=fp))
    for net in _find_all(root, "net"):
        code = int(_token(net, "code", "0"))
        name = _token(net, "name", "")
        pn = PcbNet(code=code, name=name)
        for node in _find_all(net, "node"):
            pn.nodes.append(NetNode(ref=_token(node, "ref", ""), pin=str(_token(node, "pin", ""))))
        nl.nets[name] = pn
    return nl


# ---------------------------------------------------------------- 封装库快照
def _fp_path(footprint_id: str) -> Optional[Path]:
    """'Resistor_SMD:R_0805_2012Metric' -> footprint_libs/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod"""
    if ":" not in footprint_id:
        return None
    lib, fp = footprint_id.split(":", 1)
    p = FP_LIBS_DIR / f"{lib}.pretty" / f"{fp}.kicad_mod"
    return p if p.exists() else None


# ---------------------------------------------------------------- 布局分区
ZONES = {
    "power":     ((12.0, 12.0), 15.0),    # (origin, grid)
    "mcu":       ((45.0, 38.0), 22.0),
    "sensor":    ((78.0, 15.0), 14.0),
    "display":   ((78.0, 55.0), 16.0),
    "actuator":  ((15.0, 55.0), 15.0),
    "interface": ((45.0, 75.0), 14.0),
    "misc":      ((45.0, 12.0), 11.0),
}


def _zone_of(ref: str, value: str, footprint: str) -> str:
    key = f"{ref} {value} {footprint}".lower()
    if "esp32" in value.lower() or "wroom" in key or ref.startswith("U") and "esp" in key:
        return "mcu"
    if any(k in key for k in ("ams1117", "ld1117", "ldo", "usb", "pwr_flag", "power")):
        return "power"
    if any(k in key for k in ("ds18b20", "dht", "ntc", "sensor", "to-92")):
        return "sensor"
    if any(k in key for k in ("oled", "ssd1306", "display", "lcd")):
        return "display"
    if any(k in key for k in ("ao3400", "mosfet", "relay", "heater", "ssr", "fan")):
        return "actuator"
    if ref.startswith("j") or "pinheader" in key or "conn" in key:
        return "interface"
    return "misc"


def _bbox_of(fp: Footprint) -> Tuple[float, float]:
    xs, ys = [], []
    for pad in fp.pads:
        xs.append(abs(pad.position.X))
        ys.append(abs(pad.position.Y))
    for g in fp.graphicItems:
        try:
            for pt in (getattr(g, "start", None), getattr(g, "end", None)):
                if pt is not None:
                    xs.append(abs(pt.X))
                    ys.append(abs(pt.Y))
        except Exception:
            pass
    if not xs:
        return 2.0, 2.0
    return max(xs) * 2, max(ys) * 2


def place_components(nl: Netlist) -> Dict[str, Tuple[float, float, float]]:
    """返回 {ref: (x, y, rotation)}，按分区网格摆放。"""
    positions: Dict[str, Tuple[float, float, float]] = {}
    counters = {z: 0 for z in ZONES}
    rows = {z: 0 for z in ZONES}
    for comp in nl.components:
        fp_file = _fp_path(comp.footprint)
        if fp_file is None:
            logger.warning("footprint snapshot missing: %s (%s)", comp.footprint, comp.ref)
            continue
        fp = Footprint.from_file(fp_file)
        w, h = _bbox_of(fp)
        zone = _zone_of(comp.ref, comp.value, comp.footprint)
        (ox, oy), grid = ZONES[zone]
        n = counters[zone]
        # 网格内按器件体尺寸自动拉开
        step = max(grid, w + 3.0, 10.0)
        max_per_row = 3 if zone != "mcu" else 1
        col = n % max_per_row
        row = n // max_per_row
        x = ox + col * step
        y = oy + row * max(grid, h + 3.0, 10.0)
        counters[zone] += 1
        positions[comp.ref] = (round(x, 3), round(y, 3), 0.0)
    return positions


# ---------------------------------------------------------------- 组装 Board
def build_board(netlist_path: Path, out_path: Path, project_name: str = "vibepcb") -> dict:
    """主入口：网表 -> .kicad_pcb。返回统计信息。"""
    nl = parse_netlist(netlist_path)

    # 虚拟器件不落板（PWR_FLAG 等电气标注件）
    virtual_refs = set()
    real_components = []
    for comp in nl.components:
        fp_file = _fp_path(comp.footprint)
        if fp_file is None or "PWR_FLAG" in comp.footprint.upper() or comp.ref.startswith("#"):
            virtual_refs.add(comp.ref)
        else:
            real_components.append(comp)

    board = Board.create_new()
    from kiutils.items.common import PageSettings
    board.paper = PageSettings(paperSize="A4")
    # 网络：code 0 为空网络，KiCad 网表 code 从 1 开始
    net_numbers: Dict[str, int] = {}
    board.nets = [Net(number=0, name="")]
    for idx, (name, pn) in enumerate(sorted(nl.nets.items(), key=lambda kv: kv[1].code), start=1):
        net_numbers[name] = idx
        board.nets.append(Net(number=idx, name=name))

    # 节点索引：ref -> {pin: net_name}
    ref_pin_net: Dict[str, Dict[str, str]] = {}
    for name, pn in nl.nets.items():
        for node in pn.nodes:
            ref_pin_net.setdefault(node.ref, {})[node.pin] = name

    positions = place_components(nl)

    # footprint 落板 + 焊盘网络
    pad_coords: Dict[str, List[Tuple[float, float]]] = {}  # net -> [(x,y)]
    placed_count = 0
    for comp in real_components:
        fp_file = _fp_path(comp.footprint)
        fp = Footprint.from_file(fp_file)
        x, y, rot = positions.get(comp.ref, (30.0, 30.0, 0.0))
        fp.position = Position(X=x, Y=y, angle=rot)
        # reference / value 文本替换（.kicad_mod 快照中的 REF**/占位值）
        for gi in fp.graphicItems:
            if type(gi).__name__ == "FpText":
                if gi.type == "reference":
                    gi.text = comp.ref
                elif gi.type == "value":
                    gi.text = comp.value
        # 焊盘网络
        for pad in fp.pads:
            net_name = ref_pin_net.get(comp.ref, {}).get(pad.number)
            if net_name and net_name in net_numbers:
                pad.net = Net(number=net_numbers[net_name], name=net_name)
                # 旋转 0 度，直接平移
                px = round(x + pad.position.X, 3)
                py = round(y + pad.position.Y, 3)
                pad_coords.setdefault(net_name, []).append((px, py))
        fp.tstamp = uuid.uuid4().hex[:16]
        board.footprints.append(fp)
        placed_count += 1

    # 布线
    routed = router_mod.route_all(pad_coords)
    seg_count = via_count = 0
    for net_name, rn in routed.items():
        nnum = net_numbers.get(net_name, 0)
        for s in rn.segments:
            board.traceItems.append(
                Segment(
                    start=Position(X=s.start[0], Y=s.start[1]),
                    end=Position(X=s.end[0], Y=s.end[1]),
                    width=s.width,
                    layer=s.layer,
                    net=nnum,
                    tstamp=uuid.uuid4().hex[:16],
                )
            )
            seg_count += 1
        for v in rn.vias:
            board.traceItems.append(
                Via(
                    position=Position(X=v.x, Y=v.y),
                    size=v.size,
                    drill=v.drill,
                    layers=["F.Cu", "B.Cu"],
                    net=nnum,
                    tstamp=uuid.uuid4().hex[:16],
                )
            )
            via_count += 1

    # 板框：按器件包围盒 + 5mm 边距
    xs, ys = [], []
    for fp in board.footprints:
        w, h = _bbox_of(fp)
        xs += [fp.position.X - w / 2 - 5, fp.position.X + w / 2 + 5]
        ys += [fp.position.Y - h / 2 - 5, fp.position.Y + h / 2 + 5]
    x0, x1 = round(min(xs), 3), round(max(xs), 3)
    y0, y1 = round(min(ys), 3), round(max(ys), 3)
    for (sx, sy, ex, ey) in [
        (x0, y0, x1, y0),
        (x1, y0, x1, y1),
        (x1, y1, x0, y1),
        (x0, y1, x0, y0),
    ]:
        board.graphicItems.append(
            GrLine(
                start=Position(X=sx, Y=sy),
                end=Position(X=ex, Y=ey),
                width=0.1,
                layer="Edge.Cuts",
                tstamp=uuid.uuid4().hex[:16],
            )
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.to_file(str(out_path))

    stats = {
        "components_placed": placed_count,
        "virtual_skipped": sorted(virtual_refs),
        "nets": len(net_numbers),
        "segments": seg_count,
        "vias": via_count,
        "board_outline": {"x": round(x1 - x0, 1), "y": round(y1 - y0, 1)},
        "total_track_mm": round(sum(rn.total_length_mm for rn in routed.values()), 1),
    }
    return stats


# ---------------------------------------------------------------- DRC（模拟）
def basic_drc(board_path: Path, stats: dict) -> dict:
    """MVP 级基础检查：回读板文件、线段连通性、网络覆盖。"""
    board = Board.from_file(str(board_path))
    issues: List[dict] = []
    # 1) 所有 footprint 焊盘网络号 <= 板内 net 数
    max_net = max((n.number for n in board.nets), default=0)
    for fp in board.footprints:
        for pad in fp.pads:
            if pad.net and pad.net.number > max_net:
                issues.append({"type": "pad_net_out_of_range", "ref": fp.libId, "pad": pad.number})
    # 2) 每个非空网络至少 1 段布线或为虚拟网络
    routed_nets = {t.net for t in board.traceItems if t.net}
    for n in board.nets:
        if n.number == 0 or n.name in ("", "N/C"):
            continue
        if n.number not in routed_nets:
            issues.append({"type": "net_unrouted", "net": n.name})
    # 3) Edge_Cuts 闭合
    edge_lines = [g for g in board.graphicItems if getattr(g, "layer", "") == "Edge.Cuts"]
    if len(edge_lines) != 4:
        issues.append({"type": "edge_not_rect", "lines": len(edge_lines)})
    drc = {
        "engine": "kiutils-simulated",
        "checks": ["pad_net_range", "net_coverage", "edge_closed"],
        "errors": [i for i in issues if i["type"] in ("pad_net_out_of_range", "edge_not_rect")],
        "warnings": [i for i in issues if i["type"] == "net_unrouted"],
        "summary": {
            "footprints": len(board.footprints),
            "nets": max_net,
            "segments": stats.get("segments", 0),
            "vias": stats.get("vias", 0),
        },
    }
    return drc
