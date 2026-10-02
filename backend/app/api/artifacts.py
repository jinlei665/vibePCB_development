# -*- coding: utf-8 -*-
"""产物浏览 / 下载。

GET /api/projects/{id}/artifacts/{stage}            → 该阶段产物清单
GET .../artifacts/{stage}?path=...                  → 文本内容（代码查看器）
GET .../artifacts/{stage}?path=...&download=1       → 附件下载（zip 同理）
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..core.workspace import WorkspaceError, get_project

router = APIRouter()

# 阶段 → 产物 kind 映射
STAGE_KINDS = {
    "parse": set(),
    "components": set(),
    "schematic": {"netlist", "schematic"},
    "pcb": {"pcb"},
    "firmware": {"firmware"},
    "gerber": {"gerber"},
}


@router.get("/api/projects/{project_id}/artifacts/{stage}")
def artifacts(project_id: str, stage: str, path: str | None = None, download: int = 0):
    if stage not in STAGE_KINDS:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": stage,
                                                   "message": f"未知阶段: {stage}"}})
    try:
        ws = get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": stage,
                                                   "message": f"项目不存在: {project_id}"}})

    if path is None:
        kinds = STAGE_KINDS[stage]
        items = [a for a in ws.state.get("artifacts", []) if a.get("kind") in kinds]
        return {"stage": stage, "artifacts": items}

    # 单文件
    rel = path.lstrip("/")
    try:
        full = ws.abs(rel)
    except WorkspaceError:
        raise HTTPException(400, detail={"error": {"code": "INVALID_INPUT", "stage": stage,
                                                   "message": "非法路径"}})
    if not full.exists() or not full.is_file():
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "stage": stage,
                                                   "message": f"文件不存在: {rel}"}})
    if download:
        media, _ = mimetypes.guess_type(full.name)
        return FileResponse(full, filename=full.name, media_type=media or "application/octet-stream")
    # 文本预览（限制 512KB）
    if full.stat().st_size > 512 * 1024:
        return PlainTextResponse("（文件超过 512KB，请下载查看）")
    try:
        return PlainTextResponse(full.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return FileResponse(full, filename=full.name)
