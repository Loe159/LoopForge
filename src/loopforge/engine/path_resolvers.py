"""Path validation, containment, and run-directory resolution for the engine."""

from __future__ import annotations

import re
from pathlib import Path

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def validate_identifier(value: str, prefix: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix} id must be a non-empty string")
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"{prefix} id {value!r} contains invalid characters. "
            f"Allowed: alphanumeric, hyphen, underscore; must start with a letter."
        )
    return value


def resolve_confined(allowed_root: Path, *segments: str) -> Path:
    candidate = Path(allowed_root, *segments).resolve()
    try:
        resolved_root = allowed_root.resolve()
    except OSError:
        return candidate
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise ValueError(
            f"Path escape detected: {candidate} is not within {resolved_root}"
        )
    return candidate


def resolve_run_root(home: Path, project_id: str) -> Path:
    validate_identifier(project_id, "project")
    return resolve_confined(home, "projects", project_id, "runs")


def resolve_run_dir(run_root: Path, run_id: str) -> Path:
    validate_identifier(run_id, "run")
    return resolve_confined(run_root, run_id)


def resolve_artifact(run_dir: Path, relative_path: str) -> Path:
    candidate = run_dir / relative_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError:
        raise ValueError(
            f"Artifact path escape detected: {resolved} is not within {run_dir}"
        )
    return resolved