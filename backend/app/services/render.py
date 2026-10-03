# -*- coding: utf-8 -*-
"""实时预览：用 kicad-cli 把 .kicad_pcb / .kicad_sch 渲染成 SVG。

为什么走 kicad-cli 而不是自绘：渲染结果与最终出图完全一致，且不必自己实现
KiCad 的图形语义。代价是每次重渲染要起一次 kicad-cli 子进程（实测 PCB ~0.35s、
原理图 ~0.4s），对"随生成过程刷新"完全够用。

**-o 语义在不同子命令下不一致**（实测 KiCad 10.0.6，很容易踩）：
  * `pcb export svg --mode-single -o X`  → X 是**文件**路径
  * `sch export svg -o X`                → X 是**目录**，文件按输入名写成 X/<name>.svg
  * `pcb export gerbers -o X`            → X 是**目录**（见 gerber.py 的 D10）
所以这里对 pcb 传文件、对 sch 传目录并回捞产物，最终统一复制成 render/<kind>.svg。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from ..core.engines import engine_status
from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger("vibepcb.render")

# PCB 预览默认层：铜层 + 丝印 + 板框，足以看清布局与布线
PCB_PREVIEW_LAYERS = "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,Edge.Cuts"

# kind -> (源文件相对路径, 人类可读名)
RENDER_KINDS = {
    "pcb": ("out/project.kicad_pcb", "PCB"),
    "schematic": ("out/project.kicad_sch", "原理图"),
}


def kicad_cli() -> str:
    """复用 engines 探测到的 kicad-cli 绝对路径（与 gerber.py 同一策略）。"""
    path = engine_status().kicad_cli_path
    if not path:
        raise StageError(
            "RENDER_UNAVAILABLE", "render",
            "未找到 kicad-cli，无法渲染预览（安装 KiCad 后重试）",
        )
    return path


def source_path(ws: ProjectWorkspace, kind: str) -> Path:
    if kind not in RENDER_KINDS:
        raise StageError("INVALID_INPUT", "render", f"不支持的预览类型: {kind}")
    return ws.abs(RENDER_KINDS[kind][0])


def rendered_path(ws: ProjectWorkspace, kind: str) -> Path:
    return ws.root / "render" / f"{kind}.svg"


def is_stale(ws: ProjectWorkspace, kind: str) -> bool:
    """源文件缺失或比已渲染的 SVG 新 → 需要重渲染。"""
    src = source_path(ws, kind)
    out = rendered_path(ws, kind)
    if not src.exists():
        return True
    if not out.exists():
        return True
    return src.stat().st_mtime > out.stat().st_mtime


def render_svg(ws: ProjectWorkspace, kind: str, *, force: bool = False) -> Path:
    """渲染（必要时）并返回 SVG 路径。"""
    src = source_path(ws, kind)
    if not src.exists():
        raise StageError(
            "STAGE_PREREQ_MISSING", "render",
            f"缺少 {src.name}，请先完成对应阶段",
        )

    out = rendered_path(ws, kind)
    if not force and not is_stale(ws, kind):
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    cli = kicad_cli()

    if kind == "pcb":
        cmd = [
            cli, "pcb", "export", "svg",
            "-o", str(out),                       # 文件
            "--layers", PCB_PREVIEW_LAYERS,
            "--mode-single",
            "--fit-page-to-board",
            "--exclude-drawing-sheet",
            str(src),
        ]
        res = _run(cmd, timeout=180)
        if res.returncode != 0 or not out.exists():
            raise StageError("RENDER_FAILED", "render", _err("pcb export svg", res))
    else:
        tmp = out.parent / "_sch_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        cmd = [
            cli, "sch", "export", "svg",
            "-o", str(tmp),                       # 目录
            "--exclude-drawing-sheet",
            "--no-background-color",
            str(src),
        ]
        res = _run(cmd, timeout=180)
        produced = sorted(tmp.rglob("*.svg")) if tmp.exists() else []
        if res.returncode != 0 or not produced:
            shutil.rmtree(tmp, ignore_errors=True)
            raise StageError("RENDER_FAILED", "render", _err("sch export svg", res))
        shutil.copyfile(produced[0], out)
        shutil.rmtree(tmp, ignore_errors=True)

    if not out.exists() or out.stat().st_size == 0:
        raise StageError("RENDER_FAILED", "render", f"kicad-cli 未产出有效 SVG: {out.name}")

    logger.info("rendered %s preview -> %s (%d bytes)", kind, out.name, out.stat().st_size)
    return out


def _run(cmd: list, timeout: int):
    return subprocess.run(
        cmd,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",  # kicad-cli 输出含中文，必须显式指定
        timeout=timeout,
    )


def _err(what: str, res) -> str:
    tail = (res.stderr or res.stdout or "").strip().replace("\n", " ")[-300:]
    return f"{what} exit {res.returncode}: {tail}"


# ---------------------------------------------------------------- 交给 KiCad 精修
# tool -> (可执行文件名, 源文件相对路径)
KI_GUI_TOOLS = {
    "pcb": ("pcbnew.exe" if os.name == "nt" else "pcbnew",
            "out/project.kicad_pcb"),
    "schematic": ("eeschema.exe" if os.name == "nt" else "eeschema",
                  "out/project.kicad_sch"),
}


def kicad_bin_dir() -> Path | None:
    path = engine_status().kicad_cli_path
    return Path(path).parent if path else None


def launch_in_kicad(ws: ProjectWorkspace, tool: str) -> dict:
    """用 KiCad 的 GUI 打开产物（本机桌面场景）。

    这是"双轨"里交给专业编辑器的那一轨：我们负责生成与预览，重度编辑用 KiCad。
    """
    if tool not in KI_GUI_TOOLS:
        raise StageError("INVALID_INPUT", "open", f"不支持的工具: {tool}")
    exe_name, rel = KI_GUI_TOOLS[tool]
    src = ws.abs(rel)
    if not src.exists():
        raise StageError("STAGE_PREREQ_MISSING", "open", f"缺少 {src.name}，请先完成对应阶段")

    bin_dir = kicad_bin_dir()
    exe = (bin_dir / exe_name) if bin_dir else None
    if exe is None or not exe.exists():
        raise StageError("RENDER_UNAVAILABLE", "open",
                         f"未找到 {exe_name}（安装 KiCad 后重试）")

    subprocess.Popen([str(exe), str(src)], close_fds=True)
    logger.info("launched %s for %s", exe_name, src.name)
    return {"opened": True, "tool": tool, "exe": str(exe), "file": src.name}
