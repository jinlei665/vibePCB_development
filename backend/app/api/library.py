# -*- coding: utf-8 -*-
"""器件 / 封装库端点。

GET /api/library                         器件目录 + 封装快照库 + 预置套件（一次取全）
GET /api/library/footprints              仅封装 id 列表（前端下拉用，轻量）
"""
from __future__ import annotations

from fastapi import APIRouter

from ..services import library as library_svc

router = APIRouter()


@router.get("/api/library")
def get_library():
    return library_svc.snapshot()


@router.get("/api/library/footprints")
def get_footprints():
    return {"footprint_ids": library_svc.footprint_ids(), "libs": library_svc.footprint_libs()}
