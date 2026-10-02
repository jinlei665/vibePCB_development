"""集中读取环境变量配置。

硬性规则：DEEPSEEK_API_KEY 只从环境变量读取，禁止硬编码、禁止写盘、禁止入日志。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "vibepcb"
APP_VERSION = "0.1.0"


def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    return val if val else default


def _parse_origins(raw: str) -> list:
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass
class Settings:
    # DeepSeek
    deepseek_api_key: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-flash"))
    deepseek_fallback_model: str = field(default_factory=lambda: _env("DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro"))
    deepseek_timeout_s: float = field(default_factory=lambda: float(_env("DEEPSEEK_TIMEOUT_S", "60")))
    deepseek_retries: int = 2

    # VibePCB
    pcb_engine: str = field(default_factory=lambda: _env("VIBEPCB_PCB_ENGINE", "auto"))
    port: int = field(default_factory=lambda: int(_env("VIBEPCB_PORT", "8710")))
    data_dir: Path = field(
        default_factory=lambda: Path(_env("VIBEPCB_DATA_DIR", str(Path.home() / ".vibepcb"))).expanduser()
    )
    stage_timeout_s: float = 300.0  # 文档：单阶段执行上限 300 秒

    # 公网部署防护（P1）：VIBEPCB_API_TOKEN 非空时所有 /api 路由（/api/health 除外）
    # 要求 Bearer 或 X-API-Token 凭据；为空保持本机模式（Electron/本地开发不受影响）
    api_token: str = field(default_factory=lambda: _env("VIBEPCB_API_TOKEN", ""))
    # CORS 收敛（P1）：默认仅放行本机 vite dev 与 Electron file://（Origin: null）；
    # 公网部署用 VIBEPCB_CORS_ORIGINS 显式配置逗号分隔 origin 列表（此时应去掉 null）
    cors_origins: list = field(default_factory=lambda: _parse_origins(
        _env("VIBEPCB_CORS_ORIGINS",
             "http://localhost:5173,http://127.0.0.1:5173,null")
    ))

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


settings = Settings()
