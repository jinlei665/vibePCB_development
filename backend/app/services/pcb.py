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


def run_pcb(ws: ProjectWorkspace) -> dict:
    netlist = ws.out_dir / "project.net"
    if not netlist.exists():
        raise StageError("STAGE_PREREQ_MISSING", "pcb", "缺少 project.net，请先完成 schematic 阶段")

    status = engine_status()
    use_sim = use_simulated()

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
    else:
        stats = _run_simulated(netlist, ws.out_dir)
        engine = "kiutils-simulated"
        degraded = simulated_is_degraded()

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
    """真实引擎：kinet2pcb 网表转板。需要本机安装 KiCad（pcbnew 可导入）。"""
    import kinet2pcb  # noqa: F401  顶层即校验 pcbnew 可用性

    board_out = out_dir / "project.kicad_pcb"
    result = subprocess.run(
        ["python3", "-m", "kinet2pcb", "-o", str(board_out), str(netlist)],
        capture_output=True, text=True, timeout=240,
    )
    if result.returncode != 0 or not board_out.exists():
        raise RuntimeError(f"kinet2pcb exited {result.returncode}: {result.stderr[-400:]}")
    return {
        "components_placed": -1,
        "segments": 0,
        "vias": 0,
        "board_outline": {},
        "total_track_mm": 0,
        "note": "pcbnew 引擎，布局布线请在 KiCad 中完成精修",
    }
