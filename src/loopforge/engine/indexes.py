"""Versioned, rebuildable read indexes for persisted LoopForge runs.

``run.json`` is always authoritative.  Indexes only make list views cheap and
may safely be recreated after an interrupted derived write.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from loopforge.engine.storage import JsonStore
from loopforge.engine.models.schema import CURRENT_INDEX_SCHEMA
from loopforge.engine.recovery import safe_read_json

logger = logging.getLogger(__name__)


RUN_INDEX_FILE = "index.json"
DIRTY_MARKER_FILE = ".index-dirty.json"
RUN_INDEX_VERSION = 1


def run_index_path(run_root: Path) -> Path:
    return run_root / RUN_INDEX_FILE


def dirty_marker_path(run_root: Path) -> Path:
    return run_root / DIRTY_MARKER_FILE


def run_attention(run: dict[str, Any]) -> str:
    if run.get("archived"):
        return "archived"
    blockers = run.get("blockers")
    if isinstance(blockers, list) and blockers:
        return "blocked"
    statuses = run.get("stage_statuses")
    if isinstance(statuses, dict) and any(
        value in {"awaiting_approval", "pending_approval"} for value in statuses.values()
    ):
        return "needs_human"
    status = str(run.get("status") or "")
    if status in {"adapter_blocked", "verification_failed", "blocked", "failed"}:
        return "blocked"
    if status in {"verified", "complete", "completed"}:
        return "complete"
    return "ready"


def run_summary(run: dict[str, Any], *, run_path: Path, current_run_id: str | None) -> dict[str, Any]:
    run_id = str(run.get("run_id") or run_path.name)
    return {
        "run_id": run_id,
        "path": str(run_path),
        "current": run_id == current_run_id,
        "task": str(run.get("task") or ""),
        "status": str(run.get("status") or "unknown"),
        "attention": run_attention(run),
        "pack": str(run.get("pack") or ""),
        "archived": bool(run.get("archived")),
        "created_at": str(run.get("created_at") or ""),
        "updated_at": str(run.get("updated_at") or ""),
    }


def empty_run_index() -> dict[str, Any]:
    return {"schema_version": int(CURRENT_INDEX_SCHEMA), "index_version": RUN_INDEX_VERSION, "updated_at": "", "runs": []}


def read_run_index(store: JsonStore, run_root: Path) -> dict[str, Any] | None:
    path = run_index_path(run_root)
    if dirty_marker_path(run_root).exists():
        return None
    data, diagnostic = safe_read_json(store, path)
    if data is None:
        if diagnostic and "File not found" not in (diagnostic or ""):
            logger.error("Run index corrupt: %s", diagnostic)
        return None
    runs = data.get("runs")
    if data.get("index_version") != RUN_INDEX_VERSION or not isinstance(runs, list):
        return None
    if not all(isinstance(run, dict) for run in runs):
        return None
    return data


def mark_dirty(store: JsonStore, run_root: Path, *, timestamp: str) -> None:
    store.write_object(dirty_marker_path(run_root), {"schema_version": int(CURRENT_INDEX_SCHEMA), "index_version": RUN_INDEX_VERSION, "marked_at": timestamp})


def clear_dirty(run_root: Path) -> None:
    path = dirty_marker_path(run_root)
    if path.exists():
        path.unlink()


def rebuild_run_index(
    store: JsonStore,
    run_root: Path,
    *,
    current_run_id: str | None,
    timestamp: str,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    if run_root.exists():
        for run_path in sorted(run_root.iterdir(), reverse=True):
            if not run_path.is_dir():
                continue
            try:
                run = store.read_object(run_path / "run.json")
            except (OSError, ValueError):
                continue
            runs.append(run_summary(run, run_path=run_path, current_run_id=current_run_id))
    runs.sort(key=lambda value: str(value.get("updated_at") or value.get("created_at") or ""), reverse=True)
    index = {"schema_version": int(CURRENT_INDEX_SCHEMA), "index_version": RUN_INDEX_VERSION, "updated_at": timestamp, "runs": runs}
    from loopforge.engine.repositories import IndexRepository
    repo = IndexRepository(run_index_path(run_root), store=store, lock_timeout=3.0)
    repo.write(index)
    return index


def update_run_index(
    store: JsonStore,
    run_root: Path,
    *,
    run_path: Path,
    run: dict[str, Any],
    current_run_id: str | None,
    timestamp: str,
) -> dict[str, Any]:
    index = read_run_index(store, run_root)
    if index is None:
        index = rebuild_run_index(store, run_root, current_run_id=current_run_id, timestamp=timestamp)
    entries = [entry for entry in index["runs"] if str(entry.get("run_id") or "") != str(run.get("run_id") or run_path.name)]
    entries.append(run_summary(run, run_path=run_path, current_run_id=current_run_id))
    entries.sort(key=lambda value: str(value.get("updated_at") or value.get("created_at") or ""), reverse=True)
    updated = {"schema_version": int(CURRENT_INDEX_SCHEMA), "index_version": RUN_INDEX_VERSION, "updated_at": timestamp, "runs": entries}
    from loopforge.engine.repositories import IndexRepository
    repo = IndexRepository(run_index_path(run_root), store=store, lock_timeout=3.0)
    repo.write(updated)
    return updated
