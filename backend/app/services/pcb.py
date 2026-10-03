# -*- coding: utf-8 -*-
"""PCB 阶段服务：双引擎调度。

- pcbnew 真实引擎：kinet2pcb（网表→.kicad_pcb）+ pcbnew 布线；需本机安装 KiCad。
- kiutils 模拟引擎：内置封装库快照 + 分区布局 + 曼哈顿布线；无 KiCad 环境可用。

引擎选择：VIBEPCB_PCB_ENGINE = auto | pcbnew | simulated
- auto：探测到 KiCad 用 pcbnew，否则模拟；
- 强制 simulated 时 degraded=false（用户显式选择）；
- auto 下探测不到 KiCad 落到模拟时 degraded=true。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..core.engines import engine_status, simulated_is_degraded, use_simulated
from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger(__name__)


def run_pcb(ws: ProjectWorkspace) -> dict:
    netlist = ws.out_dir / "project.net"
    if not netlist.exists():
        raise StageError("STAGE_PREREQ_MISSING", "pcb", "缺少 project.net，请先完成 schematic 阶段")

    status = engine_status()
    use_sim = use_simulated()
    degraded_reason = None

    if not use_sim and status.pcbnew_importable:
        try:
            stats = _run_pcbnew(netlist, ws.out_dir)
            engine = "pcbnew"
            degraded = False
        except Exception as exc:  # 真实引擎失败自动回落
            logger.warning("pcbnew engine failed, falling back to simulated: %s", exc)
            stats = _run_simulated(netlist, ws.out_dir)
            engine = "kiutils-simulated"
            degraded = True
            # 把回落原因带出去（质检 D3）：此前只打一条 warning，前端完全看不到
            # 「装了 KiCad 却仍在跑模拟引擎」的真实原因，只能瞎猜。
            degraded_reason = f"pcbnew 引擎失败已回落模拟引擎：{exc}"[:300]
    else:
        stats = _run_simulated(netlist, ws.out_dir)
        engine = "kiutils-simulated"
        degraded = simulated_is_degraded()
        if degraded:
            degraded_reason = "本机未检测到可导入的 pcbnew（未安装 KiCad 或未配置其 Python 路径）"

    board_path = ws.out_dir / "project.kicad_pcb"
    if not board_path.exists():
        raise StageError("PCB_ENGINE_ERROR", "pcb", "PCB 引擎未产出板文件")

    ws.register_artifact("out/project.kicad_pcb", "pcb")

    drc = _drc_for(engine, board_path, stats)
    drc["engine"] = engine

    return {
        "stage": "pcb",
        "engine": engine,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "note": stats.get("note", ""),
        "files": [str(board_path.name)],
        "layout": {
            "components_placed": stats.get("components_placed", 0),
            "board_outline_mm": stats.get("board_outline", {}),
            "zones": ["power", "mcu", "sensor", "display", "actuator", "interface"],
        },
        "routing": {
            "strategy": "manhattan-orthogonal",
            "segments": stats.get("segments", 0),
            "vias": stats.get("vias", 0),
            "total_track_mm": stats.get("total_track_mm", 0),
            "signal_width_mm": 0.25,
            "power_width_mm": 0.6,
        },
        "drc": drc,
    }


def _drc_summary(stats: dict) -> dict:
    return {
        "footprints": stats.get("components_placed", 0),
        "nets": stats.get("nets", 0),
        "segments": stats.get("segments", 0),
        "vias": stats.get("vias", 0),
    }


def _drc_for(engine: str, board_path: Path, stats: dict) -> dict:
    """DRC 摘要（质检 D11）。

    真实引擎写出的板必须用 **pcbnew** 回读：kiutils 1.4.8 解析不了 KiCad 10 的板文件
    格式——实测 `kiutils/items/common.py:543` 的 `Net.from_sexpr` 对 `(net <code>)`
    这种不带网络名的写法直接 `IndexError: list index out of range`，会让整个 pcb 阶段
    500。模拟引擎的板本来就是 kiutils 写的，继续用 kiutils 回读。

    DRC 只是建议性信息，**任何异常都不应让阶段失败**，故两条路径都兜底。
    """
    try:
        if engine == "pcbnew":
            return _drc_with_pcbnew(board_path, stats)
        from . import pcb_simulated

        return pcb_simulated.basic_drc(board_path, stats)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DRC 回读失败（engine=%s）: %s", engine, exc)
        return {
            "checks": [],
            "errors": [],
            "warnings": [{"type": "drc_unavailable", "detail": str(exc)[:200]}],
            "summary": _drc_summary(stats),
        }


def _drc_with_pcbnew(board_path: Path, stats: dict) -> dict:
    """用 pcbnew 回读真实引擎的板，做 MVP 级检查（网络覆盖 / 板框闭合）。"""
    import pcbnew

    board = pcbnew.LoadBoard(str(board_path))

    routed: set = set()
    track_count = via_count = 0
    for t in board.GetTracks():
        name = t.GetNetname()
        if name:
            routed.add(name)
        # SWIG 绑定下 isinstance 不一定可靠，按类名区分走线/过孔
        if type(t).__name__.upper().endswith("VIA"):
            via_count += 1
        else:
            track_count += 1

    net_names: set = set()
    try:
        for name in board.GetNetsByName().keys():
            net_names.add(str(name))
    except Exception:  # noqa: BLE001
        pass

    unrouted = sorted(n for n in net_names if n and n not in routed and n != "N/C")
    edge = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    errors = []
    if len(edge) != 4:
        errors.append({"type": "edge_not_rect", "lines": len(edge)})

    return {
        "checks": ["net_coverage", "edge_closed"],
        "errors": errors,
        "warnings": [{"type": "net_unrouted", "net": n} for n in unrouted],
        "summary": {
            "footprints": len(list(board.GetFootprints())),
            "nets": len([n for n in net_names if n]),
            "segments": track_count or stats.get("segments", 0),
            "vias": via_count or stats.get("vias", 0),
        },
    }


def _run_simulated(netlist: Path, out_dir: Path) -> dict:
    from . import pcb_simulated

    return pcb_simulated.build_board(netlist, out_dir / "project.kicad_pcb")


def _run_pcbnew(netlist: Path, out_dir: Path) -> dict:
    """真实引擎（D4 重写）：用 pcbnew 原生 API 从网表建板，**不依赖 kinet2pcb**。

    为什么弃用 kinet2pcb：它 1.1.4 的 Windows 发现逻辑写死了

        for kicad_version in ("9.0", "8.0", "7.0", "6.0", "5.0"):
            ki_pth = os.path.join("C:\\Program Files\\KiCad", kicad_version)

    既固定安装路径、又完全不认识 KiCad 10，`import kinet2pcb` 直接抛
    "Could not find KiCad installation to import pcbnew module"（本机 10.0.6 实测）。
    既然 pcbnew 本身已可导入，直接用它建板更简单也更可控：

    * 复用 pcb_simulated 的网表解析与分区布局 → 两个引擎布局语义一致；
    * 封装用 pcbnew.FootprintLoad 从内置快照库加载 → 走 KiCad 自己的解析器；
    * 走线/过孔复用同一个 router.route_all() → 布线语义一致；
    * 由 pcbnew.SaveBoard 写出 → 保证是 KiCad 原生格式。
    """
    import pcbnew

    from . import pcb_simulated
    from . import router as router_mod

    nl = pcb_simulated.parse_netlist(netlist)
    positions = pcb_simulated.place_components(nl)

    board = pcbnew.CreateEmptyBoard()
    board_out = out_dir / "project.kicad_pcb"

    def _pt(x_mm: float, y_mm: float):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

    nets: dict = {}

    def _net(name: str):
        if name not in nets:
            item = pcbnew.NETINFO_ITEM(board, name)
            board.Add(item)
            nets[name] = item
        return nets[name]

    # 节点索引：ref -> {pin: net_name}
    ref_pin_net: dict = {}
    for name, pn in nl.nets.items():
        for node in pn.nodes:
            ref_pin_net.setdefault(node.ref, {})[node.pin] = name

    def _is_virtual(comp) -> bool:
        # 电气标注件（PWR_FLAG）与虚拟 ref（#PWR…）不落板，与模拟引擎一致
        return (pcb_simulated._fp_path(comp.footprint) is None
                or "PWR_FLAG" in comp.footprint.upper()
                or comp.ref.startswith("#"))

    pad_coords: dict = {}
    placed = 0
    skipped: list = []
    for comp in nl.components:
        if _is_virtual(comp):
            skipped.append(comp.ref)
            continue
        fp_file = pcb_simulated._fp_path(comp.footprint)
        fp = pcbnew.FootprintLoad(str(fp_file.parent), fp_file.stem)
        if fp is None:
            logger.warning("pcbnew: FootprintLoad failed for %s (%s)", comp.ref, comp.footprint)
            skipped.append(comp.ref)
            continue
        # FootprintLoad 不会带库昵称，必须显式补上：否则板里的封装在 KiCad 中显示为
        # 「无库关联」（fpid 形如 ":R_0805_2012Metric"），也追不回来源（质检 D18）。
        try:
            fp.SetFPID(pcbnew.LIB_ID(fp_file.parent.name[: -len(".pretty")], fp_file.stem))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SetFPID failed for %s: %s", comp.ref, exc)

        x, y, rot = positions.get(comp.ref, (30.0, 30.0, 0.0))
        fp.SetPosition(_pt(x, y))
        if rot:
            fp.SetOrientationDegrees(rot)
        fp.SetReference(comp.ref)
        if comp.value:
            fp.SetValue(comp.value)
        board.Add(fp)

        for pad in fp.Pads():
            num = pad.GetNumber()
            net_name = ref_pin_net.get(comp.ref, {}).get(num)
            if not net_name:
                continue
            pad.SetNet(_net(net_name))
            pos = pad.GetPosition()
            pad_coords.setdefault(net_name, []).append(
                (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y))
            )
        placed += 1

    # 曼哈顿布线（与模拟引擎同一套算法，保证两个引擎行为一致）
    routed = router_mod.route_all(pad_coords)
    seg_count = via_count = 0
    total_mm = 0.0
    layer_cache: dict = {}

    def _layer_id(name: str) -> int:
        if name not in layer_cache:
            layer_cache[name] = board.GetLayerID(name)
        return layer_cache[name]

    for net_name, rn in routed.items():
        code = _net(net_name).GetNetCode()
        for s in rn.segments:
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(_pt(s.start[0], s.start[1]))
            t.SetEnd(_pt(s.end[0], s.end[1]))
            t.SetWidth(pcbnew.FromMM(s.width))
            t.SetLayer(_layer_id(s.layer))
            t.SetNetCode(code)
            board.Add(t)
            seg_count += 1
            total_mm += s.length_mm
        for v in rn.vias:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(_pt(v.x, v.y))
            via.SetWidth(pcbnew.FromMM(v.size))
            via.SetDrill(pcbnew.FromMM(v.drill))
            via.SetNetCode(code)
            board.Add(via)
            via_count += 1

    # 板框：已放器件包围盒 + 5mm 边距（与模拟引擎同一策略），画在 Edge.Cuts
    xs: list = []
    ys: list = []
    for fp in board.GetFootprints():
        bb = fp.GetBoundingBox()
        xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
        ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    outline: dict = {}
    if xs and ys:
        x0, x1 = min(xs) - 5.0, max(xs) + 5.0
        y0, y1 = min(ys) - 5.0, max(ys) + 5.0
        for (sx, sy, ex, ey) in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                                 (x1, y1, x0, y1), (x0, y1, x0, y0)):
            shape = pcbnew.PCB_SHAPE(board)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
            shape.SetStart(_pt(sx, sy))
            shape.SetEnd(_pt(ex, ey))
            shape.SetLayer(pcbnew.Edge_Cuts)
            shape.SetWidth(pcbnew.FromMM(0.1))
            board.Add(shape)
        outline = {"x": round(x1 - x0, 1), "y": round(y1 - y0, 1)}

    out_dir.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(board_out), board)
    if not board_out.exists():
        raise RuntimeError("pcbnew.SaveBoard 未产出板文件")

    logger.info("pcbnew native: %d footprints placed, %d segments, %d vias",
                placed, seg_count, via_count)
    return {
        "components_placed": placed,
        "virtual_skipped": sorted(set(skipped)),
        "nets": len(nets),
        "segments": seg_count,
        "vias": via_count,
        "board_outline": outline,
        "total_track_mm": round(total_mm, 1),
        "note": "pcbnew 原生引擎：FootprintLoad 摆放 + 曼哈顿自动布线",
    }
