# -*- coding: utf-8 -*-
"""Gerber 阶段：双路径。

- 真实路径：kicad-cli pcb export gerbers（本机装有 KiCad 时）；
- 模拟路径：自研 RS-274X 写入器，直接从 .kicad_pcb 几何生成
  F.Cu / B.Cu / Edge.Cuts Gerber + Excellon 钻孔文件，打包 zip。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

from kiutils.board import Board

from ..core.engines import engine_status, simulated_is_degraded, use_simulated
from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger(__name__)

# 3.4 格式：坐标 = mm * 10^4
SCALE = 10000


def run_gerber(ws: ProjectWorkspace) -> dict:
    board_path = ws.out_dir / "project.kicad_pcb"
    if not board_path.exists():
        raise StageError("STAGE_PREREQ_MISSING", "gerber", "缺少 project.kicad_pcb，请先完成 pcb 阶段")

    status = engine_status()
    ws_gerber = ws.gerber_dir
    ws_gerber.mkdir(parents=True, exist_ok=True)

    if not use_simulated() and status.kicad_cli_path:
        try:
            files = _export_with_kicad_cli(board_path, ws_gerber)
            engine = "kicad-cli"
            degraded = False
        except Exception as exc:
            logger.warning("kicad-cli export failed, falling back to simulated: %s", exc)
            files = _export_simulated(board_path, ws_gerber)
            engine = "rs274x-simulated"
            degraded = True
    else:
        files = _export_simulated(board_path, ws_gerber)
        engine = "rs274x-simulated"
        degraded = simulated_is_degraded()

    # 打包 zip
    zip_path = ws_gerber / "gerbers.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    ws.register_artifact("gerber/gerbers.zip", "gerber")

    return {
        "stage": "gerber",
        "engine": engine,
        "degraded": degraded,
        "files": [f.name for f in files] + ["gerbers.zip"],
        "format": {
            "gerber": "RS-274X (Extended), 单位 mm, 坐标格式 3.4",
            "drill": "Excellon, 单位 mm",
            "layers": ["F.Cu", "B.Cu", "Edge.Cuts"],
        },
    }


# ---------------------------------------------------------------- kicad-cli 真实路径
def _export_with_kicad_cli(board_path: Path, out_dir: Path) -> list:
    result = subprocess.run(
        [
            "kicad-cli", "pcb", "export", "gerbers",
            "-o", str(out_dir / "%f-%i.gbr"),
            "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,Edge.Cuts,F.SilkS,B.SilkS",
            str(board_path),
        ],
        capture_output=True, text=True, timeout=240,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kicad-cli exit {result.returncode}: {result.stderr[-300:]}")
    drill = subprocess.run(
        ["kicad-cli", "pcb", "export", "drill", "-o", str(out_dir), str(board_path)],
        capture_output=True, text=True, timeout=120,
    )
    if drill.returncode != 0:
        raise RuntimeError(f"kicad-cli drill exit {drill.returncode}")
    return sorted(out_dir.glob("*.gbr")) + sorted(out_dir.glob("*.drl"))


# ---------------------------------------------------------------- 模拟 RS-274X
def _fmt(v: float) -> str:
    return f"{int(round(v * SCALE)):d}"


class _GerberWriter:
    def __init__(self, name: str, comment: str):
        self.lines = [
            "G04 VibePCB generated*",
            f"G04 {name} - {comment}*",
            "%FSLAX34Y34*%",
            "%MOMM*%",
        ]
        self.apertures: list = []          # (code, definition str)
        self._ap_index: dict = {}          # key -> D code

    def _aperture(self, key: str, definition: str) -> str:
        if key not in self._ap_index:
            code = 10 + len(self.apertures)
            self._ap_index[key] = code
            self.apertures.append((code, definition))
        return f"D{self._ap_index[key]}"

    def flash(self, x: float, y: float, key: str, definition: str):
        d = self._aperture(key, definition)
        self.lines.append(f"{d}*")
        self.lines.append(f"X{_fmt(x)}Y{_fmt(y)}D03*")

    def draw(self, x1: float, y1: float, x2: float, y2: float, key: str, definition: str):
        d = self._aperture(key, definition)
        self.lines.append(f"{d}*")
        self.lines.append(f"X{_fmt(x1)}Y{_fmt(y1)}D02*")
        self.lines.append(f"X{_fmt(x2)}Y{_fmt(y2)}D01*")

    def render(self) -> str:
        header = "\n".join(f"%ADD{c},{d}*%" for c, d in self.apertures)
        return "\n".join(self.lines[:3] + [header] + self.lines[3:]) + "\nM02*\n"


def _export_simulated(board_path: Path, out_dir: Path) -> list:
    board = Board.from_file(str(board_path))

    writers = {
        "F.Cu": _GerberWriter("F.Cu", "Top copper"),
        "B.Cu": _GerberWriter("B.Cu", "Bottom copper"),
        "Edge.Cuts": _GerberWriter("Edge.Cuts", "Board outline"),
    }

    drill_points = []
    flash_count = 0

    for item in board.traceItems:
        layer = getattr(item, "layer", None)
        if layer not in writers:
            continue
        w = getattr(item, "width", 0.25) or 0.25
        writers[layer].draw(
            item.start.X, item.start.Y, item.end.X, item.end.Y,
            key=f"trace{w}", definition=f"C,{w:.3f}",
        )

    for g in board.graphicItems:
        layer = getattr(g, "layer", None)
        if layer in writers and hasattr(g, "start"):
            writers[layer].draw(
                g.start.X, g.start.Y, g.end.X, g.end.Y,
                key="edge", definition="C,0.100",
            )

    for fp in board.footprints:
        for pad in fp.pads:
            px = fp.position.X + pad.position.X
            py = fp.position.Y + pad.position.Y
            # 铜层焊盘闪曝
            pad_layers = pad.layers if pad.layers else ["F.Cu"]
            for pl in pad_layers:
                if pl not in writers:
                    continue
                sx, sy = pad.size.X, pad.size.Y
                if pad.shape == "rect":
                    key = f"r{sx}x{sy}"
                    definition = f"R,{sx:.3f}X{sy:.3f}"
                elif pad.shape == "oval":
                    key = f"o{sx}x{sy}"
                    definition = f"O,{sx:.3f}X{sy:.3f}"
                elif pad.shape == "roundrect":
                    # 矩形近似（质检 P3）：此前取 max 边做圆，窄边铜箔外扩
                    # (max-min)/2，密集焊盘间隙收缩有短路边际
                    key = f"r{sx}x{sy}"
                    definition = f"R,{sx:.3f}X{sy:.3f}"
                else:  # circle 近似为圆
                    key = f"c{max(sx, sy)}"
                    definition = f"C,{max(sx, sy):.3f}"
                writers[pl].flash(px, py, key, definition)
                flash_count += 1
            # 钻孔（kiutils DrillDefinition 的孔径字段是 diameter）
            drill_d = getattr(pad.drill, "diameter", None) or getattr(pad.drill, "size", 0)
            if pad.drill and drill_d and drill_d > 0:
                drill_points.append((px, py, drill_d))

    out_files = []
    for layer, writer in writers.items():
        p = out_dir / f"project-{layer.replace('.', '_')}.gbr"
        p.write_text(writer.render(), encoding="utf-8")
        out_files.append(p)

    # Excellon
    drl = out_dir / "project.drl"
    drl.write_text(_excellon(drill_points), encoding="utf-8")
    out_files.append(drl)

    logger.info("simulated gerber: %d pads flashed, %d drill points", flash_count, len(drill_points))
    return out_files


def _excellon(points: list) -> str:
    tools = sorted({round(p[2], 3) for p in points})
    tool_map = {t: i + 1 for i, t in enumerate(tools)}
    lines = [
        "M48",
        "METRIC,TZ",
        ";VibePCB generated drill file",
    ]
    for t, i in tool_map.items():
        lines.append(f"T{i}C{t:.3f}")
    lines.append("%")
    lines.append("G90")
    lines.append("G05")
    current_tool = None
    for x, y, d in points:
        t = tool_map[round(d, 3)]
        if t != current_tool:
            lines.append(f"T{t}")
            current_tool = t
        lines.append(f"X{ x * 1000:.0f}Y{y * 1000:.0f}")
    lines.append("T0")
    lines.append("M30")
    return "\n".join(lines) + "\n"
