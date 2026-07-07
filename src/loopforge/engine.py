"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

CONFIG_DIR = ".loopforge"
CONFIG_FILE = "config.json"
DEFAULT_PROFILE = "supervised"

CONFIG_KEYS = (
    "project_name",
    "profile",
    "run_root",
    "current_run_id",
    "created_at",
    "updated_at",
)

TEMPLATES: dict[str, str] = {
    "templates/loop.md": """---
loop_version: 1
status: draft
autonomy: supervised
---

# Objective

Describe the concrete outcome.

# Scope

In scope:

Out of scope:

# Inputs

- Task:
- Repository:
- Base commit:
- Project pack:

# Tools

- Skills:
- Commands:
- Adapters:

# Success Checks

- Objective checks:
- Subjective rubric:

# Limits

- Max attempts:
- Max wall time:
- Max output:
- Stop on stagnation after:

# Rollback Strategy

Describe how to return to the previous safe state.

# Ask Human When

- Success criteria are subjective.
- The next action would publish, delete, expose secrets, or spend money.
- Repeated attempts produce the same failure.

# Current Attempt

Record the current attempt and diagnostic.
""",
    "templates/memory.md": """---
memory_version: 1
scope: project
status: active
---

# Stable Project Facts

# User Preferences

# Verification Patterns

# Reusable Decisions

# Known Pitfalls

# Promotion Log

Record why each durable memory item was kept.
""",
    "templates/scratch.md": """---
scratch_version: 1
status: active
---

# Working Notes

# Attempt Log

# Temporary Findings

# Discard Candidates
""",
    "templates/exchange.json": """{
  "exchange_version": 1,
  "run_id": "",
  "producer": "",
  "consumer": "",
  "messages": [],
  "artifacts": [],
  "open_questions": []
}
""",
}


@dataclass(frozen=True)
class InitResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any]
    created: bool
    repaired: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_config_dir(project_dir: Path) -> Path:
    return project_dir / CONFIG_DIR


def project_config_path(project_dir: Path) -> Path:
    return project_config_dir(project_dir) / CONFIG_FILE


def project_name(project_dir: Path) -> str:
    return project_dir.resolve().name or "project"


def default_run_root(project_dir: Path, home: Path | None = None) -> Path:
    base_home = home if home is not None else Path.home()
    return base_home / "LoopForge" / "runs" / project_name(project_dir)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()


def ensure_templates(project_dir: Path) -> None:
    root = project_config_dir(project_dir)
    for relative_name, contents in TEMPLATES.items():
        destination = root / relative_name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")


def new_config(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "project_name": project_name(project_dir),
        "profile": profile,
        "run_root": str(default_run_root(project_dir, home=home)),
        "current_run_id": None,
        "created_at": now,
        "updated_at": now,
    }


def normalize_config(
    project_dir: Path,
    existing: dict[str, Any],
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    config = dict(existing)
    now = utc_now()
    if "created_at" not in config:
        config["created_at"] = now
    if "current_run_id" not in config:
        config["current_run_id"] = None
    if "project_name" not in config:
        config["project_name"] = project_name(project_dir)
    if "profile" not in config:
        config["profile"] = profile
    if "run_root" not in config:
        config["run_root"] = str(default_run_root(project_dir, home=home))
    if "updated_at" not in config:
        config["updated_at"] = now

    repaired = any(config.get(key) != existing.get(key) for key in CONFIG_KEYS)
    if repaired:
        config["updated_at"] = now
    return config, repaired


def initialize_project(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> InitResult:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_templates(project_dir)

    if config_path.exists():
        config, repaired = normalize_config(
            project_dir,
            read_json(config_path),
            profile=profile,
            home=home,
        )
        if repaired:
            write_json_atomic(config_path, config)
        return InitResult(
            project_dir=project_dir,
            config_path=config_path,
            config=config,
            created=False,
            repaired=repaired,
        )

    config = new_config(project_dir, profile=profile, home=home)
    write_json_atomic(config_path, config)
    return InitResult(
        project_dir=project_dir,
        config_path=config_path,
        config=config,
        created=True,
        repaired=False,
    )
