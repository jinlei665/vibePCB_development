"""项目工作区与 project.json 状态管理（文档第 2/4 章 workspace）。

目录结构（运行时数据目录，不属于仓库）：
~/.vibepcb/projects/{project_id}/
    project.json
    in/       输入（prompt.txt）
    out/      原理图 / 网表 / PCB
    firmware/ 固件工程
    gerber/   Gerber 输出
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from ..config import settings

_TZ = timezone(timedelta(hours=8))  # 北京时间，契约示例为 +08:00

STAGE_ORDER = ["parse", "components", "schematic", "pcb", "firmware", "gerber"]

STAGE_PREREQS = {
    "parse": [],
    "components": ["parse"],
    "schematic": ["components"],
    "pcb": ["schematic"],
    "firmware": ["parse", "components"],
    "gerber": ["pcb"],
}


def now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class WorkspaceError(LookupError):
    pass


class ProjectWorkspace:
    def __init__(self, root: Path, project_id: str):
        self.root = root
        self.project_id = project_id
        self.state_file = root / "project.json"
        self.lock = threading.RLock()
        self._state: dict[str, Any] = self._load()

    # ---------- 状态读写 ----------

    def _load(self) -> dict[str, Any]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        raise WorkspaceError(f"project.json missing: {self.state_file}")

    def save(self) -> None:
        with self.lock:
            self._state["updated_at"] = now_iso()
            self.state_file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    # ---------- 阶段状态 ----------

    def stage(self, name: str) -> dict[str, Any]:
        return self._state["stages"].setdefault(name, {"status": "pending"})

    def begin_stage(self, name: str) -> None:
        with self.lock:
            st = self.stage(name)
            st.update({"status": "running", "started_at": now_iso(),
                       "error": None, "engine": None, "degraded": None})
            self._state["current_stage"] = name
            self._state["overall"] = "running"
            self.save()

    def finish_stage(self, name: str, *, engine: str, degraded: bool,
                     result: dict[str, Any]) -> None:
        with self.lock:
            st = self.stage(name)
            st.update({
                "status": "done", "engine": engine, "degraded": degraded,
                "finished_at": now_iso(), "result": result, "error": None,
            })
            if all(self.stage(s).get("status") == "done" for s in STAGE_ORDER):
                self._state["overall"] = "done"
                self._state["current_stage"] = None
            else:
                nxt = next(
                    (s for s in STAGE_ORDER if self.stage(s).get("status") not in ("done",)),
                    None,
                )
                self._state["current_stage"] = nxt
            self.save()

    def fail_stage(self, name: str, message: str) -> None:
        with self.lock:
            st = self.stage(name)
            st.update({"status": "failed", "error": message, "finished_at": now_iso()})
            self._state["overall"] = "failed"
            self.save()

    # ---------- 产物 ----------

    def register_artifact(self, rel_path: str, kind: str) -> dict[str, Any]:
        """登记产物到 project.json 并返回描述（path/kind/sha256/size）。"""
        full = self.abs(rel_path)
        entry = {
            "path": rel_path, "kind": kind,
            "sha256": sha256_file(full), "size": full.stat().st_size,
        }
        with self.lock:
            arts = self._state.setdefault("artifacts", [])
            arts[:] = [a for a in arts if a["path"] != rel_path]
            arts.append(entry)
            self.save()
        return entry

    def abs(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise WorkspaceError(f"illegal artifact path: {rel_path}")
        return p

    # ---------- 目录 ----------

    @property
    def out_dir(self) -> Path:
        return self.root / "out"

    @property
    def firmware_dir(self) -> Path:
        return self.root / "firmware"

    @property
    def gerber_dir(self) -> Path:
        return self.root / "gerber"


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_registry: dict[str, ProjectWorkspace] = {}


def _workspace_lock(project_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(project_id, threading.Lock())


def create_project(name: str, prompt: str) -> ProjectWorkspace:
    projects_dir = settings.projects_dir
    projects_dir.mkdir(parents=True, exist_ok=True)
    project_id = "p_" + secrets.token_hex(3)
    while (projects_dir / project_id).exists():
        project_id = "p_" + secrets.token_hex(3)
    root = projects_dir / project_id
    for sub in ("in", "out", "firmware", "gerber"):
        (root / sub).mkdir(parents=True)

    safe_name = (name or "vibepcb-project").strip() or "vibepcb-project"
    state = {
        "project_id": project_id,
        "name": safe_name,
        "prompt": prompt,
        "overall": "created",
        "current_stage": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "artifacts": [],
        "stages": {s: {"status": "pending"} for s in STAGE_ORDER},
    }
    (root / "project.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "in" / "prompt.txt").write_text(prompt, encoding="utf-8")
    ws = ProjectWorkspace(root, project_id)
    _registry[project_id] = ws
    return ws


def get_project(project_id: str) -> ProjectWorkspace:
    ws = _registry.get(project_id)
    if ws is not None:
        return ws
    root = settings.projects_dir / project_id
    if not (root / "project.json").exists():
        raise WorkspaceError(f"project not found: {project_id}")
    ws = ProjectWorkspace(root, project_id)
    _registry[project_id] = ws
    return ws


def list_projects() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not settings.projects_dir.exists():
        return out
    for d in sorted(settings.projects_dir.iterdir()):
        if not d.is_dir() or not (d / "project.json").exists():
            continue
        try:
            ws = get_project(d.name)
            s = ws.state
            out.append({
                "project_id": s["project_id"], "name": s["name"],
                "overall": s["overall"], "current_stage": s.get("current_stage"),
                "created_at": s["created_at"],
            })
        except Exception:  # noqa: BLE001
            continue
    return out
