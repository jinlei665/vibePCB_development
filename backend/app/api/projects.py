# -*- coding: utf-8 -*-
"""项目 CRUD / 状态查询（契约：POST /api/projects、GET /api/projects、GET /api/projects/{id}）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import APP_VERSION, settings
from ..core.workspace import WorkspaceError, create_project, get_project, list_projects

router = APIRouter()


@router.post("/api/projects", status_code=201)
def create(body: dict):
    name = str(body.get("name") or "").strip()
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(422, detail={"error": {"code": "INVALID_INPUT", "stage": "projects",
                                                   "message": "prompt 不能为空"}})
    ws = create_project(name or "vibepcb-project", prompt)
    return _detail(ws)


@router.get("/api/projects")
def list_all():
    return {"projects": list_projects()}


@router.get("/api/projects/{project_id}")
def detail(project_id: str):
    try:
        ws = get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": "projects",
                                                   "message": f"项目不存在: {project_id}"}})
    return _detail(ws)


def _detail(ws) -> dict:
    s = ws.state
    return {
        "project_id": s["project_id"],
        "name": s["name"],
        "prompt": s["prompt"],
        "overall": s["overall"],
        "current_stage": s.get("current_stage"),
        "created_at": s["created_at"],
        "updated_at": s.get("updated_at"),
        "stages": s.get("stages", {}),
        "artifacts": s.get("artifacts", []),
    }
