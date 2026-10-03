# -*- coding: utf-8 -*-
"""PCB 板模型与编辑端点（CAD 化增量 3）。

GET  /api/projects/{id}/board          板模型（器件/焊盘/走线/过孔/板框，单位 mm）
POST /api/projects/{id}/board/edits    应用一批编辑并写回 .kicad_pcb
POST /api/projects/{id}/board/revert   恢复到上一次编辑前的备份

编辑是整批原子的：任一条非法就整体拒绝、不落盘。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..core.errors import StageError
from ..core.workspace import WorkspaceError, get_project
from ..services import board_edit as board_svc

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUS = {
    "STAGE_PREREQ_MISSING": 404,
    "INVALID_INPUT": 400,
    "RENDER_UNAVAILABLE": 503,
}


def _project(project_id: str):
    try:
        return get_project(project_id)
    except WorkspaceError:
        raise HTTPException(404, detail={"error": {
            "code": "NOT_FOUND", "stage": "board",
            "message": f"项目不存在: {project_id}"}})


def _fail(exc: StageError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 500), detail={"error": {
        "code": exc.code, "stage": "board", "message": exc.message}})


@router.get("/api/projects/{project_id}/board")
def get_board(project_id: str):
    ws = _project(project_id)
    try:
        return board_svc.board_model(ws)
    except StageError as exc:
        raise _fail(exc)


@router.post("/api/projects/{project_id}/board/edits")
def post_edits(project_id: str, body: dict | None = None):
    ws = _project(project_id)
    edits = (body or {}).get("edits")
    try:
        return board_svc.apply_edits(ws, edits)
    except StageError as exc:
        raise _fail(exc)


@router.post("/api/projects/{project_id}/board/revert")
def post_revert(project_id: str):
    ws = _project(project_id)
    try:
        return board_svc.revert_board(ws)
    except StageError as exc:
        raise _fail(exc)
