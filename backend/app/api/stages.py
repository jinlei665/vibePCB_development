# -*- coding: utf-8 -*-
"""六个阶段端点 + pipeline 端点（同步执行，前端 1 秒轮询 GET /api/projects/{id}）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..core.errors import StageError
from ..core.workspace import WorkspaceError, get_project
from ..services import pipeline as pipeline_svc

logger = logging.getLogger(__name__)

router = APIRouter()

STAGES = ("parse", "components", "schematic", "pcb", "firmware", "gerber")


def _error_response(exc: StageError) -> HTTPException:
    status = 404 if exc.code == "STAGE_PREREQ_MISSING" else 502 if exc.code.startswith("DEEPSEEK") else 500
    return HTTPException(status, detail={"error": {
        "code": exc.code, "stage": exc.stage, "message": exc.message, **({"detail": exc.detail} if exc.detail else {}),
    }})


@router.post("/api/projects/{project_id}/pipeline")
def run_pipeline(project_id: str, body: dict | None = None):
    """一键流水线：stages=["all"] 或阶段名数组；响应为最终全景状态。"""
    body = body or {}
    stages = body.get("stages") or ["all"]
    try:
        ws = get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": "pipeline",
                                                   "message": f"项目不存在: {project_id}"}})
    user_input = body.get("prompt")
    try:
        results = pipeline_svc.run_stages(ws, stages, user_input=user_input)
    except StageError as exc:
        raise _error_response(exc)
    from .projects import _detail
    d = _detail(ws)
    d["pipeline_results"] = results
    return d


@router.post("/api/projects/{project_id}/{stage}")
def run_stage(project_id: str, stage: str, body: dict | None = None):
    """单阶段执行（六阶段同构端点）。"""
    if stage not in STAGES:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": stage,
                                                   "message": f"未知阶段: {stage}"}})
    body = body or {}
    try:
        ws = get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": stage,
                                                   "message": f"项目不存在: {project_id}"}})
    user_input = body.get("prompt") or ws.state.get("prompt", "")
    try:
        return pipeline_svc.run_stage_once(ws, stage, user_input)
    except StageError as exc:
        raise _error_response(exc)
