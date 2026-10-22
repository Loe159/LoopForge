"""Task composition values and worker-side reads of the existing engine contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loopforge.engine import ActionScope, current_status, detect_project_pack


@dataclass(frozen=True)
class TaskDraft:
    task: str
    success_checks: tuple[str, ...] = ()
    rubric: str = ""


@dataclass(frozen=True)
class TaskContext:
    scope: ActionScope
    project_name: str
    profile: str
    pack: str
    adapter: str
    task: str = ""
    success_checks: tuple[str, ...] = ()
    rubric: str = ""
    missing: tuple[str, ...] = ()


def load_task_context(project: Path) -> TaskContext:
    """Called in a worker, never from a widget's render/compose callback."""

    status = current_status(project)
    if not status.initialized or status.config is None:
        raise ValueError("Initialize this project before creating a run.")
    config, run = status.config, status.run or {}
    contract = status.loop_contract or {}
    pack = detect_project_pack(project)
    return TaskContext(
        scope=ActionScope(str(config.get("project_id") or ""), status.project_dir,
                          str(config.get("current_run_id") or "") or None,
                          revision=run.get("run_revision", 0),
                          config_revision=config.get("config_revision", 0)),
        project_name=str(config.get("project_name") or project.name),
        profile=str(config.get("profile") or "supervised"),
        pack=str(pack.get("name") or "unknown"),
        adapter=str(config.get("default_adapter") or "default"),
        task=str(run.get("task") or ""),
        success_checks=tuple(str(value) for value in (run.get("success_checks") or [])),
        rubric=str(contract.get("rubric") or ""),
        missing=tuple(str(value) for value in ((run.get("task_validation") or {}).get("missing") or [])),
    )
