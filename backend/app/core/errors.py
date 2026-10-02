# -*- coding: utf-8 -*-
"""统一业务错误。架构文档定义的错误码集合。"""
from __future__ import annotations


class StageError(Exception):
    """阶段执行失败，携带契约错误码。"""

    def __init__(self, code: str, stage: str, message: str, detail: dict | None = None):
        self.code = code
        self.stage = stage
        self.message = message
        self.detail = detail or {}
        super().__init__(f"[{code}] {stage}: {message}")


# 契约错误码
DEEPSEEK_UNAVAILABLE = "DEEPSEEK_UNAVAILABLE"
DEEPSEEK_KEY_MISSING = "DEEPSEEK_KEY_MISSING"
SCHEMATIC_ERC_FAILED = "SCHEMATIC_ERC_FAILED"
FOOTPRINT_NOT_FOUND = "FOOTPRINT_NOT_FOUND"
PCB_ENGINE_ERROR = "PCB_ENGINE_ERROR"
STAGE_PREREQ_MISSING = "STAGE_PREREQ_MISSING"
INTERNAL = "INTERNAL"
