# -*- coding: utf-8 -*-
"""实时预览与「交给 KiCad」端点。

GET  /api/projects/{id}/render/{kind}          预览 SVG（源文件更新时自动重渲染）
GET  /api/projects/{id}/render/{kind}?force=1  强制重渲染
POST /api/projects/{id}/open/{tool}            用 KiCad GUI 打开产物（仅限本机）

kind: pcb | schematic      tool: pcb | schematic
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from ..core.errors import StageError
from ..core.workspace import WorkspaceError, get_project
from ..services import render as render_svc

logger = logging.getLogger(__name__)

router = APIRouter()

# 允许触发「打开本机 GUI」的客户端地址（该动作有副作用，只对本机开放）
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "::ffff:127.0.0.1"}


def _status_for(exc: StageError) -> int:
    return {
        "STAGE_PREREQ_MISSING": 404,
        "RENDER_UNAVAILABLE": 503,
        "INVALID_INPUT": 400,
    }.get(exc.code, 500)


def _project(project_id: str):
    try:
        return get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {
            "code": "NOT_FOUND", "stage": "render",
            "message": f"项目不存在: {project_id}"}})


@router.get("/api/projects/{project_id}/render/{kind}")
def get_render(project_id: str, kind: str, force: int = 0):
    """返回预览 SVG。默认仅在源文件比上次渲染新时重渲染。"""
    ws = _project(project_id)
    try:
        svg = render_svc.render_svg(ws, kind, force=bool(force))
    except StageError as exc:
        raise HTTPException(_status_for(exc), detail={"error": {
            "code": exc.code, "stage": "render", "message": exc.message}})

    # 不传 filename：FileResponse 只有在给了 filename 时才会带 attachment 头，
    # 这里要的是浏览器内联显示。同时禁掉缓存，否则前端会一直看到旧图。
    return FileResponse(
        svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store", "X-Render-Kind": kind},
    )


@router.post("/api/projects/{project_id}/open/{tool}")
def open_in_kicad(project_id: str, tool: str, request: Request):
    """用 KiCad 的 GUI 打开产物（双轨里「重度编辑交给 KiCad」的那一轨）。

    仅限本机调用：这个端点会在服务器所在机器上拉起 GUI 进程，公网可达时等于
    任何人能远程弹窗，所以非环回来源一律 403。
    """
    host = (request.client.host if request.client else "") or ""
    if host not in _LOCAL_HOSTS:
        raise HTTPException(403, detail={"error": {
            "code": "LOCAL_ONLY", "stage": "open",
            "message": f"该操作只允许本机调用（来源 {host}）"}})

    ws = _project(project_id)
    try:
        result = render_svc.launch_in_kicad(ws, tool)
    except StageError as exc:
        raise HTTPException(_status_for(exc), detail={"error": {
            "code": exc.code, "stage": "open", "message": exc.message}})
    return JSONResponse(content=result)
