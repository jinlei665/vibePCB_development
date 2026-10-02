"""KiCad 引擎探测（启动时执行并缓存，文档 6.1）。

探测顺序：
1. import pcbnew —— 成功则真实引擎可用；
2. kicad-cli 在 PATH —— 补充版本号；
3. 全部失败 → 模拟引擎。

切换（文档 6.3）：VIBEPCB_PCB_ENGINE = auto | pcbnew | simulated。
用户强制 simulated 时不算降级（degraded=false）。
"""
from __future__ import annotations

import importlib.util
import logging
import shutil
from dataclasses import dataclass
from typing import Optional

from ..config import settings

logger = logging.getLogger("vibepcb.engines")


@dataclass
class EngineStatus:
    kicad_installed: bool = False
    kicad_version: Optional[str] = None
    pcbnew_importable: bool = False
    kicad_cli_path: Optional[str] = None
    pcb_engine_active: str = "simulated"
    forced: bool = False  # 用户显式指定引擎


def _detect() -> EngineStatus:
    st = EngineStatus()

    spec = importlib.util.find_spec("pcbnew")
    st.pcbnew_importable = spec is not None
    if st.pcbnew_importable:
        try:
            import pcbnew  # noqa: F401
            st.kicad_installed = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("import pcbnew failed: %s", exc)
            st.pcbnew_importable = False

    cli = shutil.which("kicad-cli")
    if cli:
        st.kicad_cli_path = cli
        st.kicad_installed = st.kicad_installed or True
        st.kicad_version = _cli_version(cli)

    # 引擎选择
    mode = settings.pcb_engine.strip().lower()
    st.forced = mode in ("pcbnew", "simulated")
    if mode == "pcbnew":
        if not st.pcbnew_importable:
            raise RuntimeError(
                "VIBEPCB_PCB_ENGINE=pcbnew 但本机 pcbnew 不可导入；"
                "请安装 KiCad 10.0.x 或改用 auto/simulated"
            )
        st.pcb_engine_active = "pcbnew"
    elif mode == "simulated":
        st.pcb_engine_active = "simulated"
    else:  # auto
        st.pcb_engine_active = "pcbnew" if st.pcbnew_importable else "simulated"
    return st


def _cli_version(cli: str) -> Optional[str]:
    import subprocess

    try:
        out = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


_status: Optional[EngineStatus] = None


def engine_status() -> EngineStatus:
    global _status
    if _status is None:
        _status = _detect()
        logger.info(
            "engine detect: kicad_installed=%s pcbnew=%s active=%s forced=%s",
            _status.kicad_installed, _status.pcbnew_importable,
            _status.pcb_engine_active, _status.forced,
        )
    return _status


def use_simulated() -> bool:
    """当前是否应走模拟引擎（含用户强制与自动探测两种情形）。"""
    return engine_status().pcb_engine_active == "simulated"


def simulated_is_degraded() -> bool:
    """模拟引擎是否算“降级”：用户强制指定时不算（文档 6.3）。"""
    st = engine_status()
    return st.pcb_engine_active == "simulated" and not st.forced
