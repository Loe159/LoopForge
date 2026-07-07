"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

CONFIG_DIR = ".loopforge"
CONFIG_FILE = "config.json"
DEFAULT_PROFILE = "supervised"
DEFAULT_PACK = "generic-code"
READY_FOR_VERIFICATION = "ready_for_verification"
SYNTHETIC_LEGACY_BASE_COMMIT = "0" * 40

CONFIG_KEYS = (
    "project_name",
    "profile",
    "run_root",
    "current_run_id",
    "created_at",
    "updated_at",
)

NATIVE_RUN_FILES = (
    "run.json",
    "task.md",
    "loop.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "memory.md",
    "scratch.md",
    "exchange.json",
)

NATIVE_RUN_DIRECTORIES = (
    "attempts",
    "artifacts",
    "metrics",
)

LEGACY_ARTIFACT_NAMES = (
    "task.md",
    "research.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "review.md",
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


@dataclass(frozen=True)
class RunResult:
    project_dir: Path
    config_path: Path
    run_dir: Path
    run_json_path: Path
    config: dict[str, Any]
    run: dict[str, Any]


@dataclass(frozen=True)
class StatusResult:
    project_dir: Path
    config_path: Path
    initialized: bool
    config: dict[str, Any] | None
    run_dir: Path | None
    run_json_path: Path | None
    run: dict[str, Any] | None
    native_artifacts: dict[str, Any] | None
    legacy_artifacts: dict[str, Any] | None
    next_step: str
    blockers: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_config_dir(project_dir: Path) -> Path:
    return project_dir / CONFIG_DIR


def project_config_path(project_dir: Path) -> Path:
    return project_config_dir(project_dir) / CONFIG_FILE


def project_name(project_dir: Path) -> str:
    return project_dir.resolve().name or "project"


def loopforge_home(home: Path | None = None) -> Path:
    if home is not None:
        return home / "LoopForge"
    configured_home = os.environ.get("LOOPFORGE_HOME")
    if configured_home:
        return Path(configured_home).expanduser()
    return Path.home() / "LoopForge"


def default_run_root(project_dir: Path, home: Path | None = None) -> Path:
    return loopforge_home(home=home) / "runs" / project_name(project_dir)


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


def read_project_template(project_dir: Path, relative_name: str) -> str:
    template_path = project_config_dir(project_dir) / "templates" / relative_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    fallback = TEMPLATES.get(f"templates/{relative_name}")
    if fallback is None:
        raise KeyError(f"unknown template: {relative_name}")
    return fallback


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def legacy_templates_dir() -> Path:
    return repository_root() / ".agent" / "templates"


def legacy_artifact_validator() -> Path:
    return repository_root() / ".agent" / "checks" / "validate_artifacts.py"


def legacy_issue_for_task(task_id: str) -> int:
    digits = "".join(character for character in task_id if character.isdigit())
    if digits:
        return int(digits[:12])
    return 1


def render_legacy_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def legacy_template_text(name: str) -> str:
    path = legacy_templates_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"legacy artifact template not found: {path}")
    return path.read_text(encoding="utf-8")


def create_legacy_artifacts(
    legacy_dir: Path,
    *,
    task: str,
    issue: int,
    base_commit: str,
) -> None:
    legacy_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "issue": str(issue),
        "base_commit": base_commit,
        "risk": "low",
        "goal": task,
        "expected_behavior": "LoopForge records the task without requiring GitHub.",
        "acceptance_criteria": "The native run exists and the legacy artifacts validate.",
        "constraints": "Keep this artifact set for imported validator compatibility only.",
        "out_of_scope": "Publishing, GitHub issue ingestion, or adapter execution.",
        "scope": "Compatibility scaffold for the imported portable artifact contract.",
        "current_state": "No separate research is required for run initialization.",
        "evidence": "Native run metadata is stored in run.json.",
        "risks_and_unknowns": "The legacy issue value is a generated compatibility mapping.",
        "rejected_approaches": "Do not make GitHub issue IDs mandatory for native runs.",
        "suggested_verification": "Run the imported artifact validator against this directory.",
        "overview": "Create a product-native LoopForge run with a legacy validation mirror.",
        "preconditions": "LoopForge project configuration exists.",
        "implementation_steps": (
            "Create native run files, create directories, and write legacy artifacts."
        ),
        "files_in_scope": "The external run directory.",
        "verification": "Validate the legacy artifact directory with validate_artifacts.py.",
        "stop_conditions": "Stop before external side effects or destructive filesystem actions.",
        "completed": "The run has been initialized.",
        "remaining": "No adapter attempts have run yet.",
        "decisions": "Use task_id natively and generated numeric issue only for legacy tools.",
        "blockers": "None.",
        "next_step": "Inspect run.json and choose the next bounded action.",
        "candidate": "No implementation candidate exists yet.",
        "deterministic_checks": "Legacy artifact contract validation.",
        "policy_result": "Not evaluated yet.",
        "risk_classification": "Low for initialization scaffold.",
        "residual_risks": "Legacy artifacts are compatibility metadata, not publication authority.",
        "findings": "No review has run yet.",
        "plan_conformance": "No approved plan exists yet.",
        "test_coverage": "Initial CLI tests cover run creation.",
        "recommendation": "Continue with LoopForge-native planning.",
    }
    statuses = {
        "task.md": "approved",
        "research.md": "not_required",
        "plan.md": "awaiting_approval",
        "progress.md": "not_started",
        "verification.md": "pending",
        "review.md": "pending",
    }
    for name in LEGACY_ARTIFACT_NAMES:
        text = render_legacy_template(legacy_template_text(name), values)
        text = text.replace(
            {
                "task.md": "status: awaiting_approval",
                "research.md": "status: pending",
                "plan.md": "status: awaiting_approval",
                "progress.md": "status: not_started",
                "verification.md": "status: pending",
                "review.md": "status: pending",
            }[name],
            f"status: {statuses[name]}",
        )
        (legacy_dir / name).write_text(text, encoding="utf-8")


def native_artifact_state(run_dir: Path) -> dict[str, Any]:
    missing_files = [name for name in NATIVE_RUN_FILES if not (run_dir / name).is_file()]
    missing_directories = [
        name for name in NATIVE_RUN_DIRECTORIES if not (run_dir / name).is_dir()
    ]
    total = len(NATIVE_RUN_FILES) + len(NATIVE_RUN_DIRECTORIES)
    present = total - len(missing_files) - len(missing_directories)
    return {
        "status": "complete" if present == total else "incomplete",
        "present": present,
        "total": total,
        "missing_files": missing_files,
        "missing_directories": missing_directories,
    }


def legacy_artifact_state(run: dict[str, Any]) -> dict[str, Any]:
    legacy = run.get("legacy", {})
    if not isinstance(legacy, dict):
        legacy = {}
    artifact_dir_text = legacy.get("artifact_dir")
    if not isinstance(artifact_dir_text, str) or not artifact_dir_text:
        return {
            "status": "missing",
            "artifact_dir": None,
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": ["run.json does not declare legacy.artifact_dir"],
        }

    artifact_dir = Path(artifact_dir_text).expanduser()
    missing = [name for name in LEGACY_ARTIFACT_NAMES if not (artifact_dir / name).is_file()]
    if missing:
        return {
            "status": "missing",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [f"missing legacy artifacts: {', '.join(missing)}"],
        }

    validator = legacy_artifact_validator()
    if not validator.exists():
        return {
            "status": "unchecked",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [f"validator not found: {validator}"],
        }

    try:
        result = subprocess.run(
            [sys.executable, str(validator), "--run", str(artifact_dir), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "status": "unchecked",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [str(error)],
        }

    try:
        validator_result = json.loads(result.stdout)
    except json.JSONDecodeError:
        validator_result = {"errors": [{"message": result.stderr.strip() or result.stdout.strip()}]}

    errors = validator_result.get("errors", [])
    return {
        "status": "valid" if result.returncode == 0 else "invalid",
        "artifact_dir": str(artifact_dir),
        "issue": legacy.get("issue"),
        "base_commit": legacy.get("base_commit"),
        "errors": errors if isinstance(errors, list) else [],
    }


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


def detect_git_base_commit(project_dir: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def describe_next_step(run: dict[str, Any]) -> str:
    status = str(run.get("status", "unknown"))
    blockers = run.get("blockers", [])
    if isinstance(blockers, list) and blockers:
        return "Resolve the listed blockers before continuing the loop."
    if status == READY_FOR_VERIFICATION:
        return "Review the run artifacts, then add verification in the next implementation phase."
    return "Inspect the run artifacts and decide the next bounded action."


def current_status(project_dir: Path) -> StatusResult:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=False,
            config=None,
            run_dir=None,
            run_json_path=None,
            run=None,
            native_artifacts=None,
            legacy_artifacts=None,
            next_step="Initialize LoopForge with `loopforge init`.",
            blockers=[],
        )

    config = normalize_config(project_dir, read_json(config_path))[0]
    current_run_id = config.get("current_run_id")
    if not current_run_id:
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=True,
            config=config,
            run_dir=None,
            run_json_path=None,
            run=None,
            native_artifacts=None,
            legacy_artifacts=None,
            next_step='Create a run with `loopforge run --task "..."`.',
            blockers=[],
        )

    run_dir = Path(str(config["run_root"])).expanduser() / str(current_run_id)
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=True,
            config=config,
            run_dir=run_dir,
            run_json_path=run_json_path,
            run=None,
            native_artifacts=native_artifact_state(run_dir) if run_dir.exists() else None,
            legacy_artifacts=None,
            next_step="Restore the missing run artifacts or create a new run.",
            blockers=[f"current run metadata not found: {run_json_path}"],
        )

    run = read_json(run_json_path)
    raw_blockers = run.get("blockers", [])
    blockers = [str(blocker) for blocker in raw_blockers] if isinstance(raw_blockers, list) else []
    return StatusResult(
        project_dir=project_dir,
        config_path=config_path,
        initialized=True,
        config=config,
        run_dir=run_dir,
        run_json_path=run_json_path,
        run=run,
        native_artifacts=native_artifact_state(run_dir),
        legacy_artifacts=legacy_artifact_state(run),
        next_step=describe_next_step(run),
        blockers=blockers,
    )


def new_run_id() -> str:
    timestamp = utc_now().replace("-", "").replace(":", "").replace("Z", "Z")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def create_run(project_dir: Path, task: str) -> RunResult:
    if not task.strip():
        raise ValueError("task must not be empty")

    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} does not exist; run `loopforge init` first")

    config = normalize_config(project_dir, read_json(config_path))[0]
    run_root = Path(str(config["run_root"])).expanduser()
    run_id = new_run_id()
    run_dir = run_root / run_id
    while run_dir.exists():
        run_id = new_run_id()
        run_dir = run_root / run_id

    attempts_dir = run_dir / "attempts"
    artifacts_dir = run_dir / "artifacts"
    metrics_dir = run_dir / "metrics"
    legacy_dir = artifacts_dir / "legacy-agent"
    for directory in (attempts_dir, artifacts_dir, metrics_dir):
        directory.mkdir(parents=True, exist_ok=False)

    now = utc_now()
    base_commit = detect_git_base_commit(project_dir)
    task_id = run_id
    legacy_issue = legacy_issue_for_task(task_id)
    legacy_base_commit = base_commit or SYNTHETIC_LEGACY_BASE_COMMIT
    run_data: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "task": task.strip(),
        "project_root": str(project_dir),
        "base_commit": base_commit,
        "profile": config["profile"],
        "pack": DEFAULT_PACK,
        "status": READY_FOR_VERIFICATION,
        "created_at": now,
        "success_checks": [],
        "blockers": [],
        "artifacts": {
            "task": str(run_dir / "task.md"),
            "loop": str(run_dir / "loop.md"),
            "plan": str(run_dir / "plan.md"),
            "progress": str(run_dir / "progress.md"),
            "verification": str(run_dir / "verification.md"),
            "memory": str(run_dir / "memory.md"),
            "scratch": str(run_dir / "scratch.md"),
            "exchange": str(run_dir / "exchange.json"),
            "attempts": str(attempts_dir),
            "artifacts": str(artifacts_dir),
            "metrics": str(metrics_dir),
            "legacy_agent": str(legacy_dir),
        },
        "legacy": {
            "issue": legacy_issue,
            "issue_source": "generated_from_task_id",
            "base_commit": legacy_base_commit,
            "base_commit_source": "git" if base_commit else "synthetic_no_git_sentinel",
            "artifact_dir": str(legacy_dir),
            "validator": str(legacy_artifact_validator()),
        },
    }

    write_json_atomic(run_dir / "run.json", run_data)
    (run_dir / "task.md").write_text(f"# Task\n\n{task.strip()}\n", encoding="utf-8")
    (run_dir / "loop.md").write_text(
        read_project_template(project_dir, "loop.md"),
        encoding="utf-8",
    )
    (run_dir / "plan.md").write_text("# Plan\n\nNo plan recorded yet.\n", encoding="utf-8")
    (run_dir / "progress.md").write_text(
        "# Progress\n\nNo attempts recorded yet.\n",
        encoding="utf-8",
    )
    (run_dir / "verification.md").write_text(
        "# Verification\n\nVerification has not run yet.\n",
        encoding="utf-8",
    )
    (run_dir / "memory.md").write_text(
        read_project_template(project_dir, "memory.md"),
        encoding="utf-8",
    )
    (run_dir / "scratch.md").write_text(
        read_project_template(project_dir, "scratch.md"),
        encoding="utf-8",
    )
    write_json_atomic(
        run_dir / "exchange.json",
        {
            "exchange_version": 1,
            "run_id": run_id,
            "producer": "",
            "consumer": "",
            "messages": [],
            "artifacts": [],
            "open_questions": [],
        },
    )
    create_legacy_artifacts(
        legacy_dir,
        task=task.strip(),
        issue=legacy_issue,
        base_commit=legacy_base_commit,
    )

    updated_config = dict(config)
    updated_config["current_run_id"] = run_id
    updated_config["updated_at"] = now
    write_json_atomic(config_path, updated_config)

    return RunResult(
        project_dir=project_dir,
        config_path=config_path,
        run_dir=run_dir,
        run_json_path=run_dir / "run.json",
        config=updated_config,
        run=run_data,
    )
