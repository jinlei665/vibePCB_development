# -*- coding: utf-8 -*-
"""VibePCB 后端入口。运行：uvicorn app.main:app --host 127.0.0.1 --port 8710"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import artifacts, projects, stages
from .config import APP_NAME, APP_VERSION, settings
from .core.engines import engine_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="VibePCB API", version=APP_VERSION)

# Electron 前端（开发模式 vite 默认 5173）跨域放行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(stages.router)
app.include_router(artifacts.router)


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
