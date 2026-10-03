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
import subprocess
from pathlib import Path

from ..core.engines import engine_status, simulated_is_degraded, use_simulated
from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger(__name__)

# 内置封装库快照目录（与 pcb_simulated.FP_LIBS_DIR 同一份）。
# 传给 kinet2pcb -l，保证真实引擎也能解析出 netlist 里用到的 footprint。
FP_LIBS_DIR = Path(__file__).resolve().parent.parent / "templates" / "footprint_libs"


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
            engine = "pcbnew(kinet2pcb)"
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

    from . import pcb_simulated

    drc = pcb_simulated.basic_drc(board_path, stats)
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


def _run_simulated(netlist: Path, out_dir: Path) -> dict:
    from . import pcb_simulated

    return pcb_simulated.build_board(netlist, out_dir / "project.kicad_pcb")


def _run_pcbnew(netlist: Path, out_dir: Path) -> dict:
    """真实引擎：kinet2pcb 网表转板 + 补一轮曼哈顿布线。需要本机安装 KiCad。"""
    import sys

    import kinet2pcb  # noqa: F401  顶层即校验 pcbnew 可用性

    board_out = out_dir / "project.kicad_pcb"
    # 用 sys.executable 而不是写死的 "python3"（质检 D3）：Windows 上 python3 往往
    # 是 Microsoft Store 的 0 字节别名占位（本机实测 size=0）或根本不存在，导致
    # spawn 必然失败并被静默回落模拟引擎，装了 KiCad 也走不到真实链路。
    # -w：允许覆盖上一轮留下的板文件（例如先跑过模拟引擎）。
    # -l：指向内置封装快照，保证 netlist 里的 footprint 能被解析。
    cmd = [
        sys.executable, "-m", "kinet2pcb",
        "-o", str(board_out),
        "-w",
        "-l", str(FP_LIBS_DIR),
        str(netlist),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0 or not board_out.exists():
        raise RuntimeError(
            f"kinet2pcb exited {result.returncode}: "
            f"{(result.stderr or result.stdout)[-400:]}"
        )

    # kinet2pcb 只负责「网表→摆放」，本身不布线（质检 D4）。这里复用模拟引擎用的
    # 同一个 router.route_all()，把走线/过孔真正写回 .kicad_pcb，让两个引擎的
    # 「自动布局布线」行为一致。布线失败不致命：板子仍可用，只是没走线。
    try:
        stats = _route_with_pcbnew(board_out)
        stats["routed"] = True
        stats["note"] = "pcbnew(kinet2pcb) 摆放 + 曼哈顿自动布线"
    except Exception as exc:  # noqa: BLE001
        logger.warning("pcbnew auto-routing failed, board left un-routed: %s", exc)
        stats = {
            "components_placed": -1, "segments": 0, "vias": 0,
            "total_track_mm": 0, "board_outline": {},
            "routed": False, "routing_error": str(exc)[:300],
            "note": "pcbnew(kinet2pcb) 仅完成摆放，自动布线未生效（见 routing_error）",
        }
    return stats


def _route_with_pcbnew(board_path: Path) -> dict:
    """读回 pcbnew 生成的板，按网络收集焊盘坐标，注入曼哈顿走线与过孔。"""
    import pcbnew

    from . import router as router_mod

    board = pcbnew.LoadBoard(str(board_path))

    def _pt(x_mm: float, y_mm: float):
        # KiCad 7+ 用 VECTOR2I；老版本是 wxPoint。都试一遍以保证兼容。
        if hasattr(pcbnew, "VECTOR2I"):
            return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))
        return pcbnew.wxPoint(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

    net_pads: dict = {}
    placed = 0
    for fp in board.GetFootprints():
        placed += 1
        for pad in fp.Pads():
            net = pad.GetNet()
            if net is None:
                continue
            name = net.GetNetname()
            if not name:
                continue
            pos = pad.GetPosition()
            net_pads.setdefault(name, []).append(
                (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y))
            )

    routed = router_mod.route_all(net_pads)
    seg_count = via_count = 0
    total_mm = 0.0
    for net_name, rn in routed.items():
        netinfo = board.FindNet(net_name)
        if netinfo is None:
            continue
        ncode = netinfo.GetNetCode() if hasattr(netinfo, "GetNetCode") else 0
        for s in rn.segments:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(_pt(s.start[0], s.start[1]))
            track.SetEnd(_pt(s.end[0], s.end[1]))
            track.SetWidth(pcbnew.FromMM(s.width))
            track.SetLayer(board.GetLayerID(s.layer))
            track.SetNetCode(ncode)
            board.Add(track)
            seg_count += 1
            total_mm += s.length_mm
        for v in rn.vias:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(_pt(v.x, v.y))
            via.SetWidth(pcbnew.FromMM(v.size))
            via.SetDrill(pcbnew.FromMM(v.drill))
            via.SetNetCode(ncode)
            board.Add(via)
            via_count += 1

    pcbnew.SaveBoard(str(board_path), board)
    logger.info("pcbnew auto-route: %d footprints, %d segments, %d vias",
                placed, seg_count, via_count)

    # 板框尺寸：从 Edge.Cuts 包围盒取
    bbox = board.GetBoardEdgesBoundingBox()
    outline = {}
    if bbox is not None:
        outline = {
            "x": round(pcbnew.ToMM(bbox.GetWidth()), 1),
            "y": round(pcbnew.ToMM(bbox.GetHeight()), 1),
        }
    return {
        "components_placed": placed,
        "segments": seg_count,
        "vias": via_count,
        "total_track_mm": round(total_mm, 1),
        "board_outline": outline,
    }
