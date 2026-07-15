"""Project identity, registry, and cross-project read models."""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loopforge.engine.storage import DEFAULT_JSON_STORE

PROJECTS_DIRECTORY = "projects"
REGISTRY_FILE = "registry.json"


@dataclass(frozen=True)
class ProjectRegistration:
    ok: bool
    action: str
    project_id: str
    record: dict[str, Any] | None
    conflict_path: Path | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_project_id() -> str:
    return f"project-{uuid.uuid4().hex}"


def path_project_id(project_dir: Path) -> str:
    """Stable collision-safe fallback for callers without persisted config."""

    digest = hashlib.sha256(str(project_dir.resolve()).encode("utf-8")).hexdigest()[:20]
    return f"project-{digest}"


def storage_root(home: Path, project_id: str) -> Path:
    return home / PROJECTS_DIRECTORY / project_id


def registry_path(home: Path) -> Path:
    return home / PROJECTS_DIRECTORY / REGISTRY_FILE


def empty_registry() -> dict[str, Any]:
    return {"registry_version": 1, "projects": {}}


def load_registry(home: Path) -> dict[str, Any]:
    path = registry_path(home)
    if not path.exists():
        return empty_registry()
    try:
        registry = DEFAULT_JSON_STORE.read_object(path)
    except (OSError, ValueError):
        return empty_registry()
    projects = registry.get("projects")
    if not isinstance(projects, dict):
        return empty_registry()
    return {"registry_version": 1, "projects": projects}


def save_registry(home: Path, registry: dict[str, Any]) -> None:
    DEFAULT_JSON_STORE.write_object(registry_path(home), registry)


def git_branch(project_dir: Path) -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    branch = result.stdout.strip() if result.returncode == 0 else ""
    return branch or None


def register_project(
    project_dir: Path,
    config: dict[str, Any],
    home: Path,
    *,
    allow_move: bool = False,
) -> ProjectRegistration:
    project_dir = project_dir.resolve()
    project_id = str(config.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project config has no project_id")
    registry = load_registry(home)
    projects = registry["projects"]
    assert isinstance(projects, dict)
    existing = projects.get(project_id)
    existing_path = None
    if isinstance(existing, dict) and isinstance(existing.get("path"), str):
        existing_path = Path(existing["path"]).expanduser()
    if existing_path is not None and existing_path != project_dir and not allow_move:
        return ProjectRegistration(False, "identity_conflict", project_id, existing, existing_path)

    now = utc_now()
    record = {
        "project_id": project_id,
        "name": str(config.get("project_name") or project_dir.name),
        "path": str(project_dir),
        "profile": str(config.get("profile") or ""),
        "run_root": str(config.get("run_root") or ""),
        "last_opened_at": now,
        "updated_at": now,
    }
    if isinstance(existing, dict):
        record = {**existing, **record}
    projects[project_id] = record
    try:
        save_registry(home, registry)
    except OSError:
        # A project remains usable when a locked-down environment cannot host
        # the optional global index; its local identity is still persisted.
        return ProjectRegistration(True, "registry_unavailable", project_id, record)
    return ProjectRegistration(True, "moved" if existing_path and existing_path != project_dir else "registered", project_id, record)


def regenerate_project_identity(project_dir: Path, config: dict[str, Any], home: Path) -> dict[str, Any]:
    """Return a clone-safe config. The caller persists it atomically."""

    updated = dict(config)
    project_id = new_project_id()
    updated["project_id"] = project_id
    updated["run_root"] = str(storage_root(home, project_id) / "runs")
    updated["updated_at"] = utc_now()
    return updated


def migration_target(home: Path, project_id: str) -> Path:
    return storage_root(home, project_id) / "runs"


def registered_projects(home: Path) -> list[dict[str, Any]]:
    registry = load_registry(home)
    records = registry["projects"]
    assert isinstance(records, dict)
    return [dict(value) for value in records.values() if isinstance(value, dict)]
