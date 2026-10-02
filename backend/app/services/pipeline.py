# -*- coding: utf-8 -*-
"""阶段编排：串行状态机 + 依赖检查 + 一键 pipeline。

- 六阶段：parse → components → schematic → pcb / firmware → gerber；
- stages=["all"] 时按 parse → components → schematic → pcb → gerber → firmware 执行；
- 每阶段通过 workspace 更新 project.json 状态，供前端 1 秒轮询读取。
"""
from __future__ import annotations

import json
import logging
import threading
import traceback

from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace, STAGE_ORDER, STAGE_PREREQS

logger = logging.getLogger(__name__)

# 一键执行顺序：gerber 依赖 pcb；firmware 仅依赖 parse+components，放最后并行面最小
PIPELINE_ORDER = ["parse", "components", "schematic", "pcb", "gerber", "firmware"]

# 进程内运行锁：同一项目同时只允许一个流水线
_project_locks: dict = {}
_locks_guard = threading.Lock()


def _get_lock(project_id: str) -> threading.Lock:
    with _locks_guard:
        return _project_locks.setdefault(project_id, threading.Lock())


def try_acquire(project_id: str) -> threading.Lock | None:
    """尝试获取项目运行锁；被占用返回 None。

    供 pipeline 与单阶段端点共用——单阶段执行同样纳入互斥锁，
    避免与 pipeline 并发跑同项目时状态机交错（质检 P2）。
    """
    lock = _get_lock(project_id)
    return lock if lock.acquire(blocking=False) else None


def _completed(ws: ProjectWorkspace) -> set:
    return {s for s, st in ws.state.get("stages", {}).items() if st.get("status") == "done"}


def run_stage_once(ws: ProjectWorkspace, stage: str, prompt: str) -> dict:
    """执行单个阶段（runner 分发 + 状态落盘）。"""
    from . import firmware as firmware_svc
    from . import gerber as gerber_svc
    from . import parser as parser_svc
    from . import pcb as pcb_svc
    from . import schematic as schematic_svc
    from . import selector as selector_svc

    ws.begin_stage(stage)
    try:
        if stage == "parse":
            payload = parser_svc.run_parse(ws, prompt)
        elif stage == "components":
            spec = json.loads((ws.root / "in" / "spec.json").read_text(encoding="utf-8"))
            payload = selector_svc.run_components(ws, spec, prompt)
        elif stage == "schematic":
            payload = schematic_svc.run_schematic(ws)
        elif stage == "pcb":
            payload = pcb_svc.run_pcb(ws)
        elif stage == "gerber":
            payload = gerber_svc.run_gerber(ws)
        elif stage == "firmware":
            payload = firmware_svc.run_firmware(ws)
        else:
            raise StageError("STAGE_PREREQ_MISSING", stage, f"未知阶段 {stage}")
    except StageError as exc:
        ws.fail_stage(stage, f"[{exc.code}] {exc.message}")
        raise
    except Exception as exc:  # 未知异常统一包装
        ws.fail_stage(stage, str(exc))
        logger.error("stage %s crashed: %s\n%s", stage, exc, traceback.format_exc())
        raise StageError("INTERNAL", stage, str(exc)) from exc

    ws.finish_stage(
        stage,
        engine=payload.get("engine", "unknown"),
        degraded=bool(payload.get("degraded", False)),
        result=payload,
    )
    return payload


def run_stages(ws: ProjectWorkspace, stages: list, user_input: str | None = None) -> dict:
    """串行执行指定阶段。stages=["all"] 展开为完整流水线。

    - 依赖缺失即抛 STAGE_PREREQ_MISSING；
    - 已完成阶段跳过（幂等），parse 例外——允许新输入重跑；
    - gerber 失败不阻断 firmware（记录后继续）。
    """
    if not stages or "all" in stages:
        stages = list(PIPELINE_ORDER)
    for s in stages:
        if s not in STAGE_ORDER:
            raise StageError("STAGE_PREREQ_MISSING", s, f"未知阶段 {s}")

    lock = try_acquire(ws.project_id)
    if lock is None:
        raise StageError("INTERNAL", "pipeline", "该项目的流水线正在运行中")

    prompt = user_input or ws.state.get("prompt", "")
    results: dict = {}
    try:
        for stage in stages:
            done = _completed(ws)
            missing = [p for p in STAGE_PREREQS.get(stage, []) if p not in done]
            if missing:
                raise StageError(
                    "STAGE_PREREQ_MISSING", stage,
                    f"缺少前置阶段：{', '.join(missing)}",
                )
            if stage in done and stage != "parse":
                results[stage] = {
                    "stage": stage, "engine": "cached", "degraded": False, "skipped": True,
                }
                continue
            try:
                results[stage] = run_stage_once(ws, stage, prompt)
            except StageError:
                if stage == "gerber" and "firmware" in stages:
                    logger.warning("gerber failed; continue with firmware")
                    results[stage] = {"stage": "gerber", "error": "failed (see project.json)"}
                    continue
                raise
        return results
    finally:
        lock.release()
