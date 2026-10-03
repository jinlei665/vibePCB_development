# -*- coding: utf-8 -*-
"""VibePCB 后端入口。运行：uvicorn app.main:app --host 127.0.0.1 --port 8710"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import artifacts, board, library, projects, render, stages
from .config import APP_NAME, APP_VERSION, settings
from .core.engines import engine_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="VibePCB API", version=APP_VERSION)

# CORS 收敛（质检 P1）：默认仅本机 vite dev + Electron file://（Origin: null）；
# 公网部署经 VIBEPCB_CORS_ORIGINS 显式配置 origin 列表（同源反代部署天然无跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
)


# API 鉴权（质检 P1）：VIBEPCB_API_TOKEN 非空时，除 /api/health 外所有 /api 路由
# 要求凭据（Authorization: Bearer <token> 或 X-API-Token: <token>）。
# 未配置时零开销直通——本机 Electron/开发模式体验不变。
@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    if settings.api_token:
        path = request.url.path
        if path.startswith("/api") and path != "/api/health":
            auth = request.headers.get("authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            token = token or request.headers.get("x-api-token", "").strip()
            if token != settings.api_token:
                return JSONResponse(status_code=401, content={"error": {
                    "code": "UNAUTHORIZED", "stage": "-",
                    "message": "缺少或无效的 API Token（需 Authorization: Bearer 或 X-API-Token 头）",
                }})
    return await call_next(request)

app.include_router(projects.router)
app.include_router(stages.router)
app.include_router(artifacts.router)
app.include_router(render.router)
app.include_router(board.router)
app.include_router(library.router)


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": {
        "code": "INTERNAL", "stage": "-", "message": str(exc)}})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "app": APP_NAME}


@app.get("/api/capabilities")
def capabilities():
    st = engine_status()
    return {
        "version": APP_VERSION,
        "deepseek_configured": settings.deepseek_configured,
        "deepseek_model": settings.deepseek_model if settings.deepseek_configured else None,
        "pcbnew_available": st.pcbnew_importable,
        "kicad_cli_available": bool(st.kicad_cli_path),
        "kicad_version": st.kicad_version,
        "pcb_engine_selected": st.pcb_engine_active,
        "engines": {
            "kicad_installed": st.kicad_installed,
            "pcbnew_importable": st.pcbnew_importable,
            "kicad_cli_path": st.kicad_cli_path,
            "pcb_engine_active": st.pcb_engine_active,
            "forced": st.forced,
        },
        "stages": ["parse", "components", "schematic", "pcb", "firmware", "gerber"],
    }


@app.on_event("startup")
def startup():
    st = engine_status()
    logger.info(
        "%s v%s 启动 | port=%s | deepseek=%s | pcbnew=%s | kicad-cli=%s | engine=%s",
        APP_NAME, APP_VERSION, settings.port,
        "configured" if settings.deepseek_configured else "MISSING(降级模式)",
        st.pcbnew_importable, bool(st.kicad_cli_path),
        st.pcb_engine_active,
    )
