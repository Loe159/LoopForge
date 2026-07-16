"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loopforge.adapters.kilo_code import (
    DEFAULT_IMPLEMENTATION_AGENT,
    DEFAULT_READONLY_AGENT,
    command_with_prompt as kilo_command_with_prompt,
    headless_run_command as kilo_headless_run_command,
    is_kilo_run_command,
)
from loopforge.engine.packs import PackRegistry
from loopforge.engine.metrics import MetricsService
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine import projects as project_registry
from loopforge.engine import indexes as run_indexes
from loopforge.engine.git_state import DEFAULT_GIT_STATE_SERVICE

CONFIG_DIR = ".loopforge"
CONFIG_FILE = "config.json"
PROJECT_MEMORY_FILE = "memory.md"
DEFAULT_PROFILE = "supervised"
DEFAULT_PACK = "generic-code"
DEFAULT_ADAPTER = "codex"
WORKSPACE_MODE_GIT_WORKTREE = "git-worktree"
WORKSPACE_MODE_SHARED_CHECKOUT = "shared-checkout"
READY_FOR_VERIFICATION = "ready_for_verification"
ADAPTER_BLOCKED = "adapter_blocked"
LOOP_CONTRACT_DRAFT = "loop_contract_draft"
LOOP_CONTRACT_READY = "loop_contract_ready"
VERIFIED = "verified"
VERIFICATION_FAILED = "verification_failed"
METRICS_RECORD_FILE = "record.json"
USER_PREFERENCES_FILE = "preferences.json"

DEFAULT_USER_PREFERENCES = {
    "theme": "default",
    "statusline": "full",
    "keymap": "emacs",
}

SUPPORTED_ADAPTERS = (
    "codex",
    "claude-code",
    "kilo-code",
    "aider",
    "opencode",
    "mini-swe-agent",
    "local-adapter-fixture",
)

SUPPORTED_PROFILES = (
    "assist",
    "supervised",
    "autonomous",
    "strict",
)

PROFILE_POLICIES: dict[str, dict[str, Any]] = {
    "assist": {
        "summary": (
            "read-only assistance plus LoopForge bookkeeping; adapter execution, "
            "verification artifacts, and durable memory promotion are blocked"
        ),
        "mutation": "blocked for workspace-changing transitions",
        "attempts": "disabled",
        "memory": "proposals only; promotion blocked",
    },
    "supervised": {
        "summary": "bounded mutation is allowed; major transitions are surfaced for review",
        "mutation": "allowed for bounded attempts and verification",
        "attempts": "one bounded adapter attempt at a time",
        "memory": "promotion requires approval or a pack rule",
    },
    "autonomous": {
        "summary": (
            "bounded attempts may proceed only with objective checks and no stop-condition risk"
        ),
        "mutation": "allowed while checks are objective and stop conditions are absent",
        "attempts": "bounded by contract limits and stagnation checks",
        "memory": "promotion still requires approval or a pack rule",
    },
    "strict": {
        "summary": "explicit confirmation is required before mutation or memory promotion",
        "mutation": "requires --confirm for adapter execution and verification",
        "attempts": "requires explicit confirmation before each adapter attempt",
        "memory": "approval plus --confirm is required for promotion",
    },
}

AGENT_COMMANDS = {
    "codex": "codex",
    "claude-code": "claude",
    "kilo-code": "kilo",
    "aider": "aider",
    "opencode": "opencode",
    "mini-swe-agent": "mini-swe-agent",
}

CONFIG_KEYS = (
    "project_id",
    "project_name",
    "profile",
    "run_root",
    "current_run_id",
    "default_adapter",
    "default_adapter_args",
    "created_at",
    "updated_at",
)

NATIVE_RUN_FILES = (
    "run.json",
    "task.md",
    "loop.md",
    "research.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "review.md",
    "memory.md",
    "scratch.md",
    "exchange.json",
)

NATIVE_RUN_DIRECTORIES = (
    "attempts",
    "artifacts",
    "metrics",
)

REQUIRED_LOOP_SECTIONS = (
    "Objective",
    "Scope",
    "Inputs",
    "Selected Project Pack",
    "Selected Skills",
    "Allowed Tools",
    "Success Checks",
    "Limits",
    "Stagnation Rule",
    "Rollback Strategy",
    "Human Review Conditions",
)

DEFAULT_ALLOWED_TOOLS = (
    "Read project files and LoopForge run artifacts.",
    "Write bounded changes inside the target workspace.",
    "Run local deterministic verification commands.",
)

WORKFLOW_STAGES = (
    "task",
    "research",
    "plan",
    "implementation",
    "verification",
    "review",
    "publication",
)

DEFAULT_CURRENT_STAGE = "task_draft"
TASK_APPROVED_STAGE = "task_approved"
RESEARCH_READY_STAGE = "research_ready"
PLAN_READY_STAGE = "plan_ready"
IMPLEMENTATION_READY_STAGE = "implementation_ready"
VERIFICATION_READY_STAGE = "verification_ready"
REVIEW_READY_STAGE = "review_ready"
REVIEW_COMPLETE_STAGE = "review_complete"
PUBLICATION_READY_STAGE = "draft_publication_ready"

READONLY_WORKFLOW_STAGES = ("research", "plan", "review")

REQUIRED_READONLY_STAGE_SECTIONS = {
    "research": (
        "Scope",
        "Current State",
        "Evidence",
        "Risks And Unknowns",
        "Rejected Approaches",
        "Suggested Verification",
    ),
    "plan": (
        "Overview",
        "Preconditions",
        "Implementation Steps",
        "Files In Scope",
        "Out Of Scope",
        "Verification",
        "Stop Conditions",
    ),
    "review": (
        "Scope",
        "Findings",
        "Plan Conformance",
        "Test Coverage",
        "Risks And Unknowns",
        "Recommendation",
    ),
}

READONLY_STAGE_SUCCESS = {
    "research": ("complete", RESEARCH_READY_STAGE),
    "plan": ("awaiting_approval", PLAN_READY_STAGE),
    "review": ("complete", REVIEW_COMPLETE_STAGE),
}

SUBJECTIVE_TASK_MARKERS = (
    "better",
    "copy",
    "design",
    "draft",
    "evaluate",
    "improve",
    "polish",
    "rewrite",
    "review",
    "summarize",
    "ux",
)

DURABLE_MEMORY_SECTIONS = (
    "Stable Project Facts",
    "User Preferences",
    "Verification Patterns",
    "Reusable Decisions",
    "Known Pitfalls",
)

MEMORY_CATEGORY_ALIASES = {
    "fact": "Stable Project Facts",
    "facts": "Stable Project Facts",
    "preference": "User Preferences",
    "preferences": "User Preferences",
    "verify": "Verification Patterns",
    "verification": "Verification Patterns",
    "decision": "Reusable Decisions",
    "decisions": "Reusable Decisions",
    "pitfall": "Known Pitfalls",
    "pitfalls": "Known Pitfalls",
}

SECRET_MARKERS = (
    "api key",
    "apikey",
    "authorization:",
    "bearer ",
    "client secret",
    "password",
    "private key",
    "secret",
    "ssh-rsa",
    "token",
)

UNTRUSTED_TEXT_MARKERS = (
    "raw issue",
    "issue body",
    "raw comment",
    "comment body",
    "untrusted body",
)

AUTONOMOUS_STOP_MARKERS: dict[str, tuple[str, ...]] = {
    "publication": (
        "deploy",
        "publish",
        "release",
        "send email",
        "open pull request",
        "create pull request",
        "push",
        "upload",
    ),
    "deletion": (
        "delete",
        "destroy",
        "drop database",
        "remove files",
        "rm -rf",
        "wipe",
    ),
    "secrets": (
        "api key",
        "credential",
        "expose secret",
        "password",
        "private key",
        "secret",
        "token",
    ),
    "money": (
        "billing",
        "buy",
        "charge",
        "pay ",
        "purchase",
        "spend money",
    ),
    "external side effects": (
        "call external",
        "cloud",
        "external api",
        "http://",
        "https://",
        "network",
        "production",
        "remote side effect",
        "webhook",
    ),
}

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
    registration: project_registry.ProjectRegistration | None = None
    migrated_run_root: Path | None = None


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
    loop_contract: dict[str, Any] | None
    verification: dict[str, Any] | None
    memory: dict[str, Any] | None
    next_step: str
    blockers: list[str]


@dataclass(frozen=True)
class ContinueResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    contract: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]
    attempt: dict[str, Any] | None = None


@dataclass(frozen=True)
class StageResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    stage: str | None
    ok: bool
    message: str
    blockers: list[str]
    artifact_path: Path | None = None


@dataclass(frozen=True)
class VerifyResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]
    verification: dict[str, Any] | None = None


@dataclass(frozen=True)
class LearnResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    proposals: list[dict[str, Any]]
    promoted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    proposal_path: Path | None
    blockers: list[str]


@dataclass(frozen=True)
class MetricsRecordResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    record_path: Path | None
    record: dict[str, Any] | None
    blockers: list[str]


@dataclass(frozen=True)
class MetricsSummaryResult:
    project_dir: Path
    run_root: Path | None
    ok: bool
    message: str
    records: list[dict[str, Any]]
    summary: dict[str, Any]
    blockers: list[str]


@dataclass(frozen=True)
class DashboardResult:
    project_dir: Path
    ok: bool
    snapshot: dict[str, Any]
    blockers: list[str]


@dataclass(frozen=True)
class RunListResult:
    project_dir: Path
    run_root: Path | None
    initialized: bool
    config: dict[str, Any] | None
    current_run_id: str | None
    runs: list[dict[str, Any]]
    blockers: list[str]


@dataclass(frozen=True)
class ProjectListResult:
    home: Path
    projects: list[dict[str, Any]]
    blockers: list[str]


@dataclass(frozen=True)
class IndexRepairResult:
    project_dir: Path
    run_root: Path | None
    ok: bool
    message: str
    diagnostics: dict[str, Any]
    blockers: list[str]


@dataclass(frozen=True)
class GlobalRunListResult:
    home: Path
    runs: list[dict[str, Any]]
    blockers: list[str]


@dataclass(frozen=True)
class OpenProjectResult:
    project_dir: Path | None
    init: InitResult | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class ResumeRunResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class CompactContextResult:
    project_dir: Path
    run_dir: Path | None
    path: Path | None
    ok: bool
    message: str
    summary: str
    blockers: list[str]


@dataclass(frozen=True)
class ConfigUpdateResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class GuidedAction:
    id: str
    label: str
    command: str
    risk: str
    requires_confirmation: bool
    why: str


@dataclass(frozen=True)
class GuidanceResult:
    project_dir: Path
    state: str
    summary: str
    priority: str
    diagnostics: list[str]
    recommended_actions: list[GuidedAction]
    blocked_reasons: list[str]
    evidence: list[str]


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
    return platform_data_home() / "loopforge"


def user_preferences_path(home: Path | None = None) -> Path:
    """Return the user-scoped interactive preferences file.

    Visual choices are deliberately kept outside ``.loopforge/config.json``:
    that file travels with a project, while a person's terminal preferences do
    not.
    """

    return loopforge_home(home=home) / USER_PREFERENCES_FILE


def user_preferences(home: Path | None = None) -> dict[str, str]:
    """Load normalized user-scoped terminal preferences."""

    path = user_preferences_path(home=home)
    values = dict(DEFAULT_USER_PREFERENCES)
    if not path.exists():
        return values
    try:
        stored = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return values
    for key, allowed in {
        "theme": {"default", "light", "dark", "mono"},
        "statusline": {"full", "compact", "off"},
        "keymap": {"emacs", "vim"},
    }.items():
        value = stored.get(key)
        if isinstance(value, str) and value in allowed:
            values[key] = value
    return values


def update_user_preferences(
    updates: dict[str, str], home: Path | None = None
) -> dict[str, str]:
    """Persist supported terminal preferences at user scope."""

    values = user_preferences(home=home)
    allowed_values = {
        "theme": {"default", "light", "dark", "mono"},
        "statusline": {"full", "compact", "off"},
        "keymap": {"emacs", "vim"},
    }
    for key, value in updates.items():
        if key not in allowed_values or value not in allowed_values[key]:
            raise ValueError(f"unsupported user preference: {key}={value}")
        values[key] = value
    write_json_atomic(user_preferences_path(home=home), values)
    return values


def platform_data_home() -> Path:
    if sys.platform == "win32":
        configured = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if configured:
            return Path(configured).expanduser()
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    configured = os.environ.get("XDG_DATA_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share"


def platform_cache_home() -> Path:
    configured_home = os.environ.get("LOOPFORGE_HOME")
    if configured_home:
        return Path(configured_home).expanduser() / "cache"
    if sys.platform == "win32":
        configured = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
        if configured:
            return Path(configured).expanduser() / "loopforge" / "cache"
        return Path.home() / "AppData" / "Local" / "loopforge" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "loopforge"
    configured = os.environ.get("XDG_CACHE_HOME")
    if configured:
        return Path(configured).expanduser() / "loopforge"
    return Path.home() / ".cache" / "loopforge"


def default_run_root(
    project_dir: Path,
    home: Path | None = None,
    *,
    project_id: str | None = None,
) -> Path:
    return project_registry.storage_root(
        loopforge_home(home=home), project_id or project_registry.path_project_id(project_dir)
    ) / "runs"


def default_workspace_root(
    project_dir: Path,
    home: Path | None = None,
    *,
    project_id: str | None = None,
) -> Path:
    return project_registry.storage_root(
        loopforge_home(home=home), project_id or project_registry.path_project_id(project_dir)
    ) / "workspaces"


def read_json(path: Path) -> dict[str, Any]:
    return DEFAULT_JSON_STORE.read_object(path)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    DEFAULT_JSON_STORE.write_object(path, data)


def _project_summary_from_index(
    project_dir: Path,
    config: dict[str, Any],
    index: dict[str, Any],
    *,
    index_state: str = "ready",
) -> dict[str, Any]:
    runs = index.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    current_id = str(config.get("current_run_id") or "")
    current = next(
        (entry for entry in runs if str(entry.get("run_id") or "") == current_id),
        None,
    )
    last_activity = max(
        (str(entry.get("updated_at") or entry.get("created_at") or "") for entry in runs),
        default="",
    )
    now = utc_now()
    branch, head_signature = project_registry.git_head_summary(project_dir)
    return {
        "initialized": True,
        "name": str(config.get("project_name") or project_dir.name),
        "path": str(project_dir.resolve()),
        "profile": str(config.get("profile") or ""),
        "run_root": str(config.get("run_root") or ""),
        "current_run_id": current_id or None,
        "run_count": len(runs),
        "attention": str((current or {}).get("attention") or "ready"),
        "last_activity": last_activity,
        "branch": branch,
        "last_known_branch": branch,
        "git_head_signature": head_signature,
        "summary_revision": 1,
        "summary_source_timestamp": now,
        "index_state": index_state,
        "updated_at": now,
    }


def _home_from_run_root(run_root: Path) -> Path:
    """Return the LoopForge data root for a configured project run root."""

    # <home>/projects/<project-id>/runs
    try:
        return run_root.parents[2]
    except IndexError:
        return loopforge_home()


def _sync_project_indexes(project_dir: Path, config: dict[str, Any], *, rebuild: bool = False) -> dict[str, Any]:
    """Synchronize derived run and registry indexes from authoritative data."""

    run_root = Path(str(config["run_root"])).expanduser()
    current_id = str(config.get("current_run_id") or "") or None
    timestamp = utc_now()
    index = (
        run_indexes.rebuild_run_index(
            DEFAULT_JSON_STORE, run_root, current_run_id=current_id, timestamp=timestamp
        )
        if rebuild
        else run_indexes.read_run_index(DEFAULT_JSON_STORE, run_root)
    )
    if index is None:
        index = run_indexes.rebuild_run_index(
            DEFAULT_JSON_STORE, run_root, current_run_id=current_id, timestamp=timestamp
        )
    summary = _project_summary_from_index(project_dir, config, index)
    existing = project_registry.update_project_summary(
        _home_from_run_root(run_root), str(config.get("project_id") or ""), summary
    )
    if existing is None:
        # A registry may be unavailable or absent during migration. The local
        # run index remains valid and registration will create the companion
        # record on the next open/init.
        summary["index_state"] = "registry_unavailable"
    return index


def persist_run_json(project_dir: Path, run_json_path: Path, run: dict[str, Any]) -> None:
    """Persist authoritative run state, then its recoverable derived indexes."""

    config = normalize_config(project_dir, read_json(project_config_path(project_dir)))[0]
    run_root = Path(str(config["run_root"])).expanduser()
    timestamp = utc_now()
    try:
        run_indexes.mark_dirty(DEFAULT_JSON_STORE, run_root, timestamp=timestamp)
    except OSError:
        # The authoritative project-local mutation must stay usable when the
        # optional global data root is locked down.
        write_json_atomic(run_json_path, run)
        return
    write_json_atomic(run_json_path, run)
    try:
        index = run_indexes.update_run_index(
            DEFAULT_JSON_STORE,
            run_root,
            run_path=run_json_path.parent,
            run=run,
            current_run_id=str(config.get("current_run_id") or "") or None,
            timestamp=timestamp,
        )
        project_registry.update_project_summary(
            _home_from_run_root(run_root),
            str(config.get("project_id") or ""),
            _project_summary_from_index(project_dir, config, index),
        )
    except OSError:
        return
    run_indexes.clear_dirty(run_root)


def persist_project_config(project_dir: Path, config_path: Path, config: dict[str, Any]) -> None:
    """Persist config and refresh its compact project summary."""

    run_root = Path(str(config.get("run_root") or "")).expanduser()
    indexed = False
    if str(run_root):
        try:
            run_indexes.mark_dirty(DEFAULT_JSON_STORE, run_root, timestamp=utc_now())
            indexed = True
        except OSError:
            pass
    write_json_atomic(config_path, config)
    if indexed:
        try:
            _sync_project_indexes(project_dir, config)
        except OSError:
            return
        run_indexes.clear_dirty(run_root)


def index_diagnostics(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return {"initialized": False, "run_index": "unavailable", "reason": "project is not initialized"}
    config = normalize_config(project_dir, read_json(config_path))[0]
    run_root = Path(str(config["run_root"])).expanduser()
    index = run_indexes.read_run_index(DEFAULT_JSON_STORE, run_root)
    return {
        "initialized": True,
        "run_root": str(run_root),
        "run_index": "ready" if index is not None else "rebuild_required",
        "dirty": run_indexes.dirty_marker_path(run_root).exists(),
        "run_count": len(index.get("runs", [])) if index is not None else None,
        "index_version": index.get("index_version") if index is not None else None,
    }


def rebuild_indexes(project_dir: Path) -> IndexRepairResult:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return IndexRepairResult(project_dir, None, False, "LoopForge index rebuild failed.", index_diagnostics(project_dir), ["Initialize LoopForge first."])
    config = normalize_config(project_dir, read_json(config_path))[0]
    run_root = Path(str(config["run_root"])).expanduser()
    run_indexes.mark_dirty(DEFAULT_JSON_STORE, run_root, timestamp=utc_now())
    try:
        index = _sync_project_indexes(project_dir, config, rebuild=True)
    except (OSError, ValueError) as error:
        return IndexRepairResult(project_dir, run_root, False, "LoopForge index rebuild failed.", index_diagnostics(project_dir), [str(error)])
    run_indexes.clear_dirty(run_root)
    diagnostics = index_diagnostics(project_dir)
    diagnostics["run_count"] = len(index.get("runs", []))
    return IndexRepairResult(project_dir, run_root, True, "LoopForge indexes rebuilt safely.", diagnostics, [])


def initial_workflow_state() -> dict[str, Any]:
    stage_statuses = {stage: "pending" for stage in WORKFLOW_STAGES}
    stage_statuses["task"] = "draft"
    return {
        "current_stage": DEFAULT_CURRENT_STAGE,
        "stage_statuses": stage_statuses,
        "approval": {
            "approved": False,
            "source": "none",
            "approved_at": None,
        },
        "risk": {
            "level": "unknown",
            "route": "unknown",
            "reasons": [],
        },
        "human_gates": {
            "initial_task_approval": {
                "required": True,
                "status": "pending",
            },
            "plan_approval": {
                "required": True,
                "status": "pending",
            },
            "review_approval": {
                "required": True,
                "status": "pending",
            },
        },
        "publish_eligibility": {
            "eligible": False,
            "reasons": ["workflow has not reached publication"],
        },
    }


def validate_task_definition(
    *,
    task: str,
    success_checks: list[str],
    profile: str,
    subjective: bool,
    subjective_rubric: str,
) -> dict[str, Any]:
    missing: list[str] = []
    if not task.strip():
        missing.append("goal")
    if not success_checks:
        missing.append("objective success check")
    if profile == "autonomous" and subjective and not subjective_rubric.strip():
        missing.append("subjective rubric")
    return {
        "status": "valid" if not missing else "needs_input",
        "missing": missing,
        "checks": {
            "goal": bool(task.strip()),
            "objective_success_checks": bool(success_checks),
            "subjective_rubric": not (
                profile == "autonomous" and subjective and not subjective_rubric.strip()
            ),
        },
    }


def normalize_run_workflow_state(run: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(run)
    normalized.pop("legacy", None)
    artifacts = normalized.get("artifacts")
    if isinstance(artifacts, dict):
        normalized["artifacts"] = {
            key: value for key, value in artifacts.items() if key != "legacy_agent"
        }
    defaults = initial_workflow_state()

    current_stage = normalized.get("current_stage")
    if not isinstance(current_stage, str) or not current_stage.strip():
        normalized["current_stage"] = defaults["current_stage"]

    stage_statuses = normalized.get("stage_statuses")
    if not isinstance(stage_statuses, dict):
        stage_statuses = {}
    normalized["stage_statuses"] = {
        **defaults["stage_statuses"],
        **{str(key): value for key, value in stage_statuses.items()},
    }

    for key in ("approval", "risk", "human_gates", "publish_eligibility"):
        value = normalized.get(key)
        if isinstance(value, dict):
            normalized[key] = {**defaults[key], **value}
        else:
            normalized[key] = defaults[key]

    reasons = normalized["risk"].get("reasons")
    if not isinstance(reasons, list):
        normalized["risk"]["reasons"] = []
    publish_reasons = normalized["publish_eligibility"].get("reasons")
    if not isinstance(publish_reasons, list):
        normalized["publish_eligibility"]["reasons"] = defaults["publish_eligibility"][
            "reasons"
        ]
    return normalized


def apply_initial_task_approval(
    run: dict[str, Any],
    *,
    approved: bool,
    source: str = "none",
    approved_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    task_validation = normalized.get("task_validation", {})
    task_is_valid = not isinstance(task_validation, dict) or task_validation.get(
        "status"
    ) in {None, "valid"}
    approved = approved and task_is_valid
    if approved:
        normalized["current_stage"] = TASK_APPROVED_STAGE
        normalized["stage_statuses"]["task"] = "approved"
        normalized["approval"] = {
            "approved": True,
            "source": clean_source or "local",
            "approved_at": approved_at or utc_now(),
        }
        normalized["human_gates"]["initial_task_approval"] = {
            **initial_workflow_state()["human_gates"]["initial_task_approval"],
            "status": "approved",
        }
        return normalized

    normalized["current_stage"] = DEFAULT_CURRENT_STAGE
    normalized["stage_statuses"]["task"] = "draft"
    normalized["approval"] = {
        "approved": False,
        "source": clean_source or "none",
        "approved_at": None,
    }
    normalized["human_gates"]["initial_task_approval"] = {
        **initial_workflow_state()["human_gates"]["initial_task_approval"],
        "status": "pending",
    }
    return normalized


def apply_plan_approval(
    run: dict[str, Any],
    *,
    source: str = "local",
    approved_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    normalized["current_stage"] = IMPLEMENTATION_READY_STAGE
    normalized["stage_statuses"]["plan"] = "approved"
    normalized["human_gates"]["plan_approval"] = {
        **initial_workflow_state()["human_gates"]["plan_approval"],
        "status": "approved",
        "source": clean_source or "local",
        "approved_at": approved_at or utc_now(),
    }
    normalized["blockers"] = []
    return normalized


def apply_review_approval(
    run: dict[str, Any],
    *,
    source: str = "local",
    approved_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    normalized["current_stage"] = REVIEW_READY_STAGE
    normalized["stage_statuses"]["review"] = "approved"
    normalized["human_gates"]["review_approval"] = {
        **initial_workflow_state()["human_gates"]["review_approval"],
        "status": "approved",
        "source": clean_source or "local",
        "approved_at": approved_at or utc_now(),
    }
    normalized["publish_eligibility"] = {
        "eligible": True,
        "mode": "draft",
        "reasons": ["verified work has explicit review approval"],
    }
    normalized["blockers"] = []
    return normalized


def apply_draft_publication_prepared(
    run: dict[str, Any],
    *,
    artifact_path: str,
) -> dict[str, Any]:
    normalized = normalize_run_workflow_state(run)
    normalized["current_stage"] = PUBLICATION_READY_STAGE
    normalized["stage_statuses"]["publication"] = "draft_prepared"
    normalized["publication"] = {
        "status": "draft_prepared",
        "mode": "draft",
        "artifact_path": artifact_path,
        "network": {"performed": False},
    }
    normalized["publish_eligibility"] = {
        "eligible": True,
        "mode": "draft",
        "status": "prepared",
        "reasons": ["draft PR artifact prepared after explicit review approval"],
        "artifact": artifact_path,
    }
    normalized["blockers"] = []
    return normalized


def ensure_templates(project_dir: Path) -> None:
    root = project_config_dir(project_dir)
    for relative_name, contents in TEMPLATES.items():
        destination = root / relative_name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
    for directory_name in ("packs", "skills"):
        (root / directory_name).mkdir(parents=True, exist_ok=True)


def read_project_template(project_dir: Path, relative_name: str) -> str:
    template_path = project_config_dir(project_dir) / "templates" / relative_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    fallback = TEMPLATES.get(f"templates/{relative_name}")
    if fallback is None:
        raise KeyError(f"unknown template: {relative_name}")
    return fallback


def durable_memory_path(project_dir: Path) -> Path:
    return project_config_dir(project_dir) / PROJECT_MEMORY_FILE


def ensure_project_memory(project_dir: Path) -> Path:
    path = durable_memory_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(read_project_template(project_dir, "memory.md"), encoding="utf-8")
    return path


def durable_memory_items(project_dir: Path) -> dict[str, list[str]]:
    path = durable_memory_path(project_dir)
    if not path.exists():
        return {section: [] for section in DURABLE_MEMORY_SECTIONS}
    sections = markdown_sections(path.read_text(encoding="utf-8"))
    return {
        section: bullet_items(section_text(sections, section))
        for section in DURABLE_MEMORY_SECTIONS
    }


def memory_item_count(items: dict[str, list[str]]) -> int:
    return sum(len(values) for values in items.values())


def render_run_memory_snapshot(project_dir: Path, run_id: str) -> str:
    source = ensure_project_memory(project_dir)
    items = durable_memory_items(project_dir)
    lines = [
        "---",
        "memory_version: 1",
        "scope: run",
        "status: active",
        f"source: {source}",
        f"captured_at: {utc_now()}",
        "---",
        "",
        "# Durable Project Memory Snapshot",
        "",
        "Compact project memory loaded for this run. Promotion logs and old run",
        "transcripts are intentionally omitted.",
        "",
    ]
    for section in DURABLE_MEMORY_SECTIONS:
        lines.extend([f"# {section}", ""])
        values = items.get(section, [])
        if values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- None recorded.")
        lines.append("")
    lines.extend(
        [
            "# Run Memory Notes",
            "",
            "Use `scratch.md` for temporary context and `loopforge learn` to propose",
            "durable updates.",
            "",
        ]
    )
    return "\n".join(lines)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def local_implementation_adapter() -> Path:
    return Path(__file__).resolve().parents[1] / "adapters" / "local_implementation_adapter.py"


def imported_check(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "checks" / name


def default_diff_policy() -> Path:
    from loopforge.contracts import policy_path

    return policy_path("diff-policy.json")


def default_risk_policy() -> Path:
    from loopforge.contracts import policy_path

    return policy_path("risk-rules.json")


def _pack_registry(project_dir: Path) -> PackRegistry:
    return PackRegistry(
        project_dir,
        bundled_root=repository_root(),
        bundled_packs_root=Path(__file__).resolve().parents[1] / "packs",
        store=DEFAULT_JSON_STORE,
        config_dir=CONFIG_DIR,
        default_pack=DEFAULT_PACK,
    )


def pack_roots(project_dir: Path) -> list[Path]:
    return _pack_registry(project_dir).roots()


def pack_file_candidates(project_dir: Path, pack: str, file_name: str) -> list[Path]:
    return _pack_registry(project_dir).file_candidates(pack, file_name)


def normalize_unique_strings(values: list[str]) -> list[str]:
    return PackRegistry.normalize_unique_strings(values)


def discover_pack_contracts(project_dir: Path) -> list[dict[str, Any]]:
    return _pack_registry(project_dir).discover_contracts()


def load_pack_contract_from_path(path: Path) -> dict[str, Any]:
    registry = PackRegistry(
        path.parent,
        bundled_root=repository_root(),
        bundled_packs_root=Path(__file__).resolve().parents[1] / "packs",
        store=DEFAULT_JSON_STORE,
        config_dir=CONFIG_DIR,
        default_pack=DEFAULT_PACK,
    )
    return registry.load_contract_from_path(path)


def load_pack_contract(project_dir: Path, pack: str) -> dict[str, Any]:
    return _pack_registry(project_dir).load_contract(pack)


def detection_string_list(detection: dict[str, Any], key: str) -> list[str]:
    return PackRegistry.detection_string_list(detection, key)


def project_path_exists(project_dir: Path, relative_name: str) -> bool:
    return _pack_registry(project_dir).project_path_exists(relative_name)


def project_glob_matches(project_dir: Path, pattern: str) -> bool:
    return _pack_registry(project_dir).project_glob_matches(pattern)


def pack_detection_score(project_dir: Path, contract: dict[str, Any]) -> int:
    return _pack_registry(project_dir).detection_score(contract)


def detect_project_pack(project_dir: Path) -> dict[str, Any]:
    return _pack_registry(project_dir).detect()


def pack_skill_entries(contract: dict[str, Any]) -> list[str]:
    return _pack_registry(repository_root()).skill_entries(contract)


def isolated_process_module() -> Any:
    from loopforge.checks import isolated_process

    return isolated_process


def is_windows_app_execution_alias(path: Path) -> bool:
    normalized = str(path).replace("/", "\\").upper()
    return "\\APPDATA\\LOCAL\\MICROSOFT\\WINDOWSAPPS\\" in normalized


def usable_python_executable() -> str:
    candidates: list[str | None] = [
        os.environ.get("LOOPFORGE_PYTHON"),
        sys.executable,
        getattr(sys, "_base_executable", None),
        shutil.which("python"),
        shutil.which("python3"),
        shutil.which("py"),
        str(
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "python"
            / "python.exe"
        ),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            resolved = shutil.which(candidate)
            if resolved is None:
                continue
            path = Path(resolved)
        if path.is_file() and not is_windows_app_execution_alias(path):
            return str(path)
    raise RuntimeError(
        "no usable Python executable found for isolated adapter execution; "
        "set LOOPFORGE_PYTHON to a real python.exe outside WindowsApps."
    )


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


def parse_frontmatter(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith("# "):
            current = line[2:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def section_text(sections: dict[str, list[str]], name: str) -> str:
    return "\n".join(sections.get(name, [])).strip()


def bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if item and not item.lower().startswith("none recorded"):
            items.append(item)
    return items


def loop_contract_state(loop_path: Path) -> dict[str, Any]:
    if not loop_path.exists():
        return {
            "status": "missing",
            "path": str(loop_path),
            "missing_fields": list(REQUIRED_LOOP_SECTIONS),
            "success_checks": [],
            "allowed_tools": [],
            "subjective": False,
            "rubric": "",
            "errors": [f"loop contract not found: {loop_path}"],
        }

    markdown = loop_path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(markdown)
    sections = markdown_sections(markdown)
    missing_fields = [
        name for name in REQUIRED_LOOP_SECTIONS if not section_text(sections, name)
    ]
    success_checks = bullet_items(section_text(sections, "Success Checks"))
    allowed_tools = bullet_items(section_text(sections, "Allowed Tools"))
    rubric = section_text(sections, "Subjective Rubric")
    if rubric.lower().startswith("none recorded"):
        rubric = ""
    limits = parse_loop_limits(section_text(sections, "Limits"))
    subjective = frontmatter.get("subjective", "false").lower() == "true"
    status = "valid"
    errors: list[str] = []
    if missing_fields:
        status = "invalid"
        errors.append(f"missing required contract fields: {', '.join(missing_fields)}")
    return {
        "status": status,
        "path": str(loop_path),
        "missing_fields": missing_fields,
        "success_checks": success_checks,
        "allowed_tools": allowed_tools,
        "subjective": subjective,
        "rubric": rubric,
        "limits": limits,
        "errors": errors,
    }


def text_matches_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def autonomous_stop_reasons(run: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not contract.get("success_checks"):
        reasons.append("autonomous profile requires objective success checks.")
    if contract.get("subjective") and not contract.get("rubric"):
        reasons.append("autonomous profile requires a rubric for subjective work.")

    verification = verification_state(run)
    if isinstance(verification, dict) and verification.get("stagnated"):
        reasons.append("autonomous profile stops after repeated equivalent failure.")
    raw_blockers = run.get("blockers", [])
    blockers = raw_blockers if isinstance(raw_blockers, list) else []
    for blocker in blockers:
        if "stagnation:" in str(blocker).lower():
            append_unique(reasons, "autonomous profile stops after repeated equivalent failure.")

    scanned_text = "\n".join(
        [
            str(run.get("task") or ""),
            *[str(item) for item in contract.get("allowed_tools", []) if item],
        ]
    )
    for category, markers in AUTONOMOUS_STOP_MARKERS.items():
        if text_matches_any_marker(scanned_text, markers):
            reasons.append(
                f"autonomous profile stops before {category}; human review is required."
            )
    return reasons


def adapter_result_stop_reasons(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if result.get("publication_requested"):
        reasons.append("adapter requested publication; human review is required.")
    if result.get("network_requested"):
        reasons.append("adapter requested network or external side effects; human review is required.")
    summary = str(result.get("summary") or "")
    for category, markers in AUTONOMOUS_STOP_MARKERS.items():
        if text_matches_any_marker(summary, markers):
            reasons.append(
                f"adapter result mentions {category}; human review is required."
            )
    return reasons


def profile_transition_blockers(
    *,
    profile: object,
    action: str,
    confirmed: bool = False,
    run: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    normalized = normalize_profile(profile)
    if normalized == "assist" and action in {
        "adapter_attempt",
        "verification",
        "memory_promotion",
    }:
        return [
            f"assist profile blocks {action.replace('_', ' ')}; switch profile or review manually."
        ]
    if normalized == "strict" and action in {
        "adapter_attempt",
        "verification",
        "memory_promotion",
    } and not confirmed:
        return [
            f"strict profile requires --confirm before {action.replace('_', ' ')}."
        ]
    if normalized == "autonomous" and run is not None and contract is not None:
        if action == "adapter_attempt":
            return autonomous_stop_reasons(run, contract)
        if action == "verification":
            verification = verification_state(run)
            if isinstance(verification, dict) and verification.get("stagnated"):
                return ["autonomous profile stops after repeated equivalent failure."]
    return []


def parse_loop_limits(text: str) -> dict[str, int | None]:
    limits: dict[str, int | None] = {
        "max_attempts": None,
        "timeout_seconds": None,
    }
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("- max attempts:"):
            limits["max_attempts"] = positive_int_after_colon(stripped)
        elif lowered.startswith("- timeout seconds:"):
            limits["timeout_seconds"] = positive_int_after_colon(stripped)
    return limits


def positive_int_after_colon(text: str) -> int | None:
    _, _, value = text.partition(":")
    value = value.strip()
    if not value.isdigit():
        return None
    parsed = int(value)
    if parsed < 1:
        return None
    return parsed


def verification_state(run: dict[str, Any]) -> dict[str, Any] | None:
    verification = run.get("verification")
    return verification if isinstance(verification, dict) else None


def parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def duration_seconds(started_at: object, finished_at: object) -> int | None:
    started = parse_utc_timestamp(started_at)
    finished = parse_utc_timestamp(finished_at)
    if started is None or finished is None:
        return None
    seconds = int((finished - started).total_seconds())
    if seconds < 0:
        return None
    return seconds


def new_config(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> dict[str, Any]:
    now = utc_now()
    normalized_profile = normalize_profile(profile)
    project_id = project_registry.new_project_id()
    storage_root = project_registry.storage_root(loopforge_home(home=home), project_id)
    return {
        "project_id": project_id,
        "project_name": project_name(project_dir),
        "profile": normalized_profile,
        "run_root": str(storage_root / "runs"),
        "current_run_id": None,
        "default_adapter": DEFAULT_ADAPTER,
        "default_adapter_args": [],
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
    if config.get("default_adapter") not in SUPPORTED_ADAPTERS:
        config["default_adapter"] = DEFAULT_ADAPTER
    if not isinstance(config.get("default_adapter_args"), list):
        config["default_adapter_args"] = []
    else:
        config["default_adapter_args"] = [
            str(value) for value in config["default_adapter_args"]
        ]
    if "project_name" not in config:
        config["project_name"] = project_name(project_dir)
    if not isinstance(config.get("project_id"), str) or not config["project_id"].strip():
        config["project_id"] = project_registry.new_project_id()
    normalized_profile = normalize_profile(config.get("profile", profile))
    if config.get("profile") != normalized_profile:
        config["profile"] = normalized_profile
    if "run_root" not in config:
        config["run_root"] = str(
            project_registry.storage_root(
                loopforge_home(home=home), str(config["project_id"])
            )
            / "runs"
        )
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
    ensure_project_memory(project_dir)

    migrated_run_root: Path | None = None
    if config_path.exists():
        existing = read_json(config_path)
        config, repaired = normalize_config(
            project_dir,
            existing,
            profile=profile,
            home=home,
        )
        home_root = loopforge_home(home=home)
        target_root = project_registry.migration_target(home_root, str(config["project_id"]))
        previous_raw = existing.get("run_root")
        previous_run_root = (
            Path(previous_raw).expanduser()
            if isinstance(previous_raw, str) and previous_raw.strip()
            else None
        )
        if previous_run_root is not None and previous_run_root != target_root:
            if previous_run_root.exists() and not target_root.exists():
                shutil.copytree(previous_run_root, target_root)
                migrated_run_root = previous_run_root
            if not previous_run_root.exists() or target_root.exists():
                config["run_root"] = str(target_root)
                repaired = True
        if repaired:
            write_json_atomic(config_path, config)
        registration = project_registry.register_project(project_dir, config, home_root)
        if migrated_run_root is not None:
            try:
                _sync_project_indexes(project_dir, config, rebuild=True)
            except OSError:
                pass
        return InitResult(
            project_dir=project_dir,
            config_path=config_path,
            config=config,
            created=False,
            repaired=repaired,
            registration=registration,
            migrated_run_root=migrated_run_root,
        )

    config = new_config(project_dir, profile=profile, home=home)
    write_json_atomic(config_path, config)
    registration = project_registry.register_project(project_dir, config, loopforge_home(home=home))
    return InitResult(
        project_dir=project_dir,
        config_path=config_path,
        config=config,
        created=True,
        repaired=False,
        registration=registration,
    )


def open_project(
    project_or_path: str | None,
    *,
    current_project_dir: Path,
    home: Path | None = None,
    identity_resolution: str | None = None,
) -> OpenProjectResult:
    """Open or register a project, requiring an explicit duplicate-id decision."""

    home_root = loopforge_home(home=home)
    target: Path | None = current_project_dir.resolve()
    requested = str(project_or_path or "").strip()
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.exists():
            target = candidate.resolve()
        else:
            matches = [
                record
                for record in project_registry.registered_projects(home_root)
                if requested in {str(record.get("project_id") or ""), str(record.get("name") or "")}
            ]
            if len(matches) != 1:
                return OpenProjectResult(
                    None,
                    None,
                    False,
                    "LoopForge could not resolve the project.",
                    [f"no unique registered project matches: {requested}"],
                )
            target = Path(str(matches[0]["path"])).expanduser().resolve()
    if target is None or not target.is_dir():
        return OpenProjectResult(
            target,
            None,
            False,
            "LoopForge could not open the project.",
            [f"project directory does not exist: {target}"],
        )
    result = initialize_project(target, home=home)
    registration = result.registration
    if registration is not None and not registration.ok:
        if identity_resolution == "moved":
            registration = project_registry.register_project(
                target, result.config, home_root, allow_move=True
            )
            result = InitResult(
                result.project_dir,
                result.config_path,
                result.config,
                result.created,
                result.repaired,
                registration,
                result.migrated_run_root,
            )
        elif identity_resolution == "clone":
            config = project_registry.regenerate_project_identity(target, result.config, home_root)
            write_json_atomic(result.config_path, config)
            registration = project_registry.register_project(target, config, home_root)
            result = InitResult(
                result.project_dir,
                result.config_path,
                config,
                result.created,
                True,
                registration,
                result.migrated_run_root,
            )
        else:
            conflict = registration.conflict_path
            return OpenProjectResult(
                target,
                result,
                False,
                "Project identity needs confirmation.",
                [
                    f"project id {registration.project_id} is already registered at {conflict}",
                    "Use `loopforge open <path> --moved` after moving a repository, or `--clone` for a copy.",
                ],
            )
    return OpenProjectResult(target, result, True, "Project opened.", [])


def update_project_config(project_dir: Path, updates: dict[str, Any]) -> ConfigUpdateResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge config update failed.",
            blockers=[status.next_step],
        )

    config = dict(status.config)
    for key, value in updates.items():
        config[key] = value
    config["updated_at"] = utc_now()
    normalized, _ = normalize_config(status.project_dir, config)
    persist_project_config(status.project_dir, status.config_path, normalized)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=normalized,
        ok=True,
        message=f"LoopForge config updated: {status.config_path}",
        blockers=[],
    )


def set_default_adapter(
    project_dir: Path,
    adapter: str,
    adapter_args: list[str] | None = None,
) -> ConfigUpdateResult:
    if adapter not in SUPPORTED_ADAPTERS:
        return ConfigUpdateResult(
            project_dir=project_dir.resolve(),
            config_path=project_config_path(project_dir.resolve()),
            config=None,
            ok=False,
            message="LoopForge adapter update failed.",
            blockers=[f"unsupported adapter: {adapter}"],
        )
    updates: dict[str, Any] = {"default_adapter": adapter}
    if adapter_args is not None:
        updates["default_adapter_args"] = [str(value) for value in adapter_args]
    return update_project_config(project_dir, updates)


def archive_current_run(project_dir: Path) -> ConfigUpdateResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    updated_run = dict(status.run)
    updated_run["archived"] = True
    updated_run["archived_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated_run)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=status.config,
        ok=True,
        message=f"LoopForge archived run: {updated_run.get('run_id')}",
        blockers=[],
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


def git_toplevel(project_dir: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except OSError:
        return None


def run_workspace_path(run: dict[str, Any], fallback_project_dir: Path) -> Path:
    workspace = run.get("workspace", {})
    if isinstance(workspace, dict):
        raw_path = workspace.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path).expanduser().resolve()
    return fallback_project_dir.resolve()


def run_workspace_state(run: dict[str, Any], fallback_project_dir: Path) -> dict[str, Any]:
    workspace = run.get("workspace", {})
    if not isinstance(workspace, dict):
        workspace = {}
    mode = workspace.get("mode")
    if mode not in {WORKSPACE_MODE_GIT_WORKTREE, WORKSPACE_MODE_SHARED_CHECKOUT}:
        mode = WORKSPACE_MODE_SHARED_CHECKOUT
    base_commit = workspace.get("base_commit")
    if not isinstance(base_commit, str):
        base_commit = run.get("base_commit")
    return {
        "mode": mode,
        "path": str(run_workspace_path(run, fallback_project_dir)),
        "base_commit": base_commit,
        "created_at": workspace.get("created_at"),
    }


def prepare_run_workspace(
    *,
    project_dir: Path,
    run_id: str,
    base_commit: str | None,
    now: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    if base_commit is None or git_toplevel(project_dir) is None:
        return {
            "mode": WORKSPACE_MODE_SHARED_CHECKOUT,
            "path": str(project_dir),
            "base_commit": base_commit,
            "created_at": now,
        }

    workspace_path = default_workspace_root(project_dir, project_id=project_id) / run_id
    if workspace_path.exists():
        raise ValueError(f"workspace already exists: {workspace_path}")
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={project_dir.resolve().as_posix()}",
            "worktree",
            "add",
            "--detach",
            str(workspace_path),
            base_commit,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise ValueError(f"could not create run worktree: {detail}")
    return {
        "mode": WORKSPACE_MODE_GIT_WORKTREE,
        "path": str(workspace_path.resolve()),
        "base_commit": base_commit,
        "created_at": now,
    }


def task_looks_subjective(task: str) -> bool:
    lowered = task.lower()
    return any(marker in lowered for marker in SUBJECTIVE_TASK_MARKERS)


def normalize_nonempty_strings(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return [value.strip() for value in values if value.strip()]


def normalize_profile(profile: object) -> str:
    value = str(profile or "").strip().lower()
    if value in SUPPORTED_PROFILES:
        return value
    return DEFAULT_PROFILE


def profile_policy(profile: object) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    policy = dict(PROFILE_POLICIES[normalized])
    policy["name"] = normalized
    return policy


def profile_permission_lines(profile: object) -> list[str]:
    policy = profile_policy(profile)
    return [
        f"profile allows: {policy['summary']}",
        f"profile mutation: {policy['mutation']}",
        f"profile attempts: {policy['attempts']}",
        f"profile memory: {policy['memory']}",
    ]


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def loop_contract_status(
    *,
    success_checks: list[str],
    profile: str,
    subjective: bool,
    subjective_rubric: str,
) -> str:
    if not success_checks:
        return LOOP_CONTRACT_DRAFT
    if profile == "autonomous" and subjective and not subjective_rubric.strip():
        return LOOP_CONTRACT_DRAFT
    return LOOP_CONTRACT_READY


def render_loop_contract(
    *,
    task: str,
    task_id: str,
    project_dir: Path,
    base_commit: str | None,
    profile: str,
    pack: str,
    skills: list[str],
    allowed_tools: list[str],
    success_checks: list[str],
    max_attempts: int,
    timeout_seconds: int,
    subjective: bool,
    subjective_rubric: str,
) -> str:
    status = loop_contract_status(
        success_checks=success_checks,
        profile=profile,
        subjective=subjective,
        subjective_rubric=subjective_rubric,
    )

    def list_block(items: list[str], empty: str = "None recorded.") -> str:
        if not items:
            return empty
        return "\n".join(f"- {item}" for item in items)

    review_conditions = [
        "Success checks are missing or no longer match the task.",
        (
            "The next action would publish, delete, expose secrets, spend money, "
            "or use hidden network access."
        ),
        "Two attempts produce the same failure without new evidence.",
    ]
    if subjective:
        review_conditions.append(
            "Subjective quality is involved and the rubric is missing or disputed."
        )

    return f"""---
loop_version: 1
status: {status}
autonomy: {profile}
subjective: {str(subjective).lower()}
---

# Objective

{task}

# Scope

In scope:

- Complete the task described in `task.md`.
- Keep changes bounded to the target project and the external LoopForge run artifacts.

Out of scope:

- Publishing, remote side effects, destructive cleanup, or memory promotion
  without a later explicit phase.
- Treating receipts, validation, or metrics as publication authority.

# Inputs

- Task ID: {task_id}
- Task: {task}
- Repository: {project_dir}
- Base commit: {base_commit or "none"}

# Selected Project Pack

{pack}

# Selected Skills

{list_block(skills)}

# Allowed Tools

{list_block(allowed_tools)}

# Success Checks

{list_block(success_checks)}

# Subjective Rubric

{subjective_rubric.strip() or "None recorded."}

# Limits

- Max attempts: {max_attempts}
- Timeout seconds: {timeout_seconds}
- Max output: adapter default

# Stagnation Rule

Stop after two attempts produce the same failure, the same blocker, or no new evidence.

# Rollback Strategy

Use Git or explicit patch review to inspect and undo LoopForge changes. Preserve
unrelated working-tree changes.

# Human Review Conditions

{list_block(review_conditions)}

# Current Attempt

No autonomous attempt has run yet.
"""


def memory_artifact_dir(run_dir: Path) -> Path:
    return run_dir / "artifacts" / "memory"


def memory_proposal_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.json"


def memory_proposal_markdown_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.md"


def memory_status_from_proposals(run_dir: Path) -> dict[str, int | str | None]:
    path = memory_proposal_path(run_dir)
    if not path.exists():
        return {
            "proposal_path": None,
            "pending": 0,
            "promoted": 0,
            "rejected": 0,
        }
    try:
        data = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "proposal_path": str(path),
            "pending": 0,
            "promoted": 0,
            "rejected": 0,
        }
    proposals = data.get("proposals", [])
    if not isinstance(proposals, list):
        proposals = []
    normalized = [item for item in proposals if isinstance(item, dict)]
    return {
        "proposal_path": str(path),
        "pending": sum(1 for item in normalized if item.get("status") == "pending"),
        "promoted": sum(1 for item in normalized if item.get("status") == "promoted"),
        "rejected": sum(1 for item in normalized if item.get("status") == "rejected"),
    }


def memory_state(project_dir: Path, run_dir: Path | None) -> dict[str, Any]:
    memory_path = durable_memory_path(project_dir)
    memory_missing = not memory_path.exists()
    items = durable_memory_items(project_dir)
    state: dict[str, Any] = {
        "durable_path": str(memory_path),
        "durable_status": "missing" if memory_missing else "present",
        "durable_items": memory_item_count(items),
        "sections": {section: len(values) for section, values in items.items()},
        "run_snapshot": str(run_dir / "memory.md") if run_dir is not None else None,
        "proposal_path": None,
        "pending": 0,
        "promoted": 0,
        "rejected": 0,
    }
    if run_dir is not None:
        state.update(memory_status_from_proposals(run_dir))
    return state


def parse_memory_candidate_text(text: str, *, source: str) -> tuple[str, str] | None:
    candidate = " ".join(text.strip().split())
    if not candidate:
        return None
    explicit = source == "cli-note"
    lowered = candidate.lower()
    if lowered.startswith("memory:"):
        explicit = True
        candidate = candidate.split(":", 1)[1].strip()
    match = re.match(r"^([A-Za-z][A-Za-z -]{1,30})\s*:\s*(.+)$", candidate)
    category = "Stable Project Facts"
    if match:
        alias = match.group(1).strip().lower().replace(" ", "-")
        alias = alias.replace("-", "_")
        normalized_alias = alias.replace("_", " ")
        category = (
            MEMORY_CATEGORY_ALIASES.get(alias)
            or MEMORY_CATEGORY_ALIASES.get(normalized_alias)
            or category
        )
        if alias in MEMORY_CATEGORY_ALIASES or normalized_alias in MEMORY_CATEGORY_ALIASES:
            explicit = True
            candidate = match.group(2).strip()
    if not explicit:
        return None
    if not candidate:
        return None
    return category, candidate


def memory_rejection_reason(text: str, *, trusted: bool) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in SECRET_MARKERS):
        return "candidate appears to contain a secret or credential marker"
    if any(marker in lowered for marker in UNTRUSTED_TEXT_MARKERS):
        return "candidate appears to contain raw untrusted issue/comment/body text"
    if not trusted:
        return "candidate came from an untrusted exchange message"
    return None


def memory_candidate(
    text: str,
    *,
    source: str,
    source_path: Path | None,
    trusted: bool = True,
) -> dict[str, Any] | None:
    parsed = parse_memory_candidate_text(text, source=source)
    if parsed is None:
        return None
    category, value = parsed
    candidate_id = hashlib.sha256(
        json.dumps(
            {
                "category": category,
                "source": source,
                "text": value,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    reason = memory_rejection_reason(value, trusted=trusted)
    return {
        "id": candidate_id,
        "category": category,
        "text": value,
        "source": source,
        "source_path": str(source_path) if source_path is not None else None,
        "trusted": trusted,
        "status": "rejected" if reason else "pending",
        "rejection_reason": reason,
    }


def scratch_memory_candidates(run_dir: Path) -> list[dict[str, Any]]:
    scratch_path = run_dir / "scratch.md"
    if not scratch_path.exists():
        return []
    markdown = scratch_path.read_text(encoding="utf-8")
    sections = markdown_sections(markdown)
    candidates: list[dict[str, Any]] = []
    for section, lines in sections.items():
        if section == "Discard Candidates":
            continue
        for item in bullet_items("\n".join(lines)):
            candidate = memory_candidate(
                item,
                source=f"scratch:{section}",
                source_path=scratch_path,
                trusted=True,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def exchange_memory_candidates(run_dir: Path) -> list[dict[str, Any]]:
    exchange_path = run_dir / "exchange.json"
    if not exchange_path.exists():
        return []
    try:
        data = read_json(exchange_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        return []
    candidates: list[dict[str, Any]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            continue
        value = message.get("memory_candidate", message.get("promote_to_memory"))
        if not isinstance(value, str):
            continue
        candidate = memory_candidate(
            value,
            source="exchange:messages",
            source_path=exchange_path,
            trusted=message.get("trusted") is True,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def pack_memory_rule_paths(project_dir: Path, pack: str) -> list[Path]:
    return pack_file_candidates(project_dir, pack, "memory-rules.json")


def load_pack_memory_rules(project_dir: Path, pack: str) -> dict[str, Any]:
    for path in pack_memory_rule_paths(project_dir, pack):
        if not path.exists():
            continue
        data = read_json(path)
        rules = data.get("auto_promote", [])
        if not isinstance(rules, list):
            raise ValueError(f"{path} auto_promote must be a list")
        return {"source": str(path), "auto_promote": rules}
    try:
        contract = load_pack_contract(project_dir, pack)
    except ValueError:
        return {"source": None, "auto_promote": []}
    memory = contract.get("memory", {})
    if not isinstance(memory, dict):
        return {"source": None, "auto_promote": []}
    rules = memory.get("auto_promote", [])
    if not isinstance(rules, list):
        raise ValueError(f"{contract.get('source')} memory.auto_promote must be a list")
    return {"source": contract.get("source"), "auto_promote": rules}


def pack_rule_allows_promotion(rules: dict[str, Any], proposal: dict[str, Any]) -> bool:
    raw_rules = rules.get("auto_promote", [])
    if not isinstance(raw_rules, list):
        return False
    for rule in raw_rules:
        if isinstance(rule, str):
            pattern = rule
            category = None
        elif isinstance(rule, dict):
            pattern = rule.get("pattern")
            category = rule.get("category")
        else:
            continue
        if category is not None and str(category) != proposal["category"]:
            continue
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            if re.search(pattern, proposal["text"]):
                return True
        except re.error:
            if pattern in proposal["text"]:
                return True
    return False


def remove_placeholder_item(lines: list[str], start: int, end: int) -> list[str]:
    cleaned = list(lines)
    for index in range(end - 1, start, -1):
        if cleaned[index].strip().lower() == "- none recorded.":
            del cleaned[index]
    return cleaned


def append_markdown_bullet(path: Path, section: str, item: str) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    header = f"# {section}"
    try:
        header_index = next(index for index, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, "", f"- {item}", ""])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return True

    next_header = len(lines)
    for index in range(header_index + 1, len(lines)):
        if lines[index].startswith("# "):
            next_header = index
            break
    existing = bullet_items("\n".join(lines[header_index + 1 : next_header]))
    if item in existing:
        return False
    lines = remove_placeholder_item(lines, header_index + 1, next_header)
    next_header = len(lines)
    for index in range(header_index + 1, len(lines)):
        if lines[index].startswith("# "):
            next_header = index
            break
    insert_at = next_header
    while insert_at > header_index + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"- {item}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def promote_memory_candidate(
    project_dir: Path,
    proposal: dict[str, Any],
    *,
    reason: str,
    run_id: str | None,
) -> bool:
    path = ensure_project_memory(project_dir)
    item = str(proposal["text"])
    category = str(proposal["category"])
    changed = append_markdown_bullet(path, category, item)
    if changed:
        source = proposal.get("source_path") or proposal.get("source") or "unknown"
        log_item = (
            f"{utc_now()} | {reason} | run={run_id or 'none'} | "
            f"{category}: {item} | source={source}"
        )
        append_markdown_bullet(path, "Promotion Log", log_item)
    return changed


def render_memory_proposals_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Memory Proposals",
        "",
        f"- Created: {data['created_at']}",
        f"- Approved: {'yes' if data['approval'] else 'no'}",
        f"- Pack rule source: {data.get('pack_rule_source') or 'none'}",
        "",
    ]
    proposals = data.get("proposals", [])
    if not proposals:
        lines.append("No memory proposals found.")
        lines.append("")
        return "\n".join(lines)
    for proposal in proposals:
        lines.extend(
            [
                f"## {proposal['id']}",
                "",
                f"- Status: {proposal['status']}",
                f"- Category: {proposal['category']}",
                f"- Source: {proposal.get('source_path') or proposal['source']}",
                f"- Text: {proposal['text']}",
            ]
        )
        if proposal.get("rejection_reason"):
            lines.append(f"- Rejection: {proposal['rejection_reason']}")
        if proposal.get("promotion_reason"):
            lines.append(f"- Promotion: {proposal['promotion_reason']}")
        lines.append("")
    return "\n".join(lines)


def unique_memory_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["id"])
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        unique.append(candidate)
    return unique


def learn_run(
    project_dir: Path,
    *,
    approve: bool = False,
    notes: list[str] | None = None,
    confirmed: bool = False,
) -> LearnResult:
    status = current_status(project_dir)
    if not status.initialized:
        return LearnResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="Initialize LoopForge before learning.",
            proposals=[],
            promoted=[],
            rejected=[],
            proposal_path=None,
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return LearnResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            ok=False,
            message="Create a run before proposing memory updates.",
            proposals=[],
            promoted=[],
            rejected=[],
            proposal_path=None,
            blockers=[status.next_step],
        )

    raw_candidates: list[dict[str, Any]] = []
    for note in normalize_nonempty_strings(notes):
        candidate = memory_candidate(
            note,
            source="cli-note",
            source_path=None,
            trusted=True,
        )
        if candidate is not None:
            raw_candidates.append(candidate)
    raw_candidates.extend(scratch_memory_candidates(status.run_dir))
    raw_candidates.extend(exchange_memory_candidates(status.run_dir))
    proposals = unique_memory_candidates(raw_candidates)

    pack = str(status.run.get("pack") or DEFAULT_PACK)
    try:
        rules = load_pack_memory_rules(status.project_dir, pack)
    except ValueError as error:
        rules = {"source": None, "auto_promote": []}
        rule_error = str(error)
    else:
        rule_error = ""

    promotion_requested = approve or any(
        proposal.get("status") != "rejected" and pack_rule_allows_promotion(rules, proposal)
        for proposal in proposals
    )
    profile_blockers = (
        profile_transition_blockers(
            profile=status.run.get("profile", DEFAULT_PROFILE),
            action="memory_promotion",
            confirmed=confirmed,
            run=status.run,
            contract=status.loop_contract,
        )
        if promotion_requested
        else []
    )

    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if profile_blockers:
        for proposal in proposals:
            if proposal["status"] == "rejected":
                rejected.append(proposal)
    else:
        for proposal in proposals:
            if proposal["status"] == "rejected":
                rejected.append(proposal)
                continue
            promotion_reason = ""
            if approve:
                promotion_reason = "human_approved"
            elif pack_rule_allows_promotion(rules, proposal):
                promotion_reason = f"pack_rule:{rules.get('source') or 'unknown'}"
            if not promotion_reason:
                continue
            changed = promote_memory_candidate(
                status.project_dir,
                proposal,
                reason=promotion_reason,
                run_id=str(status.run.get("run_id") or ""),
            )
            proposal["status"] = "promoted" if changed else "already_present"
            proposal["promotion_reason"] = promotion_reason
            if changed:
                promoted.append(proposal)

    created = utc_now()
    proposal_data = {
        "version": 1,
        "created_at": created,
        "run_id": status.run.get("run_id"),
        "approval": approve and not profile_blockers,
        "pack": pack,
        "pack_rule_source": rules.get("source"),
        "profile_blockers": profile_blockers,
        "proposals": proposals,
    }
    if rule_error:
        proposal_data["rule_error"] = rule_error
    proposal_path = memory_proposal_path(status.run_dir)
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(proposal_path, proposal_data)
    memory_proposal_markdown_path(status.run_dir).write_text(
        render_memory_proposals_markdown(proposal_data),
        encoding="utf-8",
    )

    updated_run = dict(status.run)
    updated_run["memory"] = {
        "durable_project_memory": str(durable_memory_path(status.project_dir)),
        "run_snapshot": str(status.run_dir / "memory.md"),
        "last_proposal": relative_to_run(status.run_dir, proposal_path),
        "pending_proposals": sum(
            1 for proposal in proposals if proposal.get("status") == "pending"
        ),
        "promoted": len(promoted),
        "rejected": len(rejected),
        "updated_at": created,
    }
    updated_run["updated_at"] = created
    if status.run_json_path is not None:
        persist_run_json(status.project_dir, status.run_json_path, updated_run)

    blockers = [rule_error] if rule_error else []
    blockers.extend(profile_blockers)
    message = "LoopForge memory proposals written."
    if promoted:
        message = "LoopForge memory updated."
    if profile_blockers:
        message = "LoopForge memory promotion refused by the autonomy profile."
    return LearnResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated_run,
        ok=not blockers,
        message=message,
        proposals=proposals,
        promoted=promoted,
        rejected=rejected,
        proposal_path=proposal_path,
        blockers=blockers,
    )


def describe_next_step(run: dict[str, Any]) -> str:
    pack_contract = run.get("pack_contract", {})
    workflow = pack_contract.get("workflow", []) if isinstance(pack_contract, dict) else []
    if isinstance(workflow, list) and workflow:
        normalized = normalize_run_workflow_state(run)
        statuses = normalized.get("stage_statuses", {})
        validation = normalized.get("task_validation", {})
        if isinstance(validation, dict) and validation.get("status") == "needs_input":
            return "Complete the task definition and objective success checks."
        if isinstance(statuses, dict):
            if statuses.get("task") != "approved":
                return "Review and approve the task with `loopforge run`."
            if statuses.get("research") != "complete":
                return "Run the read-only researcher with `loopforge run`."
            if statuses.get("plan") not in {"awaiting_approval", "approved", "complete"}:
                return "Run the read-only planner with `loopforge run`."
            if statuses.get("plan") == "awaiting_approval":
                return "Review and approve the plan with `loopforge run`."
            if statuses.get("implementation") != "complete":
                return "Run the developer with `loopforge continue --adapter <adapter>`."
            if statuses.get("verification") != "complete":
                return "Generate the patch and run checks with `loopforge verify`."
            if statuses.get("review") not in {"complete", "approved"}:
                return "Run the read-only patch reviewer with `loopforge run`."
            if statuses.get("review") == "complete":
                return "Approve the review and draft preparation with `loopforge run`."
            if statuses.get("publication") != "draft_prepared":
                return "Prepare the local draft PR artifact with `loopforge run`."
            return "Inspect the completed workflow with `loopforge status --details`."
    status = str(run.get("status", "unknown"))
    blockers = run.get("blockers", [])
    if isinstance(blockers, list) and blockers:
        return "Resolve the listed blockers before continuing the loop."
    if status == LOOP_CONTRACT_DRAFT:
        return "Complete the loop contract, especially success checks, before continuing."
    if status == LOOP_CONTRACT_READY:
        return "Run `loopforge continue --adapter <adapter>` to execute a bounded attempt."
    if status == ADAPTER_BLOCKED:
        return "Inspect the latest attempt artifacts, resolve blockers, then continue again."
    if status == READY_FOR_VERIFICATION:
        return "Run `loopforge verify` to generate the patch and run pack checks."
    if status == VERIFICATION_FAILED:
        return "Inspect verification.md, fix the diagnostic, then run `loopforge verify` again."
    if status == VERIFIED:
        return "Review the verified patch and decide whether to continue, commit, or hand off."
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
            loop_contract=None,
            verification=None,
            memory=None,
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
            loop_contract=None,
            verification=None,
            memory=memory_state(project_dir, None),
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
            loop_contract=loop_contract_state(run_dir / "loop.md") if run_dir.exists() else None,
            verification=None,
            memory=memory_state(project_dir, run_dir) if run_dir.exists() else None,
            next_step="Restore the missing run artifacts or create a new run.",
            blockers=[f"current run metadata not found: {run_json_path}"],
        )

    run = normalize_run_workflow_state(read_json(run_json_path))
    raw_blockers = run.get("blockers", [])
    blockers = [str(blocker) for blocker in raw_blockers] if isinstance(raw_blockers, list) else []
    contract = loop_contract_state(run_dir / "loop.md")
    if contract["status"] != "valid":
        for error in contract["errors"]:
            append_unique(blockers, str(error))
    return StatusResult(
        project_dir=project_dir,
        config_path=config_path,
        initialized=True,
        config=config,
        run_dir=run_dir,
        run_json_path=run_json_path,
        run=run,
        native_artifacts=native_artifact_state(run_dir),
        loop_contract=contract,
        verification=verification_state(run),
        memory=memory_state(project_dir, run_dir),
        next_step=describe_next_step(run),
        blockers=blockers,
    )


def guided_action(
    action_id: str,
    label: str,
    command: str,
    *,
    risk: str = "low",
    requires_confirmation: bool = False,
    why: str,
) -> GuidedAction:
    return GuidedAction(
        id=action_id,
        label=label,
        command=command,
        risk=risk,
        requires_confirmation=requires_confirmation,
        why=why,
    )


def workflow_stage_guidance(
    run: dict[str, Any],
    *,
    adapter: str,
    profile: str,
) -> tuple[str, str, str, GuidedAction] | None:
    contract = run.get("pack_contract", {})
    workflow = contract.get("workflow", []) if isinstance(contract, dict) else []
    if not isinstance(workflow, list) or not workflow:
        return None
    normalized = normalize_run_workflow_state(run)
    statuses = normalized.get("stage_statuses", {})
    gates = normalized.get("human_gates", {})
    if not isinstance(statuses, dict) or not isinstance(gates, dict):
        return None

    validation = normalized.get("task_validation", {})
    if isinstance(validation, dict) and validation.get("status") == "needs_input":
        missing = ", ".join(str(value) for value in validation.get("missing", []))
        action = guided_action(
            "complete-task",
            "Complete the task and its objective proof",
            'loopforge run --task "Describe the outcome" --success-check "Describe the proof"',
            why="Research starts only after the task contract is complete and approved.",
        )
        return "task_needs_input", f"The task is incomplete: {missing}.", "complete_task", action

    approval = normalized.get("approval", {})
    if statuses.get("task") != "approved" or not (
        isinstance(approval, dict) and approval.get("approved") is True
    ):
        action = guided_action(
            "approve-task",
            "Review and approve the task",
            "loopforge run",
            requires_confirmation=True,
            why="Task approval is required before repository research.",
        )
        return "task_awaiting_approval", "The task is waiting for approval.", "approve_task", action

    if statuses.get("research") != "complete":
        action = guided_action(
            "run-research",
            f"Run read-only research with {adapter}",
            "loopforge run",
            risk="read-only-agent",
            requires_confirmation=True,
            why="Research maps files, tests, and reusable patterns before planning.",
        )
        return "research_pending", "The researcher is the next actor.", "research", action

    if statuses.get("plan") not in {"awaiting_approval", "approved", "complete"}:
        action = guided_action(
            "run-plan",
            f"Generate a read-only plan with {adapter}",
            "loopforge run",
            risk="read-only-agent",
            requires_confirmation=True,
            why="Implementation must be based on repository evidence.",
        )
        return "plan_pending", "Research is complete; the planner is next.", "plan", action

    plan_gate = gates.get("plan_approval", {})
    if statuses.get("plan") == "awaiting_approval" or not (
        isinstance(plan_gate, dict) and plan_gate.get("status") == "approved"
    ):
        action = guided_action(
            "approve-plan",
            "Review and approve the implementation plan",
            "loopforge run",
            requires_confirmation=True,
            why="Implementation cannot start until scope and checks are approved.",
        )
        return "plan_awaiting_approval", "The plan is waiting for approval.", "approve_plan", action

    run_status = str(normalized.get("status") or "")
    if statuses.get("implementation") != "complete":
        blocked = statuses.get("implementation") == "blocked"
        action = guided_action(
            "retry-attempt" if run_status == ADAPTER_BLOCKED else "continue",
            f"{'Retry' if blocked else 'Run'} the developer with {adapter}",
            f"loopforge continue --adapter {adapter}",
            risk="adapter-execution",
            requires_confirmation=profile != "autonomous",
            why="The developer may edit only the isolated workspace and approved scope.",
        )
        state = "implementation_blocked" if blocked else "implementation_pending"
        return state, "The approved plan is ready for implementation.", "implementation", action

    if statuses.get("verification") != "complete":
        action = guided_action(
            "verify",
            "Generate the patch and run deterministic checks",
            "loopforge verify",
            risk="verification",
            requires_confirmation=profile == "strict",
            why="Checks and policy evidence are required before review.",
        )
        state = "verification_blocked" if statuses.get("verification") == "blocked" else "verification_pending"
        return state, "Implementation is complete; verification is next.", "verification", action

    if statuses.get("review") not in {"complete", "approved"}:
        action = guided_action(
            "run-review",
            f"Run read-only patch review with {adapter}",
            "loopforge run",
            risk="read-only-agent",
            requires_confirmation=True,
            why="The reviewer compares the patch with the task, research, plan, and checks.",
        )
        return "review_pending", "Verification passed; the reviewer is next.", "review", action

    review_gate = gates.get("review_approval", {})
    if statuses.get("review") == "complete" or not (
        isinstance(review_gate, dict) and review_gate.get("status") == "approved"
    ):
        action = guided_action(
            "approve-review",
            "Approve the review for draft preparation",
            "loopforge run",
            requires_confirmation=True,
            why="Verification and review are evidence; publication authority remains human.",
        )
        return "review_awaiting_approval", "The review is waiting for approval.", "approve_review", action

    if statuses.get("publication") != "draft_prepared":
        action = guided_action(
            "prepare-draft",
            "Prepare the local draft PR artifact",
            "loopforge run",
            requires_confirmation=True,
            why="This prepares a local draft without pushing or opening a network PR.",
        )
        return "publication_pending", "Reviewed work is ready for draft preparation.", "publication", action

    action = guided_action(
        "status",
        "Inspect the completed run",
        "loopforge status --details",
        why="The full supervised workflow and local draft artifact are complete.",
    )
    return "draft_publication_ready", "The supervised workflow is complete.", "complete", action


def guidance_from_status(status: StatusResult) -> GuidanceResult:
    """Build guidance from an already loaded status without performing another read."""
    actions: list[GuidedAction] = []
    diagnostics: list[str] = []
    evidence: list[str] = [f"project: {status.project_dir}"]
    blocked_reasons = list(status.blockers)

    if not status.initialized:
        return GuidanceResult(
            project_dir=status.project_dir,
            state="not_initialized",
            summary="LoopForge is not initialized for this project yet.",
            priority="setup",
            diagnostics=[
                f"Expected config is missing: {status.config_path}",
                "Create project metadata before starting a run.",
            ],
            recommended_actions=[
                guided_action(
                    "init",
                    "Initialize LoopForge metadata",
                    "loopforge init",
                    why="The project needs .loopforge/config.json before runs can be created.",
                )
            ],
            blocked_reasons=[],
            evidence=evidence,
        )

    assert status.config is not None
    adapter = str(status.config.get("default_adapter") or DEFAULT_ADAPTER)
    adapter_args = status.config.get("default_adapter_args", [])
    if adapter not in SUPPORTED_ADAPTERS:
        diagnostics.append(f"default adapter is invalid: {adapter}")
        blocked_reasons.append(f"unsupported default adapter: {adapter}")
        actions.append(
            guided_action(
                "choose-adapter",
                "Choose a supported adapter",
                f"loopforge shell --command \"/adapter {DEFAULT_ADAPTER}\"",
                why="A valid adapter is required before LoopForge can execute an attempt.",
            )
        )
    else:
        evidence.append(f"default adapter: {adapter}")
        if isinstance(adapter_args, list) and adapter_args:
            evidence.append("default adapter args: " + " ".join(str(arg) for arg in adapter_args))

    if status.run is None:
        actions.append(
            guided_action(
                "create-run",
                "Create a run for the task",
                'loopforge run --task "Describe the task" --success-check "Describe the proof"',
                why="LoopForge needs a concrete task and objective success check to guide work.",
            )
        )
        return GuidanceResult(
            project_dir=status.project_dir,
            state="ready_for_run",
            summary="LoopForge is initialized, but there is no current run.",
            priority="next_task",
            diagnostics=diagnostics or ["No active run is selected."],
            recommended_actions=actions,
            blocked_reasons=blocked_reasons,
            evidence=evidence + [f"run root: {status.config.get('run_root')}"],
        )

    run = status.run
    run_status = str(run.get("status") or "unknown")
    profile = normalize_profile(run.get("profile", status.config.get("profile")))
    run_id = str(run.get("run_id") or "")
    task = str(run.get("task") or "")
    evidence.extend(
        [
            f"run: {run_id}",
            f"task: {task}",
            f"run status: {run_status}",
            f"run directory: {status.run_dir}",
        ]
    )
    if status.loop_contract is not None:
        evidence.append(f"loop contract: {status.loop_contract.get('status')}")
        diagnostics.append(
            f"success checks: {len(status.loop_contract.get('success_checks', []))}"
        )
        if profile == "autonomous":
            for reason in autonomous_stop_reasons(run, status.loop_contract):
                append_unique(blocked_reasons, reason)
    if status.memory is not None:
        pending = int(status.memory.get("pending", 0) or 0)
        if pending:
            diagnostics.append(f"memory proposals pending: {pending}")
            actions.append(
                guided_action(
                    "approve-memory",
                    "Review and approve safe memory proposals",
                    "loopforge learn --approve",
                    risk="memory",
                    requires_confirmation=True,
                    why="Durable memory changes should be explicitly reviewed before promotion.",
                )
            )

    staged = workflow_stage_guidance(run, adapter=adapter, profile=profile)
    if staged is not None:
        state, summary, priority, action = staged
        stage_actions = [action]
        if state == "implementation_blocked":
            stage_actions.append(
                guided_action(
                    "inspect-attempt",
                    "Inspect the latest attempt stderr",
                    'loopforge shell --command "/raw latest stderr"',
                    why="The latest attempt artifact usually contains the actionable error.",
                )
            )
        elif state == "verification_blocked":
            stage_actions.insert(
                0,
                guided_action(
                    "inspect-verification",
                    "Inspect verification diagnostics",
                    'loopforge shell --command "/export plan"',
                    why="The verification report and blockers explain what must be fixed.",
                )
            )
        if blocked_reasons:
            diagnostics.extend(blocked_reasons)
        return GuidanceResult(
            project_dir=status.project_dir,
            state=state,
            summary=summary,
            priority=priority,
            diagnostics=diagnostics or [status.next_step],
            recommended_actions=[*stage_actions, *actions],
            blocked_reasons=blocked_reasons,
            evidence=evidence,
        )

    if blocked_reasons:
        diagnostics.extend(blocked_reasons)

    if run_status == LOOP_CONTRACT_DRAFT:
        checks = status.loop_contract.get("success_checks", []) if status.loop_contract else []
        if not checks:
            blocked_reasons.append("the loop contract has no objective success checks")
            actions.append(
                guided_action(
                    "show-plan",
                    "Open the loop contract and add success checks",
                    "loopforge shell --command \"/plan\"",
                    why="Autonomous attempts need objective checks so progress can be verified.",
                )
            )
        actions.append(
            guided_action(
                "check-contract",
                "Re-check the loop contract",
                "loopforge continue",
                why="This validates whether the run is ready for an adapter attempt.",
            )
        )
        summary = "The current run needs a complete loop contract before execution."
        priority = "complete_contract"
    elif run_status == LOOP_CONTRACT_READY:
        if profile == "assist":
            actions.append(
                guided_action(
                    "review-contract",
                    "Review the ready loop contract",
                    "loopforge shell --command \"/plan\"",
                    why="Assist profile blocks workspace-changing adapter execution.",
                )
            )
        elif profile == "autonomous" and blocked_reasons:
            actions.append(
                guided_action(
                    "review-autonomy-stop",
                    "Review autonomy stop conditions",
                    "loopforge status",
                    why="Autonomous execution stops until a human resolves the listed condition.",
                )
            )
        else:
            actions.append(
                guided_action(
                    "continue",
                    f"Run a bounded attempt with {adapter}",
                    f"loopforge continue --adapter {adapter}",
                    risk="adapter-execution",
                    requires_confirmation=profile != "autonomous",
                    why=(
                        "The contract is ready and the autonomy profile allows a bounded "
                        "adapter attempt."
                    ),
                )
            )
        summary = "The run is ready for an adapter attempt."
        priority = "execute_attempt"
    elif run_status == ADAPTER_BLOCKED:
        if len(attempt_records(run)) < attempt_limit(run, status.loop_contract or {}):
            actions.append(
                guided_action(
                    "retry-attempt",
                    f"Retry a bounded attempt with {adapter}",
                    f"loopforge continue --adapter {adapter}",
                    risk="adapter-execution",
                    requires_confirmation=profile != "autonomous",
                    why="The previous attempt is recorded; a new attempt can continue with better context.",
                )
            )
        actions.append(
            guided_action(
                "inspect-attempt",
                "Inspect the latest attempt stderr",
                "loopforge shell --command \"/raw latest stderr\"",
                why="The latest attempt artifact usually contains the actionable error.",
            )
        )
        actions.append(
            guided_action(
                "tasks",
                "Review recorded attempts",
                "loopforge shell --command \"/tasks\"",
                why="Attempt history shows what was tried and where it stopped.",
            )
        )
        summary = "The last adapter attempt is blocked and needs diagnosis."
        priority = "resolve_blocker"
    elif run_status == READY_FOR_VERIFICATION:
        actions.append(
            guided_action(
                "verify",
                "Generate patch and run verification",
                "loopforge verify",
                risk="verification",
                requires_confirmation=profile == "strict",
                why="The workspace changed; deterministic checks should verify the result.",
            )
        )
        summary = "The attempt completed; verification is the next step."
        priority = "verify_work"
    elif run_status == VERIFICATION_FAILED:
        actions.append(
            guided_action(
                "inspect-verification",
                "Inspect verification diagnostics",
                "loopforge shell --command \"/export plan\"",
                why="The verification report and blockers explain what must be fixed.",
            )
        )
        actions.append(
            guided_action(
                "retry-verify",
                "Run verification again after fixing blockers",
                "loopforge verify",
                why="Re-running verification confirms whether the diagnostic was resolved.",
            )
        )
        summary = "Verification failed; inspect diagnostics, fix the issue, then verify again."
        priority = "fix_verification"
    elif run_status == VERIFIED:
        actions.append(
            guided_action(
                "compact",
                "Write a compact handoff",
                "loopforge shell --command \"/compact\"",
                why="A compact handoff records the verified state for review or continuation.",
            )
        )
        actions.append(
            guided_action(
                "review",
                "Review verified patch and decide handoff",
                "loopforge shell --command \"/review\"",
                why=(
                    "Verification is evidence, not publication authority; "
                    "a human decision remains."
                ),
            )
        )
        summary = "The run is verified and ready for review or handoff."
        priority = "review_verified_work"
    else:
        actions.append(
            guided_action(
                "status",
                "Inspect current status",
                "loopforge status",
                why="The run is in an unfamiliar state, so status is the safest first check.",
            )
        )
        summary = "LoopForge found a run state that needs human inspection."
        priority = "inspect_state"

    if not diagnostics:
        diagnostics.append(status.next_step)
    return GuidanceResult(
        project_dir=status.project_dir,
        state=run_status,
        summary=summary,
        priority=priority,
        diagnostics=diagnostics,
        recommended_actions=actions,
        blocked_reasons=blocked_reasons,
        evidence=evidence,
    )


def current_guidance(project_dir: Path) -> GuidanceResult:
    """Compatibility wrapper for callers that only have a project path."""

    return guidance_from_status(current_status(project_dir))


def run_summary_from_path(run_path: Path, *, current_run_id: str | None = None) -> dict[str, Any]:
    run_json_path = run_path / "run.json"
    summary: dict[str, Any] = {
        "run_id": run_path.name,
        "path": str(run_path),
        "current": run_path.name == current_run_id,
        "status": "missing",
        "task": "",
        "pack": "",
        "created_at": "",
        "updated_at": "",
    }
    if not run_json_path.exists():
        return summary
    try:
        run = read_json(run_json_path)
    except ValueError as error:
        summary.update({"status": "invalid", "error": str(error)})
        return summary
    summary.update(
        {
            "run_id": str(run.get("run_id") or run_path.name),
            "status": str(run.get("status") or "unknown"),
            "task": str(run.get("task") or ""),
            "pack": str(run.get("pack") or ""),
            "created_at": str(run.get("created_at") or ""),
            "updated_at": str(run.get("updated_at") or ""),
        }
    )
    return summary


def list_runs_from_status(status: StatusResult) -> RunListResult:
    """Summarize runs from an already loaded project status."""
    if not status.initialized or status.config is None:
        return RunListResult(
            project_dir=status.project_dir,
            run_root=None,
            initialized=False,
            config=None,
            current_run_id=None,
            runs=[],
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    current_run_id = str(status.config.get("current_run_id") or "") or None
    index = run_indexes.read_run_index(DEFAULT_JSON_STORE, run_root)
    if index is None:
        index = run_indexes.rebuild_run_index(
            DEFAULT_JSON_STORE,
            run_root,
            current_run_id=current_run_id,
            timestamp=utc_now(),
        )
    runs = [dict(entry) for entry in index.get("runs", []) if isinstance(entry, dict)]
    return RunListResult(
        project_dir=status.project_dir,
        run_root=run_root,
        initialized=True,
        config=status.config,
        current_run_id=current_run_id,
        runs=runs,
        blockers=[],
    )


def list_runs(project_dir: Path) -> RunListResult:
    """List compact runs without loading the current authoritative run."""

    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return RunListResult(project_dir, None, False, None, None, [], ["Initialize LoopForge with `loopforge init`."])
    config = normalize_config(project_dir, read_json(config_path))[0]
    synthetic = StatusResult(
        project_dir=project_dir,
        config_path=config_path,
        initialized=True,
        config=config,
        run_dir=None,
        run_json_path=None,
        run=None,
        native_artifacts=None,
        loop_contract=None,
        verification=None,
        memory=None,
        next_step="",
        blockers=[],
    )
    return list_runs_from_status(synthetic)


def run_attention(run: dict[str, Any]) -> str:
    """Classify persisted run state without treating history as a live process."""

    return run_indexes.run_attention(run)


def attention_order(value: object) -> int:
    return {
        "needs_human": 0,
        "blocked": 1,
        "running": 2,
        "ready": 3,
        "complete": 4,
        "archived": 5,
    }.get(str(value), 6)


def project_registry_summary(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    project_dir = Path(str(record.get("path") or "")).expanduser()
    project_id = str(record.get("project_id") or "")
    if not project_dir.exists():
        return (
            {
                **record,
                "initialized": False,
                "run_count": 0,
                "attention": "blocked",
                "last_activity": record.get("last_opened_at") or "",
                "branch": None,
                "current_run_id": None,
            },
            [f"registered project path is unavailable: {project_dir}"],
        )
    status = current_status(project_dir)
    runs = list_runs(project_dir)
    current = status.run if isinstance(status.run, dict) else None
    attention = run_attention(current) if current is not None else "ready"
    last_activity = ""
    if runs.runs:
        last_activity = max(str(run.get("updated_at") or run.get("created_at") or "") for run in runs.runs)
    return (
        {
            **record,
            "project_id": project_id,
            "name": str(record.get("name") or project_dir.name),
            "path": str(project_dir.resolve()),
            "initialized": status.initialized,
            "run_count": len(runs.runs),
            "attention": attention,
            "last_activity": last_activity or record.get("last_opened_at") or "",
            "branch": project_registry.git_branch(project_dir),
            "current_run_id": runs.current_run_id,
        },
        list(runs.blockers),
    )


def list_registered_projects(home: Path | None = None) -> ProjectListResult:
    home_root = loopforge_home(home=home)
    projects: list[dict[str, Any]] = []
    blockers: list[str] = []
    for record in project_registry.registered_projects(home_root):
        if record.get("summary_revision") == 1:
            summary, summary_blockers = dict(record), []
        else:
            # One compatibility scan upgrades registries created before the
            # compact summary existed. Normal Home reads never enter projects.
            summary, summary_blockers = project_registry_summary(record)
            if summary.get("project_id"):
                try:
                    project_registry.update_project_summary(home_root, str(summary["project_id"]), summary)
                except OSError:
                    summary_blockers.append("project summary registry is unavailable")
        projects.append(summary)
        blockers.extend(summary_blockers)
    projects.sort(key=lambda value: (attention_order(value.get("attention")), str(value.get("last_activity") or "")), reverse=False)
    # Recent activity is descending within the same attention family.
    projects.sort(key=lambda value: str(value.get("last_activity") or ""), reverse=True)
    projects.sort(key=lambda value: attention_order(value.get("attention")))
    return ProjectListResult(home_root, projects, blockers)


def list_runs_all_projects(home: Path | None = None) -> GlobalRunListResult:
    project_result = list_registered_projects(home)
    rows: list[dict[str, Any]] = []
    blockers = list(project_result.blockers)
    for project in project_result.projects:
        if not project.get("initialized"):
            continue
        project_dir = Path(str(project["path"]))
        result = list_runs(project_dir)
        blockers.extend(result.blockers)
        for run in result.runs:
            rows.append(
                {
                    **run,
                    "project_id": project.get("project_id") or "",
                    "project": project.get("name") or project_dir.name,
                    "project_path": str(project_dir),
                    "attention": str(run.get("attention") or "ready"),
                    "archived": bool(run.get("archived")),
                }
            )
    rows.sort(key=lambda value: str(value.get("updated_at") or value.get("created_at") or ""), reverse=True)
    rows.sort(key=lambda value: attention_order(value.get("attention")))
    return GlobalRunListResult(project_result.home, rows, blockers)


def current_or_selected_run(
    project_dir: Path,
    run_id: str | None = None,
) -> tuple[StatusResult, Path | None, Path | None, dict[str, Any] | None, list[str]]:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return status, None, None, None, [status.next_step]
    if run_id is None:
        if status.run is None or status.run_dir is None:
            blockers = status.blockers or [status.next_step]
            return status, status.run_dir, status.run_json_path, None, blockers
        return status, status.run_dir, status.run_json_path, status.run, []

    selected = run_id.strip()
    if not selected:
        return status, None, None, None, ["run id must not be empty"]
    run_dir = Path(str(status.config["run_root"])).expanduser() / selected
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return status, run_dir, run_json_path, None, [f"run metadata not found: {run_json_path}"]
    return status, run_dir, run_json_path, read_json(run_json_path), []


def nonnegative_int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def first_nonnegative_int(*values: object) -> int | None:
    for value in values:
        parsed = nonnegative_int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def latest_attempt(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = attempt_records(run)
    return attempts[-1] if attempts else None


def read_attempt_protocol_result(run_dir: Path, attempt: dict[str, Any] | None) -> dict[str, Any]:
    if attempt is None:
        return {}
    raw_path = attempt.get("result_path")
    if not isinstance(raw_path, str) or not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = run_dir / path
    if not path.exists():
        return {}
    try:
        result = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return result


def model_from_command(command: object) -> str | None:
    if not isinstance(command, list):
        return None
    parts = [str(part) for part in command]
    for index, part in enumerate(parts):
        if part in {"-m", "--model"} and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith("--model="):
            return part.split("=", 1)[1] or None
    return None


def metrics_model(
    *,
    override: str | None,
    attempt: dict[str, Any] | None,
    protocol_result: dict[str, Any],
) -> dict[str, Any]:
    model: str | None = override.strip() if isinstance(override, str) and override.strip() else None
    if model is None:
        raw_model = protocol_result.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        elif isinstance(raw_model, dict):
            candidate = raw_model.get("id") or raw_model.get("name")
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
    if model is None:
        for key in ("model_id", "model_name"):
            candidate = protocol_result.get(key)
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
                break
    if model is None and attempt is not None:
        model = model_from_command(attempt.get("command"))
    return {
        "status": "reported" if model is not None else "unavailable",
        "id": model,
    }


def metrics_tokens(
    *,
    protocol_result: dict[str, Any],
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
) -> dict[str, Any]:
    source = protocol_result.get("tokens")
    if not isinstance(source, dict):
        source = protocol_result.get("usage")
    if not isinstance(source, dict):
        source = {}
    measured_input = first_nonnegative_int(
        input_tokens,
        source.get("input_tokens"),
        source.get("prompt_tokens"),
    )
    measured_output = first_nonnegative_int(
        output_tokens,
        source.get("output_tokens"),
        source.get("completion_tokens"),
    )
    measured_total = first_nonnegative_int(total_tokens, source.get("total_tokens"))
    if measured_total is None and measured_input is not None and measured_output is not None:
        measured_total = measured_input + measured_output
    status = (
        "reported"
        if any(value is not None for value in (measured_input, measured_output, measured_total))
        else "unavailable"
    )
    return {
        "status": status,
        "input_tokens": measured_input,
        "output_tokens": measured_output,
        "total_tokens": measured_total,
    }


def metrics_cost(
    *,
    protocol_result: dict[str, Any],
    amount_microunits: int | None,
    currency: str | None,
) -> dict[str, Any]:
    source = protocol_result.get("cost")
    if not isinstance(source, dict):
        source = {}
    measured_amount = first_nonnegative_int(
        amount_microunits,
        source.get("amount_microunits"),
        source.get("total_microunits"),
    )
    measured_currency = (
        currency.strip().upper()
        if isinstance(currency, str) and currency.strip()
        else None
    )
    if measured_currency is None:
        raw_currency = source.get("currency")
        if isinstance(raw_currency, str) and raw_currency.strip():
            measured_currency = raw_currency.strip().upper()
    return {
        "status": "reported" if measured_amount is not None else "unavailable",
        "amount_microunits": measured_amount,
        "currency": measured_currency if measured_amount is not None else None,
    }


def metrics_patch(verification: dict[str, Any] | None) -> dict[str, Any]:
    if verification is None:
        return {
            "status": "unavailable",
            "path": None,
            "size_bytes": None,
            "sha256": None,
        }
    patch = verification.get("patch", {})
    if not isinstance(patch, dict):
        patch = {}
    size = nonnegative_int_or_none(patch.get("size_bytes"))
    generated = bool(patch.get("generated"))
    if generated or patch.get("status") == "generated":
        status = "measured"
    else:
        status = "not_generated"
    return {
        "status": status,
        "path": patch.get("path") if isinstance(patch.get("path"), str) else None,
        "size_bytes": size if size is not None else (0 if status == "not_generated" else None),
        "sha256": patch.get("sha256") if isinstance(patch.get("sha256"), str) else None,
    }


def inferred_final_disposition(run_status: object) -> str:
    status = str(run_status or "unknown")
    if status == VERIFIED:
        return "verified"
    if status == VERIFICATION_FAILED:
        return "failed"
    if status == ADAPTER_BLOCKED:
        return "blocked"
    if status == READY_FOR_VERIFICATION:
        return "pending_verification"
    if status in {LOOP_CONTRACT_DRAFT, LOOP_CONTRACT_READY}:
        return "pending"
    return status


def build_metrics_record(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> dict[str, Any]:
    attempt = latest_attempt(run)
    protocol_result = read_attempt_protocol_result(run_dir, attempt)
    verification = verification_state(run)
    finished_at = (
        verification.get("finished_at")
        if isinstance(verification, dict) and verification.get("finished_at")
        else (attempt or {}).get("finished_at")
    )
    if not finished_at:
        finished_at = run.get("updated_at") or run.get("created_at")
    measured_duration = duration_seconds(run.get("created_at"), finished_at)
    attempt_count = run.get("attempt_count")
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = len(attempt_records(run))
    adapter = attempt.get("adapter") if isinstance(attempt, dict) else None
    final = (
        final_disposition.strip()
        if isinstance(final_disposition, str) and final_disposition.strip()
        else inferred_final_disposition(run.get("status"))
    )
    corrections = nonnegative_int_or_none(human_corrections)
    if corrections is None:
        corrections = nonnegative_int_or_none(run.get("human_correction_count"))
    return {
        "metrics_version": 1,
        "recorded_at": utc_now(),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "task": run.get("task"),
        "project_root": str(project_dir),
        "profile": run.get("profile"),
        "pack": run.get("pack"),
        "timing": {
            "started_at": run.get("created_at"),
            "finished_at": finished_at,
            "duration_seconds": measured_duration,
            "status": "measured" if measured_duration is not None else "unavailable",
        },
        "adapter": {
            "status": "reported" if isinstance(adapter, str) and adapter else "unavailable",
            "id": adapter if isinstance(adapter, str) and adapter else None,
        },
        "model": metrics_model(
            override=model,
            attempt=attempt,
            protocol_result=protocol_result,
        ),
        "attempts": {
            "count": attempt_count,
            "statuses": [
                str(item.get("status") or "unknown")
                for item in attempt_records(run)
            ],
        },
        "tokens": metrics_tokens(
            protocol_result=protocol_result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        "cost": metrics_cost(
            protocol_result=protocol_result,
            amount_microunits=cost_microunits,
            currency=cost_currency,
        ),
        "patch": metrics_patch(verification),
        "verification": {
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "checks_passed": (
                verification.get("checks_passed") if isinstance(verification, dict) else None
            ),
            "checks_total": (
                verification.get("checks_total") if isinstance(verification, dict) else None
            ),
        },
        "human_corrections": {
            "status": "measured" if corrections is not None else "unavailable",
            "count": corrections,
        },
        "final_disposition": {
            "status": final,
            "source": "reported" if final_disposition else "run_status",
        },
    }


def record_run_metrics(
    project_dir: Path,
    *,
    run_id: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> MetricsRecordResult:
    status, run_dir, _run_json_path, run, blockers = current_or_selected_run(project_dir, run_id)
    if blockers or run is None or run_dir is None:
        return MetricsRecordResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge metrics record failed.",
            record_path=None,
            record=None,
            blockers=blockers,
        )
    record = build_metrics_record(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_microunits=cost_microunits,
        cost_currency=cost_currency,
        human_corrections=human_corrections,
        final_disposition=final_disposition,
    )
    record_path = run_dir / "metrics" / METRICS_RECORD_FILE
    write_json_atomic(record_path, record)
    return MetricsRecordResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        ok=True,
        message="LoopForge metrics recorded.",
        record_path=record_path,
        record=record,
        blockers=[],
    )


def _metrics_service() -> MetricsService:
    return MetricsService(DEFAULT_JSON_STORE, record_file=METRICS_RECORD_FILE)


def metric_number(value: object) -> int | float | None:
    return MetricsService.metric_number(value)


def summarize_number_series(records: list[dict[str, Any]], values: list[object]) -> dict[str, Any]:
    return MetricsService.summarize_number_series(records, values)


def count_values(values: list[object]) -> dict[str, int]:
    return MetricsService.count_values(values)


def summarize_token_field(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    return _metrics_service().summarize_token_field(records, field)


def summarize_costs(records: list[dict[str, Any]]) -> dict[str, Any]:
    return _metrics_service().summarize_costs(records)


def build_metrics_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return _metrics_service().build_summary(records)


def summarize_run_metrics(project_dir: Path) -> MetricsSummaryResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return MetricsSummaryResult(
            project_dir=status.project_dir,
            run_root=None,
            ok=False,
            message="LoopForge metrics summarize failed.",
            records=[],
            summary=build_metrics_summary([]),
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    records, blockers = _metrics_service().load_records(run_root)
    summary = build_metrics_summary(records)
    return MetricsSummaryResult(
        project_dir=status.project_dir,
        run_root=run_root,
        ok=not blockers,
        message=(
            "LoopForge metrics summary ready."
            if not blockers
            else "LoopForge metrics summary has warnings."
        ),
        records=records,
        summary=summary,
        blockers=blockers,
    )


def compact_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def dashboard_number_summary(records: list[dict[str, Any]], values: list[object]) -> dict[str, Any]:
    return summarize_number_series(records, values)


def dashboard_attempt_rows(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    if run is None:
        return []
    rows: list[dict[str, Any]] = []
    for attempt in attempt_records(run):
        rows.append(
            {
                "id": compact_text(attempt.get("id")),
                "adapter": compact_text(attempt.get("adapter") or "unknown"),
                "status": compact_text(attempt.get("status") or "unknown"),
                "summary": compact_text(attempt.get("summary"), limit=160),
                "started_at": compact_text(attempt.get("started_at")),
                "finished_at": compact_text(attempt.get("finished_at")),
                "stdout_path": compact_text(attempt.get("stdout_path")),
                "stderr_path": compact_text(attempt.get("stderr_path")),
            }
        )
    return rows


def dashboard_memory_proposal_rows(memory: dict[str, Any] | None) -> list[dict[str, Any]]:
    if memory is None:
        return []
    proposal_path = memory.get("proposal_path")
    if not isinstance(proposal_path, str) or not proposal_path:
        return []
    path = Path(proposal_path)
    if not path.exists():
        return []
    try:
        data = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    proposals = data.get("proposals", [])
    if not isinstance(proposals, list):
        return []
    rows: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        rows.append(
            {
                "id": compact_text(proposal.get("id")),
                "status": compact_text(proposal.get("status") or "unknown"),
                "category": compact_text(proposal.get("category")),
                "source": compact_text(
                    proposal.get("source_path") or proposal.get("source"),
                    limit=160,
                ),
                "text": compact_text(proposal.get("text"), limit=200),
                "rejection_reason": compact_text(proposal.get("rejection_reason"), limit=160),
                "promotion_reason": compact_text(proposal.get("promotion_reason"), limit=160),
            }
        )
    return rows


def dashboard_adapter_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        adapter = record.get("adapter") if isinstance(record.get("adapter"), dict) else {}
        adapter_id = adapter.get("id") if isinstance(adapter, dict) else None
        key = adapter_id if isinstance(adapter_id, str) and adapter_id else "unknown"
        grouped.setdefault(key, []).append(record)

    groups: list[dict[str, Any]] = []
    for adapter_id in sorted(grouped):
        adapter_records = grouped[adapter_id]
        groups.append(
            {
                "adapter": adapter_id,
                "record_count": len(adapter_records),
                "duration_seconds": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("timing", {}).get("duration_seconds")
                        if isinstance(record.get("timing"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "attempt_count": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("attempts", {}).get("count")
                        if isinstance(record.get("attempts"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "total_tokens": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("tokens", {}).get("total_tokens")
                        if isinstance(record.get("tokens"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "patch_size_bytes": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("patch", {}).get("size_bytes")
                        if isinstance(record.get("patch"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "cost": summarize_costs(adapter_records),
                "verification_results": count_values(
                    [
                        record.get("verification", {}).get("status")
                        if isinstance(record.get("verification"), dict)
                        else None
                        for record in adapter_records
                    ]
                ),
                "final_dispositions": count_values(
                    [
                        record.get("final_disposition", {}).get("status")
                        if isinstance(record.get("final_disposition"), dict)
                        else None
                        for record in adapter_records
                    ]
                ),
            }
        )
    return {"record_count": len(records), "groups": groups}


def dashboard_snapshot(project_dir: Path) -> DashboardResult:
    status = current_status(project_dir)
    guidance = current_guidance(project_dir)
    run_list = list_runs(project_dir)
    metrics = summarize_run_metrics(project_dir)
    run = status.run
    contract = status.loop_contract or {}
    attempts = dashboard_attempt_rows(run)
    blockers = list(status.blockers)
    for source in (guidance.blocked_reasons, run_list.blockers, metrics.blockers):
        for blocker in source:
            append_unique(blockers, str(blocker))

    limits: dict[str, Any] = {"max_attempts": None, "timeout_seconds": None}
    if run is not None:
        limits["max_attempts"] = attempt_limit(run, contract)
        limits["timeout_seconds"] = attempt_timeout(run, contract)

    action = guidance.recommended_actions[0] if guidance.recommended_actions else None
    memory_rows = dashboard_memory_proposal_rows(status.memory)
    verification = status.verification or {}
    patch = verification.get("patch", {}) if isinstance(verification, dict) else {}
    diff_policy = verification.get("diff_policy", {}) if isinstance(verification, dict) else {}
    risk = verification.get("risk", {}) if isinstance(verification, dict) else {}

    snapshot = {
        "dashboard_version": 1,
        "project": {
            "path": str(status.project_dir),
            "name": status.project_dir.name,
            "initialized": status.initialized,
            "config_path": str(status.config_path),
            "profile": status.config.get("profile") if status.config else None,
            "run_root": status.config.get("run_root") if status.config else None,
            "current_run_id": status.config.get("current_run_id") if status.config else None,
            "default_adapter": status.config.get("default_adapter") if status.config else None,
        },
        "runs": {
            "run_root": str(run_list.run_root) if run_list.run_root is not None else None,
            "current_run_id": run_list.current_run_id,
            "total": len(run_list.runs),
            "items": run_list.runs,
        },
        "current_loop": {
            "available": run is not None,
            "run_id": run.get("run_id") if run else None,
            "task": run.get("task") if run else None,
            "status": run.get("status") if run else None,
            "profile": run.get("profile") if run else None,
            "pack": run.get("pack") if run else None,
            "run_dir": str(status.run_dir) if status.run_dir is not None else None,
            "loop_contract_status": contract.get("status") if contract else None,
            "success_checks": contract.get("success_checks", []) if contract else [],
            "allowed_tools": contract.get("allowed_tools", []) if contract else [],
            "subjective": bool(contract.get("subjective")) if contract else False,
            "rubric_present": bool(contract.get("rubric")) if contract else False,
            "attempts_count": len(attempts),
            "limits": limits,
            "next_step": status.next_step,
        },
        "attempts": {
            "count": len(attempts),
            "max_attempts": limits["max_attempts"],
            "remaining": (
                max(0, int(limits["max_attempts"]) - len(attempts))
                if isinstance(limits["max_attempts"], int)
                else None
            ),
            "items": attempts,
        },
        "verification": {
            "available": bool(verification),
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "patch_path": patch.get("path") if isinstance(patch, dict) else None,
            "patch_size_bytes": patch.get("size_bytes") if isinstance(patch, dict) else None,
            "diff_policy_allowed": (
                diff_policy.get("allowed") if isinstance(diff_policy, dict) else None
            ),
            "risk": risk.get("risk") if isinstance(risk, dict) else None,
            "checks_passed": (
                verification.get("checks_passed") if isinstance(verification, dict) else None
            ),
            "checks_total": (
                verification.get("checks_total") if isinstance(verification, dict) else None
            ),
            "stagnated": bool(verification.get("stagnated"))
            if isinstance(verification, dict)
            else False,
        },
        "memory": {
            "available": status.memory is not None,
            "durable_path": status.memory.get("durable_path") if status.memory else None,
            "durable_items": status.memory.get("durable_items") if status.memory else None,
            "run_snapshot": status.memory.get("run_snapshot") if status.memory else None,
            "proposal_path": status.memory.get("proposal_path") if status.memory else None,
            "pending": status.memory.get("pending", 0) if status.memory else 0,
            "promoted": status.memory.get("promoted", 0) if status.memory else 0,
            "rejected": status.memory.get("rejected", 0) if status.memory else 0,
            "proposal_rows": memory_rows,
            "pending_proposals": [
                proposal for proposal in memory_rows if proposal.get("status") == "pending"
            ],
        },
        "adapter_comparison": dashboard_adapter_comparison(metrics.records),
        "next_human_action": {
            "available": action is not None,
            "id": action.id if action else None,
            "label": action.label if action else None,
            "command": action.command if action else None,
            "do_command": f"loopforge shell --command \"/do {action.id}\"" if action else None,
            "risk": action.risk if action else None,
            "requires_confirmation": action.requires_confirmation if action else None,
            "why": action.why if action else None,
        },
        "blockers": blockers,
    }
    return DashboardResult(
        project_dir=status.project_dir,
        ok=not blockers and metrics.ok,
        snapshot=snapshot,
        blockers=blockers,
    )


def dashboard_average_text(series: object) -> str:
    if not isinstance(series, dict):
        return "unknown"
    average = series.get("average")
    if average is None:
        return "unknown"
    if isinstance(average, float):
        return f"{average:.2f}".rstrip("0").rstrip(".")
    return str(average)


def dashboard_text_lines(snapshot: dict[str, Any]) -> list[str]:
    lines = ["LoopForge dashboard"]
    project = snapshot.get("project", {}) if isinstance(snapshot.get("project"), dict) else {}
    lines.extend(
        [
            f"project: {project.get('name') or 'unknown'}",
            f"initialized: {project.get('initialized')}",
            f"profile: {project.get('profile') or 'none'}",
            "",
            "Run list",
        ]
    )
    runs = snapshot.get("runs", {}) if isinstance(snapshot.get("runs"), dict) else {}
    run_items = runs.get("items", []) if isinstance(runs.get("items"), list) else []
    lines.append(f"run root: {runs.get('run_root') or 'none'}")
    lines.append(f"runs: {runs.get('total', len(run_items))}")
    if run_items:
        for run in run_items[:10]:
            if not isinstance(run, dict):
                continue
            marker = "*" if run.get("current") else "-"
            task = compact_text(run.get("task"), limit=80)
            lines.append(f"{marker} {run.get('run_id')} [{run.get('status')}] {task}")
    else:
        lines.append("- none")

    current = (
        snapshot.get("current_loop", {})
        if isinstance(snapshot.get("current_loop"), dict)
        else {}
    )
    limits = current.get("limits", {}) if isinstance(current.get("limits"), dict) else {}
    lines.extend(
        [
            "",
            "Current loop",
            f"run id: {current.get('run_id') or 'none'}",
            f"task: {compact_text(current.get('task'), limit=120) or 'none'}",
            f"status: {current.get('status') or 'none'}",
            f"pack: {current.get('pack') or 'none'}",
            f"loop contract: {current.get('loop_contract_status') or 'none'}",
            f"success checks: {len(current.get('success_checks') or [])}",
            (
                "limits: "
                f"max_attempts={limits.get('max_attempts')}, "
                f"timeout_seconds={limits.get('timeout_seconds')}"
            ),
            f"next step: {current.get('next_step') or 'none'}",
            "",
            "Attempts",
        ]
    )
    attempts = snapshot.get("attempts", {}) if isinstance(snapshot.get("attempts"), dict) else {}
    attempt_items = attempts.get("items", []) if isinstance(attempts.get("items"), list) else []
    lines.append(
        f"attempts: {attempts.get('count', 0)}/"
        f"{attempts.get('max_attempts') or 'unknown'}"
    )
    if attempt_items:
        for attempt in attempt_items[:10]:
            if isinstance(attempt, dict):
                lines.append(
                    "- "
                    f"{attempt.get('id')}: {attempt.get('adapter')} "
                    f"[{attempt.get('status')}] {attempt.get('summary')}"
                )
    else:
        lines.append("- none")

    verification = (
        snapshot.get("verification", {})
        if isinstance(snapshot.get("verification"), dict)
        else {}
    )
    lines.extend(
        [
            "",
            "Verification",
            f"status: {verification.get('status') or 'not run'}",
            f"risk: {verification.get('risk') or 'unknown'}",
            (
                "checks: "
                f"{verification.get('checks_passed') or 0}/"
                f"{verification.get('checks_total') or 0}"
            ),
            f"patch size bytes: {verification.get('patch_size_bytes') or 'unknown'}",
            "",
            "Memory proposals",
        ]
    )
    memory = snapshot.get("memory", {}) if isinstance(snapshot.get("memory"), dict) else {}
    proposals = (
        memory.get("proposal_rows", []) if isinstance(memory.get("proposal_rows"), list) else []
    )
    lines.append(f"durable items: {memory.get('durable_items') or 0}")
    lines.append(
        "proposals: "
        f"{memory.get('pending', 0)} pending, "
        f"{memory.get('promoted', 0)} promoted, "
        f"{memory.get('rejected', 0)} rejected"
    )
    if proposals:
        for proposal in proposals[:10]:
            if isinstance(proposal, dict):
                lines.append(
                    "- "
                    f"{proposal.get('id')}: {proposal.get('status')} "
                    f"{proposal.get('category')} - {proposal.get('text')}"
                )
    else:
        lines.append("- none")

    comparison = (
        snapshot.get("adapter_comparison", {})
        if isinstance(snapshot.get("adapter_comparison"), dict)
        else {}
    )
    groups = comparison.get("groups", []) if isinstance(comparison.get("groups"), list) else []
    lines.extend(["", "Adapter comparison", f"records: {comparison.get('record_count', 0)}"])
    if groups:
        for group in groups:
            if not isinstance(group, dict):
                continue
            cost = group.get("cost", {}) if isinstance(group.get("cost"), dict) else {}
            lines.append(
                "- "
                f"{group.get('adapter')}: records={group.get('record_count')}, "
                f"duration_avg={dashboard_average_text(group.get('duration_seconds'))}, "
                f"attempts_avg={dashboard_average_text(group.get('attempt_count'))}, "
                f"tokens_avg={dashboard_average_text(group.get('total_tokens'))}, "
                f"patch_avg={dashboard_average_text(group.get('patch_size_bytes'))}, "
                f"cost_known={cost.get('known_count', 0)}"
            )
    else:
        lines.append("- none")

    action = (
        snapshot.get("next_human_action", {})
        if isinstance(snapshot.get("next_human_action"), dict)
        else {}
    )
    lines.extend(["", "Next human action"])
    if action.get("available"):
        lines.extend(
            [
                f"id: {action.get('id')}",
                f"label: {action.get('label')}",
                f"command: {action.get('command')}",
                f"do command: {action.get('do_command')}",
                f"requires confirmation: {action.get('requires_confirmation')}",
                f"why: {action.get('why')}",
            ]
        )
    else:
        lines.append("- none")

    blockers = snapshot.get("blockers", [])
    lines.extend(["", "Blockers"])
    if isinstance(blockers, list) and blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")
    return lines


def resume_run(project_dir: Path, run_id: str) -> ResumeRunResult:
    if not run_id.strip():
        return ResumeRunResult(
            project_dir=project_dir.resolve(),
            run_dir=None,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=["run id must not be empty"],
        )

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ResumeRunResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    run_dir = run_root / run_id.strip()
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return ResumeRunResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=[f"run metadata not found: {run_json_path}"],
        )

    run = read_json(run_json_path)
    config = dict(status.config)
    config["current_run_id"] = str(run.get("run_id") or run_id.strip())
    config["updated_at"] = utc_now()
    persist_project_config(status.project_dir, status.config_path, config)
    return ResumeRunResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        ok=True,
        message=f"LoopForge resumed run: {config['current_run_id']}",
        blockers=[],
    )


def directory_file_sizes(root: Path) -> list[tuple[str, int]]:
    if not root.exists():
        return []
    sizes: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                sizes.append((str(path.relative_to(root)), path.stat().st_size))
            except OSError:
                continue
    return sizes


def render_compact_context(status: StatusResult, *, focus: str = "") -> str:
    lines = [
        "# LoopForge Compact Context",
        "",
        f"- Generated: {utc_now()}",
        f"- Project: {status.project_dir}",
    ]
    if focus.strip():
        lines.append(f"- Focus: {focus.strip()}")
    if status.config is not None:
        lines.extend(
            [
                f"- Profile: {status.config.get('profile')}",
                f"- Run root: {status.config.get('run_root')}",
            ]
        )
    if status.run is None or status.run_dir is None:
        lines.extend(["", "## Current Run", "", "No current run is available."])
    else:
        run = status.run
        lines.extend(
            [
                "",
                "## Current Run",
                "",
                f"- Run ID: {run.get('run_id')}",
                f"- Task: {run.get('task')}",
                f"- Status: {run.get('status')}",
                f"- Pack: {run.get('pack')}",
                f"- Attempts: {run.get('attempt_count', len(run.get('attempts', [])))}",
                f"- Run directory: {status.run_dir}",
            ]
        )
        checks = run.get("success_checks", [])
        if isinstance(checks, list) and checks:
            lines.extend(["", "## Success Checks", ""])
            lines.extend(f"- {check}" for check in checks)
        if status.loop_contract is not None:
            lines.extend(
                [
                    "",
                    "## Loop Contract",
                    "",
                    f"- Status: {status.loop_contract.get('status')}",
                    f"- Subjective: {'yes' if status.loop_contract.get('subjective') else 'no'}",
                    f"- Rubric: {'present' if status.loop_contract.get('rubric') else 'missing'}",
                ]
            )
        if status.verification is not None:
            verification = status.verification
            checks_passed = verification.get("checks_passed", 0)
            checks_total = verification.get("checks_total", 0)
            lines.extend(
                [
                    "",
                    "## Verification",
                    "",
                    f"- Status: {verification.get('status')}",
                    f"- Checks: {checks_passed}/{checks_total}",
                ]
            )
            patch = verification.get("patch", {})
            if isinstance(patch, dict):
                lines.append(f"- Patch: {patch.get('path') or 'none'}")
        if status.memory is not None:
            memory = status.memory
            lines.extend(
                [
                    "",
                    "## Memory",
                    "",
                    f"- Durable items: {memory.get('durable_items', 0)}",
                    f"- Pending proposals: {memory.get('pending', 0)}",
                    f"- Run snapshot: {memory.get('run_snapshot') or 'none'}",
                ]
            )
        sizes = directory_file_sizes(status.run_dir)
        if sizes:
            lines.extend(["", "## Run Files", ""])
            for relative_name, size in sizes[:40]:
                lines.append(f"- {relative_name}: {size} bytes")
            if len(sizes) > 40:
                lines.append(f"- ... {len(sizes) - 40} more files")

    lines.extend(["", "## Blockers", ""])
    if status.blockers:
        lines.extend(f"- {blocker}" for blocker in status.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Next Step", "", status.next_step, ""])
    return "\n".join(lines)


def compact_current_context(project_dir: Path, *, focus: str = "") -> CompactContextResult:
    status = current_status(project_dir)
    summary = render_compact_context(status, focus=focus)
    if not status.initialized:
        return CompactContextResult(
            project_dir=status.project_dir,
            run_dir=None,
            path=None,
            ok=False,
            message="LoopForge compact failed.",
            summary=summary,
            blockers=[status.next_step],
        )
    if status.run_dir is None:
        return CompactContextResult(
            project_dir=status.project_dir,
            run_dir=None,
            path=None,
            ok=False,
            message="LoopForge compact failed.",
            summary=summary,
            blockers=[status.next_step],
        )
    target_dir = status.run_dir / "artifacts" / "context"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "compact.md"
    target_path.write_text(summary, encoding="utf-8")
    return CompactContextResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        path=target_path,
        ok=True,
        message=f"LoopForge compact context written: {target_path}",
        summary=summary,
        blockers=[],
    )


def new_run_id() -> str:
    timestamp = utc_now().replace("-", "").replace(":", "").replace("Z", "Z")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def create_run(
    project_dir: Path,
    task: str,
    *,
    pack: str | None = None,
    success_checks: list[str] | None = None,
    selected_skills: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    max_attempts: int = 3,
    timeout_seconds: int = 1800,
    subjective_rubric: str = "",
    source_metadata: dict[str, Any] | None = None,
    initial_approval: dict[str, Any] | None = None,
) -> RunResult:
    if not task.strip():
        raise ValueError("task must not be empty")
    if max_attempts < 1:
        raise ValueError("max attempts must be at least 1")
    if timeout_seconds < 1:
        raise ValueError("timeout must be at least 1 second")

    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} does not exist; run `loopforge init` first")

    config = normalize_config(project_dir, read_json(config_path))[0]
    project_memory = ensure_project_memory(project_dir)
    run_root = Path(str(config["run_root"])).expanduser()
    run_id = new_run_id()
    run_dir = run_root / run_id
    while run_dir.exists():
        run_id = new_run_id()
        run_dir = run_root / run_id

    attempts_dir = run_dir / "attempts"
    artifacts_dir = run_dir / "artifacts"
    metrics_dir = run_dir / "metrics"
    for directory in (attempts_dir, artifacts_dir, metrics_dir):
        directory.mkdir(parents=True, exist_ok=False)

    now = utc_now()
    base_commit = detect_git_base_commit(project_dir)
    workspace_state = prepare_run_workspace(
        project_dir=project_dir,
        run_id=run_id,
        base_commit=base_commit,
        now=now,
        project_id=str(config.get("project_id") or "") or None,
    )
    task_id = run_id
    normalized_success_checks = normalize_nonempty_strings(success_checks)
    if pack is None:
        pack_contract = detect_project_pack(project_dir)
        selected_pack = str(pack_contract["name"])
        pack_detection = "auto"
    else:
        selected_pack = pack.strip()
        if not selected_pack:
            raise ValueError("pack must not be empty")
        pack_contract = load_pack_contract(project_dir, selected_pack)
        pack_detection = "explicit"
    run_profile = normalize_profile(config["profile"])
    pack_skills = pack_skill_entries(pack_contract)
    normalized_skills = normalize_unique_strings(
        [*pack_skills, *normalize_nonempty_strings(selected_skills)]
    )
    normalized_allowed_tools = normalize_nonempty_strings(allowed_tools) or list(
        DEFAULT_ALLOWED_TOOLS
    )
    normalized_rubric = subjective_rubric.strip()
    subjective = task_looks_subjective(task)
    contract_status = loop_contract_status(
        success_checks=normalized_success_checks,
        profile=run_profile,
        subjective=subjective,
        subjective_rubric=normalized_rubric,
    )
    task_validation = validate_task_definition(
        task=task.strip(),
        success_checks=normalized_success_checks,
        profile=run_profile,
        subjective=subjective,
        subjective_rubric=normalized_rubric,
    )
    run_data: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "task": task.strip(),
        "project_root": str(project_dir),
        "base_commit": base_commit,
        "workspace": workspace_state,
        "profile": run_profile,
        "profile_policy": profile_policy(run_profile),
        "pack": selected_pack,
        "pack_contract": {
            "name": selected_pack,
            "version": pack_contract.get("version"),
            "description": pack_contract.get("description"),
            "source": pack_contract.get("source"),
            "detection": pack_detection,
            "detection_score": pack_contract.get("detection_score", 0),
            "skills": pack_skills,
            "skill_files": pack_contract.get("skill_files", []),
            "skills_dirs": pack_contract.get("skills_dirs", []),
            "skill_definition_files": pack_contract.get("skill_definition_files", []),
            "agents": pack_contract.get("agents", []),
            "permission_sets": pack_contract.get("permission_sets", {}),
            "workflow": pack_contract.get("workflow", []),
            "inherited_from": pack_contract.get("inherited_from", []),
            "contribution_sources": pack_contract.get("contribution_sources", {}),
            "skill_file": pack_contract.get("skill_file"),
            "agents_file": pack_contract.get("agents_file"),
            "permissions_file": pack_contract.get("permissions_file"),
            "workflow_file": pack_contract.get("workflow_file"),
            "checks_file": pack_contract.get("checks_file"),
            "protected_paths_file": pack_contract.get("protected_paths_file"),
            "memory_rules_file": pack_contract.get("memory_rules_file"),
        },
        "status": contract_status,
        **initial_workflow_state(),
        "task_validation": task_validation,
        "created_at": now,
        "success_checks": normalized_success_checks,
        "limits": {
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
        },
        "attempt_count": 0,
        "attempts": [],
        "blockers": [],
        "loop_contract": {
            "path": str(run_dir / "loop.md"),
            "version": 1,
            "status": contract_status,
            "subjective": subjective,
            "requires_rubric": run_profile == "autonomous" and subjective,
        },
        "memory": {
            "durable_project_memory": str(project_memory),
            "run_snapshot": str(run_dir / "memory.md"),
            "pending_proposals": 0,
            "promoted": 0,
            "rejected": 0,
        },
        "artifacts": {
            "task": str(run_dir / "task.md"),
            "loop": str(run_dir / "loop.md"),
            "research": str(run_dir / "research.md"),
            "plan": str(run_dir / "plan.md"),
            "progress": str(run_dir / "progress.md"),
            "verification": str(run_dir / "verification.md"),
            "review": str(run_dir / "review.md"),
            "memory": str(run_dir / "memory.md"),
            "scratch": str(run_dir / "scratch.md"),
            "exchange": str(run_dir / "exchange.json"),
            "attempts": str(attempts_dir),
            "artifacts": str(artifacts_dir),
            "metrics": str(metrics_dir),
        },
    }
    if source_metadata:
        run_data["evidence"] = {"source": source_metadata}
    if isinstance(initial_approval, dict):
        run_data = apply_initial_task_approval(
            run_data,
            approved=bool(initial_approval.get("approved")),
            source=str(initial_approval.get("source") or "none"),
            approved_at=(
                str(initial_approval.get("approved_at"))
                if initial_approval.get("approved_at")
                else None
            ),
        )
    else:
        run_data = apply_initial_task_approval(
            run_data,
            approved=False,
            source="none",
        )

    persist_run_json(project_dir, run_dir / "run.json", run_data)
    (run_dir / "task.md").write_text(f"# Task\n\n{task.strip()}\n", encoding="utf-8")
    (run_dir / "loop.md").write_text(
        render_loop_contract(
            task=task.strip(),
            task_id=task_id,
            project_dir=project_dir,
            base_commit=base_commit,
            profile=run_profile,
            pack=selected_pack,
            skills=normalized_skills,
            allowed_tools=normalized_allowed_tools,
            success_checks=normalized_success_checks,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            subjective=subjective,
            subjective_rubric=normalized_rubric,
        ),
        encoding="utf-8",
    )
    (run_dir / "research.md").write_text(
        "# Research\n\nNo research recorded yet.\n",
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
    (run_dir / "review.md").write_text(
        "# Review\n\nReview has not run yet.\n",
        encoding="utf-8",
    )
    (run_dir / "memory.md").write_text(
        render_run_memory_snapshot(project_dir, run_id),
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
    updated_config = dict(config)
    updated_config["current_run_id"] = run_id
    updated_config["updated_at"] = now
    persist_project_config(project_dir, config_path, updated_config)

    return RunResult(
        project_dir=project_dir,
        config_path=config_path,
        run_dir=run_dir,
        run_json_path=run_dir / "run.json",
        config=updated_config,
        run=run_data,
    )


def attempt_limit(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 1


def attempt_timeout(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 540


def attempt_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attempts = run.get("attempts", [])
    if not isinstance(raw_attempts, list):
        return []
    return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]


def command_for_adapter(adapter: str, adapter_args: list[str]) -> list[str]:
    if adapter == "local-adapter-fixture":
        if not adapter_args:
            raise ValueError("local-adapter-fixture requires a command after --")
        return adapter_args
    command = AGENT_COMMANDS.get(adapter)
    if command is None:
        raise ValueError(f"unsupported adapter: {adapter}")
    return [command, *adapter_args]


def command_for_readonly_stage(
    *,
    adapter: str,
    adapter_args: list[str],
    workspace_dir: Path,
) -> list[str]:
    if adapter == "local-adapter-fixture":
        return command_for_adapter(adapter, adapter_args)
    if adapter == "codex":
        args = list(adapter_args)
        if not args:
            args = ["exec"]
        elif args[0] not in {"exec", "e"}:
            args = ["exec", *args]
        for flag in ("-s", "--sandbox"):
            if flag in args:
                index = args.index(flag)
                if index + 1 < len(args):
                    args[index + 1] = "read-only"
                break
        else:
            args[1:1] = ["-s", "read-only"]
        if "-C" not in args and "--cd" not in args:
            args[1:1] = ["--cd", str(workspace_dir)]
        if "--color" not in args:
            args[1:1] = ["--color", "never"]
        args = [value for value in args if value != "--json"]
        if "-" not in args:
            args.append("-")
        return ["codex", *args]
    if adapter == "claude-code" and not adapter_args:
        return ["claude", "-p", "--permission-mode", "plan"]
    if adapter == "kilo-code":
        return kilo_headless_run_command(
            adapter_args,
            default_agent=DEFAULT_READONLY_AGENT,
        )
    if not adapter_args:
        raise ValueError(f"read-only {adapter} requires non-interactive adapter arguments")
    return command_for_adapter(adapter, adapter_args)


def resolve_child_executable(command: list[str]) -> list[str]:
    """Return a command whose executable is an absolute, non-symlink file."""
    resolved = list(command)
    executable = Path(resolved[0])
    if not executable.is_absolute():
        found = shutil.which(resolved[0])
        if not found:
            raise FileNotFoundError(f"agent executable not found: {resolved[0]}")
        executable = Path(found)
    try:
        executable = executable.resolve(strict=True)
    except OSError as error:
        raise FileNotFoundError(f"agent executable not found: {resolved[0]}") from error
    if not executable.is_file():
        raise FileNotFoundError(f"agent executable is not a regular file: {resolved[0]}")
    resolved[0] = str(executable)
    return resolved


def execute_readonly_adapter_command(
    *,
    command: list[str],
    prompt: bytes,
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    resolved = resolve_child_executable(command)
    kilo_prompted = is_kilo_run_command(resolved)
    prepared_command = (
        kilo_command_with_prompt(resolved, decode_output(prompt)) if kilo_prompted else resolved
    )
    isolated = isolated_process_module()
    policy = isolated.load_policy()
    isolated.validate_command(prepared_command, project_dir, policy)
    environment = isolated.build_child_environment(
        isolated.select_allowed_parent_environment(os.environ, policy),
        policy,
    )
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    try:
        completed = subprocess.run(
            prepared_command,
            cwd=project_dir,
            env=environment,
            input=None if kilo_prompted else prompt,
            capture_output=True,
            timeout=bounded_timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, bytes) else b""
        stderr = error.stderr if isinstance(error.stderr, bytes) else b""
        return (
            {
                "completed": False,
                "returncode": None,
                "timed_out": True,
                "output_limit_exceeded": False,
            },
            stdout,
            stderr,
        )
    output_limit = int(policy["max_captured_output_bytes"])
    output_limit_exceeded = len(completed.stdout) + len(completed.stderr) > output_limit
    return (
        {
            "completed": not output_limit_exceeded,
            "returncode": completed.returncode,
            "timed_out": False,
            "output_limit_exceeded": output_limit_exceeded,
        },
        completed.stdout[:output_limit],
        completed.stderr[:output_limit],
    )


def command_for_attempt(
    *,
    adapter: str,
    adapter_args: list[str],
    workspace_dir: Path | None = None,
    run_dir: Path | None = None,
) -> list[str]:
    if adapter == "codex":
        args = list(adapter_args)
        if not args:
            args = ["exec"]
        elif args[0] not in {"exec", "e"}:
            args = ["exec", *args]
        if "-s" not in args and "--sandbox" not in args:
            args[1:1] = ["-s", "workspace-write"]
        if workspace_dir is not None and "-C" not in args and "--cd" not in args:
            args[1:1] = ["--cd", str(workspace_dir)]
        if run_dir is not None and "--add-dir" not in args:
            args[1:1] = ["--add-dir", str(run_dir)]
        if "--color" not in args:
            args[1:1] = ["--color", "never"]
        if "--json" not in args:
            args[1:1] = ["--json"]
        if "-" not in args:
            args.append("-")
        return ["codex", *args]
    if adapter == "kilo-code":
        return kilo_headless_run_command(
            adapter_args,
            default_agent=DEFAULT_IMPLEMENTATION_AGENT,
        )
    return command_for_adapter(adapter, adapter_args)


def render_adapter_prompt(
    *,
    run: dict[str, Any],
    contract: dict[str, Any],
    run_dir: Path,
    workspace_dir: Path,
    adapter: str,
    attempt_id: str,
) -> str:
    success_checks = contract.get("success_checks") or run.get("success_checks") or []
    if not isinstance(success_checks, list):
        success_checks = []
    allowed_tools = contract.get("allowed_tools")
    if not isinstance(allowed_tools, list):
        allowed_tools = []
    pack_contract = run.get("pack_contract", {})
    skills = []
    if isinstance(pack_contract, dict) and isinstance(pack_contract.get("skills"), list):
        skills = [str(skill) for skill in pack_contract["skills"]]
    limits = run.get("limits", {}) if isinstance(run.get("limits"), dict) else {}
    agent = pack_agent_for_stage(run, "implementation")
    permission = pack_permission_for_agent(run, agent)
    lines = [
        "# LoopForge Adapter Attempt",
        "",
        "You are executing one bounded LoopForge implementation attempt.",
        "Do not stop at analysis: make the requested code changes when feasible.",
        "",
        "## Paths",
        "",
        f"- Run directory: {run_dir}",
        f"- Workspace directory: {workspace_dir}",
        f"- Project control checkout: {run.get('project_root')}",
        f"- Attempt: {attempt_id}",
        f"- Adapter: {adapter}",
        f"- Agent: {agent.get('id') if agent else 'developer'}",
        f"- Permission set: {agent.get('permission_set') if agent else 'workspace-write'}",
        "",
        "Read these run artifacts before editing:",
        f"- {run_dir / 'task.md'}",
        f"- {run_dir / 'loop.md'}",
        f"- {run_dir / 'memory.md'}",
        f"- {run_dir / 'scratch.md'}",
        "",
        "Make code changes only in the workspace directory unless the run contract says otherwise.",
        "Preserve unrelated working-tree changes.",
        "Do not publish, push, deploy, delete unrelated files, expose secrets, "
        "or use hidden network effects.",
        "",
        "## Objective",
        "",
        str(run.get("task") or "").strip(),
        "",
        "## Success Checks",
        "",
    ]
    if success_checks:
        lines.extend(f"- {check}" for check in success_checks)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Allowed Tools", ""])
    if allowed_tools:
        lines.extend(f"- {tool}" for tool in allowed_tools)
    else:
        lines.append("- Use only local deterministic project tools.")
    lines.extend(["", "## Pack Skills", ""])
    lines.extend(f"- {skill}" for skill in skills) if skills else lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Limits",
            "",
            f"- Max attempts: {limits.get('max_attempts', 'unknown')}",
            f"- Timeout seconds: {limits.get('timeout_seconds', 'unknown')}",
            "",
            "## Required Finish",
            "",
            "Run the relevant deterministic checks from the success checks when possible.",
            "Leave the workspace with the implementation changes present for `loopforge verify`.",
            "Summarize what changed and any checks run.",
            "",
        ]
    )
    if permission is not None:
        lines.extend(
            [
                "",
                "## Permission Boundary",
                "",
                json.dumps(permission, indent=2, sort_keys=True),
            ]
        )
    agent_prompt = pack_agent_prompt(agent)
    if agent_prompt:
        lines.extend(["", "## Pack Agent Instructions", "", agent_prompt.strip()])
    return "\n".join(lines)


def session_hash(seed: dict[str, Any], label: str) -> str:
    encoded = json.dumps({"label": label, **seed}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_session_for(run: dict[str, Any], adapter: str, workspace_dir: Path) -> dict[str, Any]:
    seed = {
        "base_commit": run.get("base_commit"),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "adapter": adapter,
        "workspace": str(workspace_dir.resolve()),
    }
    return {
        "risk": "low",
        "base_commit": run.get("base_commit"),
        "workspace": str(workspace_dir.resolve()),
        "runner_id": adapter,
        "preflight_sha256": session_hash(seed, "preflight"),
        "start_authorization_receipt_sha256": session_hash(seed, "start-authorization"),
    }


def decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return str(path)


def workspace_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in project_dir.rglob("*"):
        if ".git" in path.parts:
            continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(project_dir).as_posix()
        except ValueError:
            relative = str(path)
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def workspace_snapshot_changes(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changes: list[str] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            changes.append(f"A {name}")
        elif name not in after:
            changes.append(f"D {name}")
        elif before[name] != after[name]:
            changes.append(f"M {name}")
    return changes


def git_status_entries(project_dir: Path) -> list[str] | None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def pack_workflow_stage(run: dict[str, Any], stage: str) -> dict[str, Any] | None:
    contract = run.get("pack_contract", {})
    workflow = contract.get("workflow", []) if isinstance(contract, dict) else []
    if not isinstance(workflow, list):
        return None
    for item in workflow:
        if isinstance(item, dict) and item.get("id") == stage:
            return item
    return None


def pack_agent_for_stage(run: dict[str, Any], stage: str) -> dict[str, Any] | None:
    workflow_stage = pack_workflow_stage(run, stage)
    actor = workflow_stage.get("actor", {}) if workflow_stage is not None else {}
    if not isinstance(actor, dict) or actor.get("type") != "agent":
        return None
    agent_id = str(actor.get("id") or "")
    contract = run.get("pack_contract", {})
    agents = contract.get("agents", []) if isinstance(contract, dict) else []
    if not isinstance(agents, list):
        return None
    for agent in agents:
        if isinstance(agent, dict) and agent.get("id") == agent_id:
            return agent
    return None


def pack_permission_for_agent(
    run: dict[str, Any],
    agent: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if agent is None:
        return None
    contract = run.get("pack_contract", {})
    permission_sets = contract.get("permission_sets", {}) if isinstance(contract, dict) else {}
    if not isinstance(permission_sets, dict):
        return None
    value = permission_sets.get(agent.get("permission_set"))
    return value if isinstance(value, dict) else None


def pack_agent_prompt(agent: dict[str, Any] | None) -> str:
    value = agent.get("prompt_path") if agent is not None else None
    if not isinstance(value, str) or not value:
        return ""
    path = Path(value)
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeError):
        return ""


def next_readonly_stage(run: dict[str, Any]) -> str | None:
    normalized = normalize_run_workflow_state(run)
    approval = normalized.get("approval", {})
    approved = bool(approval.get("approved")) if isinstance(approval, dict) else False
    if not approved:
        return None
    statuses = normalized.get("stage_statuses", {})
    if not isinstance(statuses, dict):
        return None
    if statuses.get("task") != "approved":
        return None
    if statuses.get("research") != "complete":
        return "research"
    if statuses.get("plan") not in {"awaiting_approval", "approved", "complete"}:
        return "plan"
    verification = normalized.get("verification", {})
    verification_passed = (
        statuses.get("verification") == "complete"
        and isinstance(verification, dict)
        and verification.get("status") == "passed"
    )
    if verification_passed and statuses.get("review") not in {"complete", "approved"}:
        return "review"
    return None


def readonly_stage_prerequisite_blockers(run: dict[str, Any], stage: str) -> list[str]:
    normalized = normalize_run_workflow_state(run)
    statuses = normalized.get("stage_statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}
    approval = normalized.get("approval", {})
    approved = bool(approval.get("approved")) if isinstance(approval, dict) else False
    blockers: list[str] = []
    task_approved = statuses.get("task") == "approved"
    if stage == "research" and (not approved or not task_approved):
        blockers.append("research requires an approved task before adapter execution.")
    task_validation = normalized.get("task_validation", {})
    if stage == "research" and isinstance(task_validation, dict) and task_validation.get(
        "status"
    ) not in {None, "valid"}:
        blockers.append("research requires a complete task definition and objective success check.")
    if stage == "plan":
        if not approved or not task_approved:
            blockers.append("plan requires an approved task before adapter execution.")
        if statuses.get("research") != "complete":
            blockers.append("plan requires completed research before adapter execution.")
    if stage == "review":
        verification = normalized.get("verification", {})
        if (
            statuses.get("verification") != "complete"
            or not isinstance(verification, dict)
            or verification.get("status") != "passed"
        ):
            blockers.append("review requires passed deterministic verification.")
    if stage not in READONLY_WORKFLOW_STAGES:
        blockers.append(f"unsupported read-only stage: {stage}")
    return blockers


def render_stage_prompt(
    *,
    stage: str,
    run: dict[str, Any],
    run_dir: Path,
    workspace_dir: Path,
    adapter: str,
) -> str:
    artifact = f"{stage}.md"
    sections = REQUIRED_READONLY_STAGE_SECTIONS.get(stage, ())
    agent = pack_agent_for_stage(run, stage)
    permission = pack_permission_for_agent(run, agent)
    lines = [
        f"# LoopForge {stage.title()} Stage",
        "",
        "Produce only the requested portable Markdown artifact on stdout.",
        "Do not modify the workspace. Read project files and run artifacts only.",
        "",
        "## Paths",
        "",
        f"- Run directory: {run_dir}",
        f"- Workspace directory: {workspace_dir}",
        f"- Artifact: {artifact}",
        f"- Adapter: {adapter}",
        f"- Agent: {agent.get('id') if agent else stage}",
        f"- Permission set: {agent.get('permission_set') if agent else 'read-only'}",
        "",
        "## Objective",
        "",
        str(run.get("task") or "").strip(),
        "",
        "## Required Artifact",
        "",
        "- YAML frontmatter with artifact_version, artifact, issue, base_commit, and status.",
        f"- artifact: {stage}",
        f"- status: {READONLY_STAGE_SUCCESS[stage][0]}",
        "",
        "## Required Sections",
        "",
    ]
    lines.extend(f"- {section}" for section in sections)
    lines.append("")
    if permission is not None:
        lines.extend(
            [
                "## Permission Boundary",
                "",
                json.dumps(permission, indent=2, sort_keys=True),
                "",
            ]
        )
    agent_prompt = pack_agent_prompt(agent)
    if agent_prompt:
        lines.extend(["## Pack Agent Instructions", "", agent_prompt.strip(), ""])
    return "\n".join(lines)


def validate_readonly_stage_artifact(stage: str, markdown: str) -> list[str]:
    blockers: list[str] = []
    lines = markdown.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---" or "---" not in [
        line.strip() for line in lines[1:]
    ]:
        blockers.append(f"{stage}.md must start with YAML frontmatter.")
        return blockers
    frontmatter = parse_frontmatter(markdown)
    if frontmatter.get("artifact") != stage:
        blockers.append(f"{stage}.md frontmatter must include artifact: {stage}.")
    if not frontmatter.get("artifact_version"):
        blockers.append(f"{stage}.md frontmatter must include artifact_version.")
    if not frontmatter.get("issue"):
        blockers.append(f"{stage}.md frontmatter must include issue.")
    if not frontmatter.get("base_commit"):
        blockers.append(f"{stage}.md frontmatter must include base_commit.")
    expected_status = READONLY_STAGE_SUCCESS[stage][0]
    if frontmatter.get("status") != expected_status:
        blockers.append(f"{stage}.md frontmatter must include status: {expected_status}.")
    sections = markdown_sections(markdown)
    missing_sections = [
        section
        for section in REQUIRED_READONLY_STAGE_SECTIONS[stage]
        if not section_text(sections, section)
    ]
    if missing_sections:
        blockers.append(
            f"{stage}.md is missing required sections: {', '.join(missing_sections)}."
        )
    return blockers


def readonly_worktree_changes(
    *,
    before_snapshot: dict[str, tuple[int, int]],
    before_git: list[str] | None,
    after_snapshot: dict[str, tuple[int, int]],
    after_git: list[str] | None,
) -> list[str]:
    snapshot_changes = workspace_snapshot_changes(before_snapshot, after_snapshot)
    if before_git is not None and after_git is not None and before_git != after_git:
        return after_git or snapshot_changes or ["git status changed"]
    return snapshot_changes


def update_run_for_stage_blocker(
    *,
    project_dir: Path,
    run_json_path: Path,
    run: dict[str, Any],
    stage: str,
    blockers: list[str],
) -> dict[str, Any]:
    updated = normalize_run_workflow_state(run)
    updated["stage_statuses"][stage] = "blocked"
    updated["blockers"] = blockers
    updated["updated_at"] = utc_now()
    persist_run_json(project_dir, run_json_path, updated)
    return updated


def approve_plan(
    project_dir: Path,
    *,
    source: str = "local",
) -> StageResult:
    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="plan_approval",
            ok=False,
            message="Initialize LoopForge before approving a plan.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="plan_approval",
            ok=False,
            message="No current run is ready for plan approval.",
            blockers=status.blockers or [status.next_step],
        )

    run = normalize_run_workflow_state(status.run)
    statuses = run.get("stage_statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}
    blockers: list[str] = []
    if statuses.get("plan") != "awaiting_approval":
        blockers.append("plan approval requires a plan awaiting approval.")
    plan_path = status.run_dir / "plan.md"
    if not plan_path.exists():
        blockers.append("plan approval requires plan.md in the run directory.")
    if blockers:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="plan_approval",
            ok=False,
            message="LoopForge plan approval is blocked.",
            blockers=blockers,
            artifact_path=plan_path if plan_path.exists() else None,
        )

    updated = apply_plan_approval(run, source=source)
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="plan_approval",
        ok=True,
        message="LoopForge plan approved; implementation is ready.",
        blockers=[],
        artifact_path=plan_path,
    )


def approve_review(
    project_dir: Path,
    *,
    source: str = "local",
) -> StageResult:
    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="review_approval",
            ok=False,
            message="Initialize LoopForge before approving a review.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="review_approval",
            ok=False,
            message="No current run is ready for review approval.",
            blockers=status.blockers or [status.next_step],
        )

    run = normalize_run_workflow_state(status.run)
    statuses = run.get("stage_statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}
    blockers: list[str] = []
    if statuses.get("verification") != "complete":
        blockers.append("review approval requires completed deterministic verification.")
    verification = run.get("verification", {})
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        blockers.append("review approval requires passed deterministic verification.")
    if statuses.get("review") == "approved":
        blockers.append("review approval has already been recorded.")
    elif statuses.get("review") != "complete":
        blockers.append("review approval requires a completed read-only review.")
    verification_path = status.run_dir / "verification.md"
    if not verification_path.exists():
        blockers.append("review approval requires verification.md in the run directory.")
    review_path = status.run_dir / "review.md"
    if not review_path.exists():
        blockers.append("review approval requires review.md in the run directory.")
    if blockers:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="review_approval",
            ok=False,
            message="LoopForge review approval is blocked.",
            blockers=blockers,
            artifact_path=review_path if review_path.exists() else None,
        )

    updated = apply_review_approval(run, source=source)
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="review_approval",
        ok=True,
        message="LoopForge review approved; draft publication is now eligible.",
        blockers=[],
        artifact_path=review_path,
    )


def current_git_branch(project_dir: Path) -> str:
    state = DEFAULT_GIT_STATE_SERVICE.get(project_dir, allow_fallback=True)
    return state.branch or "HEAD"


def draft_publication_body(run: dict[str, Any], verification: dict[str, Any]) -> str:
    patch = verification.get("patch", {}) if isinstance(verification.get("patch"), dict) else {}
    checks_passed = verification.get("checks_passed", 0)
    checks_total = verification.get("checks_total", 0)
    lines = [
        f"# {run.get('task') or 'LoopForge run'}",
        "",
        "Draft PR prepared by LoopForge after explicit review approval.",
        "",
        "## Verification",
        "",
        f"- Status: {verification.get('status') or 'unknown'}",
        f"- Checks: {checks_passed}/{checks_total}",
        f"- Patch: {patch.get('path') or 'none'}",
        f"- Patch SHA-256: {patch.get('sha256') or 'none'}",
        "",
        "## Publication",
        "",
        "- Draft: true",
        "- Network: not performed",
    ]
    return "\n".join(lines) + "\n"


def prepare_draft_publication(project_dir: Path) -> StageResult:
    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="publication",
            ok=False,
            message="Initialize LoopForge before preparing draft publication.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="publication",
            ok=False,
            message="No current run is ready for draft publication.",
            blockers=status.blockers or [status.next_step],
        )

    run = normalize_run_workflow_state(status.run)
    statuses = run.get("stage_statuses", {})
    gates = run.get("human_gates", {})
    eligibility = run.get("publish_eligibility", {})
    verification = run.get("verification", {})
    if not isinstance(statuses, dict):
        statuses = {}
    if not isinstance(gates, dict):
        gates = {}
    if not isinstance(eligibility, dict):
        eligibility = {}
    if not isinstance(verification, dict):
        verification = {}
    review_gate = gates.get("review_approval")
    if not isinstance(review_gate, dict):
        review_gate = {}
    patch = verification.get("patch")
    if not isinstance(patch, dict):
        patch = {}

    blockers: list[str] = []
    if statuses.get("verification") != "complete" or verification.get("status") != "passed":
        blockers.append("draft publication requires passed deterministic verification.")
    if statuses.get("review") not in {"approved", "complete"} or review_gate.get("status") != "approved":
        blockers.append("draft publication requires explicit review approval.")
    if not bool(eligibility.get("eligible")) or eligibility.get("mode") != "draft":
        blockers.append("draft publication requires draft publish eligibility.")
    patch_path_value = patch.get("path")
    patch_path = status.run_dir / str(patch_path_value) if patch_path_value else None
    if not bool(patch.get("generated")) or patch.get("status") != "generated":
        blockers.append("draft publication requires a generated verification patch.")
    if patch_path is None or not patch_path.is_file():
        blockers.append("draft publication requires a retained verification patch.")
    if not isinstance(patch.get("sha256"), str) or not str(patch.get("sha256")).strip():
        blockers.append("draft publication requires a verification patch sha256.")
    base_commit = run.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        blockers.append("draft publication requires base_commit in run.json.")
    if blockers:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="publication",
            ok=False,
            message="LoopForge draft publication is blocked.",
            blockers=blockers,
        )

    publication_dir = status.run_dir / "artifacts" / "publication"
    publication_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = publication_dir / "draft-pr.json"
    relative_artifact_path = relative_to_run(status.run_dir, artifact_path)
    run_id = str(run.get("run_id") or "run")
    title = str(run.get("task") or "LoopForge run").strip() or "LoopForge run"
    payload = {
        "artifact_version": 1,
        "artifact": "draft_pr",
        "kind": "draft_pr_publication",
        "draft": True,
        "no_network": True,
        "network": {
            "performed": False,
            "reason": "LoopForge prepared a deterministic local draft artifact only.",
        },
        "publisher": "local-draft-artifact",
        "run_id": run_id,
        "task": run.get("task"),
        "title": f"LoopForge: {title}",
        "body": draft_publication_body(run, verification),
        "branch": f"loopforge/{run_id}",
        "base": current_git_branch(status.project_dir),
        "head_branch": f"loopforge/{run_id}",
        "base_branch": current_git_branch(status.project_dir),
        "base_commit": base_commit,
        "patch": {
            "path": patch.get("path"),
            "sha256": patch.get("sha256"),
            "size_bytes": patch.get("size_bytes", 0),
        },
        "verification": {
            "status": verification.get("status"),
            "patch": {
                "path": patch.get("path"),
                "sha256": patch.get("sha256"),
                "size_bytes": patch.get("size_bytes", 0),
            },
        },
        "source": {
            "run_id": run.get("run_id"),
            "task": run.get("task"),
            "review_status": review_gate.get("status"),
            "verification_status": verification.get("status"),
        },
    }
    write_json_atomic(artifact_path, payload)
    updated = apply_draft_publication_prepared(
        run,
        artifact_path=relative_artifact_path,
    )
    updated.setdefault("artifacts", {})["draft_publication"] = str(artifact_path)
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="publication",
        ok=True,
        message="LoopForge draft PR artifact prepared without network publication.",
        blockers=[],
        artifact_path=artifact_path,
    )


def execute_readonly_stage(
    project_dir: Path,
    *,
    stage: str,
    adapter: str,
    adapter_args: list[str] | None = None,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> StageResult:
    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage=stage,
            ok=False,
            message="Initialize LoopForge before running a read-only stage.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage=stage,
            ok=False,
            message="No current run is ready for a read-only stage.",
            blockers=status.blockers or [status.next_step],
        )
    run = normalize_run_workflow_state(status.run)
    run_json_path = status.run_json_path or (status.run_dir / "run.json")
    blockers = readonly_stage_prerequisite_blockers(run, stage)
    if blockers:
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    available_stage = next_readonly_stage(run)
    if available_stage != stage:
        blockers = [f"{stage} is not the next available read-only stage."]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    workspace_dir = run_workspace_path(run, status.project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        blockers = [f"run workspace is not available: {workspace_dir}"]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )

    stage_dir = status.run_dir / "artifacts" / "stages" / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    emit_operation_event(
        operation_callback,
        "stage_started",
        f"Starting read-only {stage} stage.",
        artifact=str(stage_dir),
    )
    prompt = render_stage_prompt(
        stage=stage,
        run=run,
        run_dir=status.run_dir,
        workspace_dir=workspace_dir,
        adapter=adapter,
    )
    (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    before_snapshot = workspace_snapshot(workspace_dir)
    before_git = git_status_entries(workspace_dir)
    if cancel_event is not None and cancel_event.is_set():
        blockers = [f"read-only {stage} stage was interrupted before adapter execution."]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        emit_operation_event(
            operation_callback,
            "cancelled",
            blockers[0],
            artifact=str(stage_dir / "prompt.md"),
            status="cancelled",
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage was interrupted.",
            blockers=blockers,
        )
    try:
        command = command_for_readonly_stage(
            adapter=adapter,
            adapter_args=adapter_args or [],
            workspace_dir=workspace_dir,
        )
        if adapter == "local-adapter-fixture":
            child, stdout, stderr = execute_fixture_command(
                command=command,
                project_dir=workspace_dir,
                timeout_seconds=attempt_timeout(run, status.loop_contract or {}),
            )
        else:
            child, stdout, stderr = execute_readonly_adapter_command(
                command=command,
                prompt=prompt.encode("utf-8"),
                project_dir=workspace_dir,
                timeout_seconds=attempt_timeout(run, status.loop_contract or {}),
            )
    except (OSError, RuntimeError, ValueError) as error:
        blockers = [f"read-only {stage} adapter execution could not start: {error}"]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    after_snapshot = workspace_snapshot(workspace_dir)
    after_git = git_status_entries(workspace_dir)
    write_bytes(stage_dir / "adapter.stdout", stdout)
    write_bytes(stage_dir / "adapter.stderr", stderr)
    worktree_changes = readonly_worktree_changes(
        before_snapshot=before_snapshot,
        before_git=before_git,
        after_snapshot=after_snapshot,
        after_git=after_git,
    )
    returncode = child.get("returncode")
    if cancel_event is not None and cancel_event.is_set():
        blockers = [f"read-only {stage} stage was interrupted; its evidence was retained."]
    elif not bool(child.get("completed")):
        blockers = [f"read-only {stage} adapter timed out."]
    elif returncode != 0:
        blockers = [f"read-only {stage} adapter failed with return code {returncode}."]
    else:
        blockers = []
    if worktree_changes:
        blockers.append(
            f"read-only {stage} stage changed the worktree: "
            + "; ".join(worktree_changes[:10])
        )
    try:
        artifact_text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        artifact_text = ""
        blockers.append(f"{stage}.md stdout must be valid UTF-8.")
    if not artifact_text:
        blockers.append(f"{stage}.md stdout was empty.")
    if artifact_text:
        blockers.extend(validate_readonly_stage_artifact(stage, artifact_text))
    if blockers:
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        emit_operation_event(
            operation_callback,
            "cancelled" if cancel_event is not None and cancel_event.is_set() else "blocked",
            f"Read-only {stage} stage is blocked.",
            artifact=str(stage_dir),
            status="cancelled" if cancel_event is not None and cancel_event.is_set() else "blocked",
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )

    artifact_path = status.run_dir / f"{stage}.md"
    artifact_path.write_bytes(stdout)
    updated = normalize_run_workflow_state(run)
    stage_status, current_stage = READONLY_STAGE_SUCCESS[stage]
    updated["stage_statuses"][stage] = stage_status
    updated["current_stage"] = current_stage
    if stage == "plan":
        updated["human_gates"]["plan_approval"] = {
            **initial_workflow_state()["human_gates"]["plan_approval"],
            "status": "pending",
        }
    updated["blockers"] = []
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, run_json_path, updated)
    emit_operation_event(
        operation_callback,
        "completed",
        f"Read-only {stage} stage completed.",
        artifact=str(artifact_path),
        status="completed",
    )
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage=stage,
        ok=True,
        message=f"LoopForge {stage} stage completed.",
        blockers=[],
        artifact_path=artifact_path,
    )


def append_progress(run_dir: Path, attempt: dict[str, Any]) -> None:
    progress_path = run_dir / "progress.md"
    lines = [
        "",
        f"## Attempt {attempt['number']}: {attempt['adapter']}",
        "",
        f"- Started: {attempt['started_at']}",
        f"- Finished: {attempt['finished_at']}",
        f"- Status: {attempt['status']}",
        f"- Summary: {attempt['summary']}",
        f"- Workspace changed: {'yes' if attempt['workspace_changed'] else 'no'}",
        f"- Workspace: {attempt.get('workspace') or 'unknown'}",
        f"- Prompt: {attempt.get('prompt_path') or 'none'}",
        f"- Stdout: {attempt['stdout_path']}",
        f"- Stderr: {attempt['stderr_path']}",
        f"- Result: {attempt['result_path']}",
    ]
    changes = attempt.get("workspace_changes", [])
    if changes:
        lines.append("- Workspace changes:")
        for change in changes[:20]:
            lines.append(f"  - {change}")
    if len(changes) > 20:
        lines.append(f"  - ... {len(changes) - 20} more")
    lines.append("")
    progress_path.write_text(
        progress_path.read_text(encoding="utf-8") + "\n".join(lines),
        encoding="utf-8",
    )


def synthetic_adapter_result(
    *,
    session: dict[str, Any],
    status: str,
    summary: str,
    workspace_changed: bool,
) -> dict[str, Any]:
    return {
        "result_version": 1,
        "purpose": "implementation_session_result",
        "mode": "untrusted-runner-output",
        "status": status,
        **session,
        "summary": summary[:1000] or "Adapter execution did not produce a summary.",
        "workspace_changed": workspace_changed,
        "patch_generated": False,
        "deterministic_checks_run": False,
        "publication_requested": False,
        "network_requested": False,
        "next_action": "deterministic_patch_generation"
        if status == "completed"
        else "human_review",
    }


def run_with_isolated_process(command: list[str], cwd: Path, timeout_seconds: int) -> dict[str, Any]:
    isolated_process = isolated_process_module()
    policy = isolated_process.load_policy()
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    return isolated_process.run(
        command,
        cwd,
        isolated_process.select_allowed_parent_environment(os.environ, policy),
        policy,
        timeout_seconds=bounded_timeout,
    )


OperationCallback = Callable[[dict[str, Any]], None]


def emit_operation_event(
    callback: OperationCallback | None,
    kind: str,
    message: str,
    **details: Any,
) -> None:
    """Publish factual work boundaries without making the engine UI-aware."""

    if callback is not None:
        callback({"kind": kind, "message": message, **details})


def run_streaming_process(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    *,
    output_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    isolated_process = isolated_process_module()
    policy = isolated_process.load_policy()
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    env = isolated_process.build_child_environment(
        isolated_process.select_allowed_parent_environment(os.environ, policy),
        policy,
    )
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def read_available(source) -> bytes:  # type: ignore[no-untyped-def]
        if hasattr(source, "read1"):
            return source.read1(4096)
        return source.read(1)

    def pump(source, target, buffer: bytearray) -> None:  # type: ignore[no-untyped-def]
        try:
            while True:
                chunk = read_available(source)
                if not chunk:
                    break
                buffer.extend(chunk)
                if output_callback is not None:
                    emit_operation_event(
                        output_callback,
                        "adapter_output",
                        decode_output(chunk).strip() or "Adapter produced output.",
                    )
                else:
                    target.write(chunk)
                    target.flush()
        finally:
            source.close()

    stdout_thread = threading.Thread(
        target=pump,
        args=(process.stdout, sys.stdout.buffer, stdout_buffer),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=pump,
        args=(process.stderr, sys.stderr.buffer, stderr_buffer),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    interrupted = False
    try:
        deadline = time.monotonic() + bounded_timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                interrupted = True
                process.terminate()
                try:
                    returncode = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    returncode = process.wait()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, bounded_timeout)
            try:
                returncode = process.wait(timeout=min(remaining, 0.1))
                break
            except subprocess.TimeoutExpired:
                continue
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    except KeyboardInterrupt:
        interrupted = True
        process.terminate()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if interrupted and cancel_event is None:
        raise KeyboardInterrupt
    return {
        "completed": not timed_out,
        "returncode": returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "output_limit_exceeded": False,
        "stdout": bytes(stdout_buffer),
        "stderr": bytes(stderr_buffer),
    }


def adapter_protocol_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    workspace_dir: Path,
    stdin_file: Path | None,
    result_output: Path | None,
) -> list[str]:
    protocol = [
        usable_python_executable(),
        "-m",
        "loopforge.adapters.local_implementation_adapter",
        "--expected-session",
        str(expected_session_path),
        "--workspace",
        str(workspace_dir),
    ]
    if stdin_file is not None:
        protocol.extend(["--stdin-file", str(stdin_file)])
    if result_output is not None:
        protocol.extend(["--result-output", str(result_output)])
    protocol.extend(["--", *command])
    return protocol


def execute_fixture_command(
    *,
    command: list[str],
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    resolved_command = resolve_child_executable(command)
    child = run_with_isolated_process(resolved_command, project_dir, timeout_seconds)
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def execute_adapter_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    workspace_dir: Path,
    stdin_file: Path,
    result_output: Path,
    timeout_seconds: int,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[dict[str, Any], bytes, bytes]:
    protocol_command = adapter_protocol_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=stdin_file,
        result_output=result_output,
    )
    child = run_streaming_process(
        protocol_command,
        repository_root(),
        min(timeout_seconds + 5, 600),
        output_callback=operation_callback,
        cancel_event=cancel_event,
    )
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def parse_adapter_result(stdout: bytes) -> dict[str, Any] | None:
    if not stdout.strip():
        return None
    try:
        parsed = json.loads(decode_output(stdout))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_adapter_result_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def execute_attempt(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    contract: dict[str, Any],
    adapter: str,
    adapter_args: list[str],
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter}")
    workspace_dir = run_workspace_path(run, project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        raise ValueError(f"run workspace is not available: {workspace_dir}")
    command = command_for_attempt(
        adapter=adapter,
        adapter_args=adapter_args,
        workspace_dir=workspace_dir,
        run_dir=run_dir,
    )
    attempts = attempt_records(run)
    number = len(attempts) + 1
    attempt_id = f"attempt-{number:03d}"
    attempt_dir = run_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)

    emit_operation_event(
        operation_callback,
        "attempt_started",
        f"Starting {adapter} implementation attempt {attempt_id}.",
        artifact=str(attempt_dir),
    )

    started = utc_now()
    prompt_path = attempt_dir / "adapter-prompt.md"
    prompt_path.write_text(
        render_adapter_prompt(
            run=run,
            contract=contract,
            run_dir=run_dir,
            workspace_dir=workspace_dir,
            adapter=adapter,
            attempt_id=attempt_id,
        ),
        encoding="utf-8",
    )
    session = expected_session_for(run, adapter, workspace_dir)
    expected_session_path = attempt_dir / "expected-session.json"
    write_json_atomic(expected_session_path, session)
    before_snapshot = workspace_snapshot(workspace_dir)
    before_git = git_status_entries(workspace_dir)
    timeout_seconds = attempt_timeout(run, contract)

    if adapter == "local-adapter-fixture":
        child, stdout, stderr = execute_fixture_command(
            command=command,
            project_dir=workspace_dir,
            timeout_seconds=timeout_seconds,
        )
        result = None
    else:
        result_path = attempt_dir / "result.json"
        child, stdout, stderr = execute_adapter_command(
            adapter=adapter,
            command=command,
            expected_session_path=expected_session_path,
            workspace_dir=workspace_dir,
            stdin_file=prompt_path,
            result_output=result_path,
            timeout_seconds=timeout_seconds,
            operation_callback=operation_callback,
            cancel_event=cancel_event,
        )
        result = parse_adapter_result_file(result_path) or parse_adapter_result(stdout)

    finished = utc_now()
    after_snapshot = workspace_snapshot(workspace_dir)
    after_git = git_status_entries(workspace_dir)
    workspace_changes = (
        after_git
        if after_git is not None
        else workspace_snapshot_changes(before_snapshot, after_snapshot)
    )
    snapshot_changed = before_snapshot != after_snapshot
    returncode = child.get("returncode")
    completed = bool(child.get("completed")) and returncode == 0
    timed_out = bool(child.get("timed_out"))
    output_limit_exceeded = bool(child.get("output_limit_exceeded"))
    interrupted = bool(child.get("interrupted"))

    if adapter == "local-adapter-fixture":
        status = "completed" if completed and snapshot_changed else "blocked"
        if interrupted:
            status = "interrupted"
            summary = "Fixture command was interrupted."
        elif timed_out:
            status = "failed"
            summary = "Fixture command timed out."
        elif output_limit_exceeded:
            status = "failed"
            summary = "Fixture command exceeded the output limit."
        elif not completed:
            status = "failed"
            summary = f"Fixture command failed with return code {returncode}."
        elif snapshot_changed:
            summary = "Fixture command completed and changed the workspace."
        else:
            summary = "Fixture command completed without workspace changes."
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=summary,
            workspace_changed=snapshot_changed,
        )
    elif interrupted:
        status = "interrupted"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary="Adapter execution was interrupted.",
            workspace_changed=snapshot_changed,
        )
    elif result is None:
        status = "failed"
        stderr_text = decode_output(stderr).strip()
        stdout_text = decode_output(stdout).strip()
        detail = stderr_text or stdout_text or "adapter produced no protocol result"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=f"Adapter failed before producing a result: {detail}"[:1000],
            workspace_changed=snapshot_changed,
        )
    else:
        status = str(result.get("status", "failed"))
        if "workspace_changed" not in result:
            result["workspace_changed"] = snapshot_changed
        if "summary" not in result:
            result["summary"] = f"Adapter reported {status}."

    profile_stop_reasons: list[str] = []
    if normalize_profile(run.get("profile")) == "autonomous":
        profile_stop_reasons = adapter_result_stop_reasons(result)
        if profile_stop_reasons and status == "completed":
            status = "blocked"
            result["status"] = status
            result["summary"] = (
                str(result.get("summary", "")).rstrip()
                + " Autonomy profile stopped for human review."
            ).strip()

    stdout_path = attempt_dir / "adapter.stdout"
    stderr_path = attempt_dir / "adapter.stderr"
    result_path = attempt_dir / "result.json"
    write_bytes(stdout_path, stdout)
    write_bytes(stderr_path, stderr)
    write_json_atomic(result_path, result)

    attempt = {
        "id": attempt_id,
        "number": number,
        "adapter": adapter,
        "command": command,
        "started_at": started,
        "finished_at": finished,
        "status": status,
        "summary": str(result.get("summary", "")),
        "workspace_changed": bool(result.get("workspace_changed", snapshot_changed)),
        "workspace_changes": workspace_changes,
        "returncode": returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "output_limit_exceeded": output_limit_exceeded,
        "profile_stop_reasons": profile_stop_reasons,
        "publication_requested": bool(result.get("publication_requested", False)),
        "network_requested": bool(result.get("network_requested", False)),
        "attempt_dir": str(attempt_dir),
        "workspace": str(workspace_dir),
        "expected_session_path": relative_to_run(run_dir, expected_session_path),
        "prompt_path": relative_to_run(run_dir, prompt_path),
        "stdout_path": relative_to_run(run_dir, stdout_path),
        "stderr_path": relative_to_run(run_dir, stderr_path),
        "result_path": relative_to_run(run_dir, result_path),
        "before_git_status": before_git,
        "after_git_status": after_git,
    }
    write_json_atomic(attempt_dir / "attempt.json", attempt)
    append_progress(run_dir, attempt)
    emit_operation_event(
        operation_callback,
        "attempt_finished",
        f"Implementation attempt {attempt_id} {status}.",
        artifact=str(attempt_dir / "attempt.json"),
        status=status,
    )
    return attempt


def update_run_after_attempt(
    *,
    project_dir: Path,
    run_json_path: Path,
    run: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(run)
    attempts = attempt_records(updated)
    attempts.append(attempt)
    updated["attempts"] = attempts
    updated["attempt_count"] = len(attempts)
    updated["last_attempt"] = attempt
    updated["updated_at"] = utc_now()
    if attempt["status"] == "completed":
        updated["status"] = READY_FOR_VERIFICATION
        updated["blockers"] = []
        updated = normalize_run_workflow_state(updated)
        updated["stage_statuses"]["implementation"] = "complete"
        updated["current_stage"] = "implementation_complete"
    else:
        updated["status"] = ADAPTER_BLOCKED
        blockers = [
            f"attempt {attempt['id']} with adapter {attempt['adapter']} "
            f"reported {attempt['status']}: {attempt['summary']}"
        ]
        for reason in attempt.get("profile_stop_reasons", []):
            blockers.append(str(reason))
        updated["blockers"] = blockers
        updated = normalize_run_workflow_state(updated)
        updated["stage_statuses"]["implementation"] = "blocked"
        updated["current_stage"] = "implementation_blocked"
    persist_run_json(project_dir, run_json_path, updated)
    return updated


def pack_check_paths(project_dir: Path, pack: str) -> list[Path]:
    return _pack_registry(project_dir).check_paths(pack)


def load_pack_checks(project_dir: Path, pack: str) -> dict[str, Any]:
    return _pack_registry(project_dir).load_checks(pack)


def expand_check_value(
    value: str,
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> str:
    replacements = {
        "{python}": usable_python_executable(),
        "{repo}": str(project_dir),
        "{run_dir}": str(run_dir),
        "{patch}": str(patch_path or ""),
    }
    expanded = value
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    return expanded


def run_pack_check(
    check: dict[str, Any],
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> dict[str, Any]:
    command = [
        expand_check_value(
            part,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
        for part in check["command"]
    ]
    env = os.environ.copy()
    for key, value in check.get("env", {}).items():
        env[key] = expand_check_value(
            value,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
    started = utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(check["timeout_seconds"]),
            check=False,
        )
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "timed_out",
            "returncode": None,
            "stdout": (error.stdout or "")[-4000:]
            if isinstance(error.stdout, str)
            else "",
            "stderr": (error.stderr or "")[-4000:]
            if isinstance(error.stderr, str)
            else "",
            "timed_out": True,
        }
    except OSError as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "timed_out": False,
        }


def run_json_check(command: list[str], cwd: Path, timeout: int = 60) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": payload,
    }


def pack_protected_path_paths(project_dir: Path, pack: str) -> list[Path]:
    return _pack_registry(project_dir).protected_path_paths(pack)


def load_pack_protected_paths(project_dir: Path, pack: str) -> dict[str, Any]:
    return _pack_registry(project_dir).load_protected_paths(pack)


def merged_risk_policy_path(
    *,
    project_dir: Path,
    run_dir: Path,
    pack: str,
) -> tuple[Path, list[str]]:
    base = read_json(default_risk_policy())
    protected = load_pack_protected_paths(project_dir, pack)
    sources = [str(default_risk_policy())]
    if protected["source"]:
        sources.append(str(protected["source"]))
    high_patterns = normalize_unique_strings(
        [
            *[str(pattern) for pattern in base.get("high_path_patterns", [])],
            *[str(pattern) for pattern in protected.get("high_path_patterns", [])],
        ]
    )
    medium_patterns = normalize_unique_strings(
        [
            *[str(pattern) for pattern in base.get("medium_path_patterns", [])],
            *[str(pattern) for pattern in protected.get("medium_path_patterns", [])],
        ]
    )
    merged = dict(base)
    merged["high_path_patterns"] = high_patterns
    merged["medium_path_patterns"] = medium_patterns
    policy_path = run_dir / "artifacts" / "policies" / "risk-rules.merged.json"
    write_json_atomic(policy_path, merged)
    return policy_path, sources


def verification_failure_parts(verification: dict[str, Any]) -> list[Any]:
    parts: list[Any] = []
    patch = verification.get("patch", {})
    if isinstance(patch, dict) and patch.get("status") == "failed":
        parts.append({"patch_error": patch.get("error")})
    diff_policy = verification.get("diff_policy", {})
    if isinstance(diff_policy, dict) and diff_policy.get("allowed") is False:
        violations = diff_policy.get("violations", [])
        rules = []
        if isinstance(violations, list):
            for violation in violations:
                if isinstance(violation, dict):
                    rules.append(violation.get("rule"))
        parts.append({"policy_violations": sorted(str(rule) for rule in rules if rule)})
    checks = verification.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("status") != "passed":
                parts.append(
                    {
                        "check": check.get("name"),
                        "status": check.get("status"),
                        "returncode": check.get("returncode"),
                    }
                )
    return parts


def failure_signature(verification: dict[str, Any]) -> str | None:
    parts = verification_failure_parts(verification)
    if not parts:
        return None
    encoded = json.dumps(parts, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_verification_markdown(verification: dict[str, Any]) -> str:
    lines = [
        "# Verification",
        "",
        f"- Started: {verification['started_at']}",
        f"- Finished: {verification['finished_at']}",
        f"- Status: {verification['status']}",
        f"- Patch generated: {'yes' if verification['patch'].get('generated') else 'no'}",
        f"- Patch: {verification['patch'].get('path') or 'none'}",
        f"- Patch size bytes: {verification['patch'].get('size_bytes', 0)}",
        f"- Diff policy allowed: {str(verification['diff_policy'].get('allowed')).lower()}",
        f"- Risk: {verification['risk'].get('risk') or 'unknown'}",
        f"- Risk policy: {verification['risk'].get('policy') or 'none'}",
        f"- Pack checks: {verification['checks_passed']}/{verification['checks_total']}",
        "",
        "## Diff Policy",
        "",
    ]
    violations = verification["diff_policy"].get("violations", [])
    if violations:
        for violation in violations:
            if isinstance(violation, dict):
                lines.append(
                    f"- {violation.get('rule', 'violation')}: "
                    f"{violation.get('message', '')}"
                )
            else:
                lines.append(f"- {violation}")
    else:
        lines.append("- No deterministic policy violations recorded.")
    lines.extend(["", "## Risk", ""])
    reasons = verification["risk"].get("reasons", [])
    if reasons:
        for reason in reasons:
            if isinstance(reason, dict):
                lines.append(
                    f"- {reason.get('level', 'unknown')} {reason.get('rule', 'reason')}: "
                    f"{reason.get('message', '')}"
                )
    else:
        lines.append("- No risk elevation reasons recorded.")
    sources = verification["risk"].get("policy_sources", [])
    if sources:
        lines.extend(["", "## Risk Policy Sources", ""])
        for source in sources:
            lines.append(f"- {source}")
    lines.extend(["", "## Pack Checks", ""])
    if verification["pack_checks_source"]:
        lines.append(f"- Source: {verification['pack_checks_source']}")
    else:
        lines.append("- Source: none")
    if verification["checks"]:
        for check in verification["checks"]:
            lines.append(
                f"- {check['name']}: {check['status']} "
                f"(returncode: {check['returncode']})"
            )
    else:
        lines.append("- No pack checks configured.")
    if verification["blockers"]:
        lines.extend(["", "## Diagnostics", ""])
        for blocker in verification["blockers"]:
            lines.append(f"- {blocker}")
    lines.append("")
    return "\n".join(lines)


def update_loop_diagnostic(run_dir: Path, verification: dict[str, Any]) -> None:
    loop_path = run_dir / "loop.md"
    if not loop_path.exists():
        return
    text = loop_path.read_text(encoding="utf-8")
    marker = "# Current Attempt"
    diagnostic = (
        "# Current Attempt\n\n"
        f"Verification status: {verification['status']}.\n"
        f"Patch: {verification['patch'].get('path') or 'none'}.\n"
        f"Risk: {verification['risk'].get('risk') or 'unknown'}.\n"
    )
    if verification["blockers"]:
        diagnostic += (
            "Blockers:\n"
            + "\n".join(f"- {item}" for item in verification["blockers"])
            + "\n"
        )
    if marker not in text:
        loop_path.write_text(text.rstrip() + "\n\n" + diagnostic, encoding="utf-8")
        return
    before = text.split(marker, 1)[0].rstrip()
    loop_path.write_text(before + "\n\n" + diagnostic, encoding="utf-8")


def verify_run(
    project_dir: Path,
    *,
    confirmed: bool = False,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> VerifyResult:
    status = current_status(project_dir)
    if not status.initialized:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="Initialize LoopForge before verification.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            ok=False,
            message="No current run is ready for verification.",
            blockers=status.blockers or [status.next_step],
        )

    run = status.run
    run_dir = status.run_dir
    workspace_dir = run_workspace_path(run, status.project_dir)
    run_json_path = status.run_json_path or (run_dir / "run.json")
    profile_blockers = profile_transition_blockers(
        profile=run.get("profile", DEFAULT_PROFILE),
        action="verification",
        confirmed=confirmed,
        run=run,
        contract=status.loop_contract,
    )
    if profile_blockers:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge verification refused by the autonomy profile.",
            blockers=profile_blockers,
            verification=verification_state(run),
        )
    started = utc_now()
    patch_dir = run_dir / "artifacts" / "patches"
    patch_path = patch_dir / "complete.patch"
    blockers: list[str] = []
    patch_summary: dict[str, Any] = {
        "generated": False,
        "path": None,
        "size_bytes": 0,
        "sha256": None,
        "status": "not_run",
    }
    diff_summary: dict[str, Any] = {
        "allowed": None,
        "facts": {},
        "violations": [],
        "status": "not_run",
    }
    risk_summary: dict[str, Any] = {
        "risk": None,
        "route": None,
        "policy_allowed": None,
        "reasons": [],
        "facts": {},
        "status": "not_run",
    }
    checks: list[dict[str, Any]] = []
    pack_checks_source: str | None = None
    risk_policy_sources: list[str] = []
    risk_policy_path: Path | None = None

    emit_operation_event(operation_callback, "stage_started", "Starting deterministic verification.")

    def cancelled_result() -> VerifyResult | None:
        if cancel_event is None or not cancel_event.is_set():
            return None
        blocker = "verification was interrupted before the next check."
        interrupted_run = normalize_run_workflow_state(run)
        interrupted_run["updated_at"] = utc_now()
        interrupted_run["status"] = VERIFICATION_FAILED
        interrupted_run["blockers"] = [blocker]
        interrupted_run["current_stage"] = "verification_blocked"
        interrupted_run["stage_statuses"]["verification"] = "blocked"
        persist_run_json(status.project_dir, run_json_path, interrupted_run)
        emit_operation_event(operation_callback, "cancelled", blocker, status="cancelled")
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=interrupted_run,
            ok=False,
            message="LoopForge verification was interrupted.",
            blockers=[blocker],
            verification=verification_state(interrupted_run),
        )

    base_commit = run.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        blockers.append("patch generation requires a Git base_commit recorded in run.json.")
    elif not workspace_dir.exists() or not workspace_dir.is_dir():
        blockers.append(f"patch generation requires the run workspace: {workspace_dir}.")
    else:
        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Generating complete patch.", current=1, total=4)
        generated = run_json_check(
            [
                usable_python_executable(),
                "-m",
                "loopforge.checks.generate_complete_patch",
                "--repo",
                str(workspace_dir),
                "--base",
                base_commit,
                "--output",
                str(patch_path),
                "--policy",
                str(default_diff_policy()),
                "--force",
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if generated["returncode"] != 0 or generated["json"] is None:
            error = generated["stderr"].strip() or generated["stdout"].strip()
            patch_summary.update({"status": "failed", "error": error})
            blockers.append(f"patch generation failed: {error or 'unknown error'}")
        else:
            patch_result = generated["json"]
            artifact = patch_result.get("artifact", {})
            if not isinstance(artifact, dict):
                artifact = {}
            patch_summary.update(
                {
                    "generated": bool(artifact.get("retained", False)),
                    "path": relative_to_run(run_dir, patch_path) if artifact.get("retained") else None,
                    "size_bytes": artifact.get("size_bytes", 0),
                    "sha256": artifact.get("sha256"),
                    "status": "generated" if artifact.get("retained") else "not_retained",
                }
            )
            diff_summary.update(
                {
                    "allowed": bool(patch_result.get("allowed", False)),
                    "facts": patch_result.get("facts", {}),
                    "violations": patch_result.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                blockers.append("diff policy blocked the generated patch.")
        emit_operation_event(operation_callback, "check_finished", "Complete patch generation finished.", current=1, total=4)

    if patch_path.exists() and isinstance(base_commit, str) and base_commit:
        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Enforcing diff policy.", current=2, total=4)
        diff_result = run_json_check(
            [
                usable_python_executable(),
                "-m",
                "loopforge.checks.diff_policy",
                "--patch",
                str(patch_path),
                "--policy",
                str(default_diff_policy()),
                "--repo",
                str(workspace_dir),
                "--base",
                str(base_commit),
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if diff_result["returncode"] == 0 and diff_result["json"] is not None:
            diff_payload = diff_result["json"]
            diff_summary.update(
                {
                    "allowed": bool(diff_payload.get("allowed", False)),
                    "facts": diff_payload.get("facts", {}),
                    "violations": diff_payload.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                append_unique(blockers, "diff policy blocked the generated patch.")
        else:
            error = diff_result["stderr"].strip() or diff_result["stdout"].strip()
            diff_summary.update({"status": "failed", "error": error})
            blockers.append(f"diff policy failed: {error or 'unknown error'}")
        emit_operation_event(operation_callback, "check_finished", "Diff policy finished.", current=2, total=4)

        try:
            risk_policy_path, risk_policy_sources = merged_risk_policy_path(
                project_dir=status.project_dir,
                run_dir=run_dir,
                pack=str(run.get("pack") or DEFAULT_PACK),
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            risk_summary.update({"status": "failed", "error": str(error)})
            blockers.append(f"risk policy could not be loaded: {error}")

        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Classifying patch risk.", current=3, total=4)
        risk_result = run_json_check(
            [
                usable_python_executable(),
                "-m",
                "loopforge.checks.classify_patch_risk",
                "--patch",
                str(patch_path),
                "--diff-policy",
                str(default_diff_policy()),
                "--risk-policy",
                str(risk_policy_path or default_risk_policy()),
                "--repo",
                str(workspace_dir),
                "--base",
                str(base_commit),
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if risk_result["returncode"] == 0 and risk_result["json"] is not None:
            risk_payload = risk_result["json"]
            risk_summary.update(
                {
                    "risk": risk_payload.get("risk"),
                    "route": risk_payload.get("route"),
                    "policy_allowed": risk_payload.get("policy_allowed"),
                    "reasons": risk_payload.get("reasons", []),
                    "facts": risk_payload.get("facts", {}),
                    "human_gates": risk_payload.get("human_gates", {}),
                    "policy": (
                        relative_to_run(run_dir, risk_policy_path)
                        if risk_policy_path is not None
                        else str(default_risk_policy())
                    ),
                    "policy_sources": risk_policy_sources,
                    "status": "completed",
                }
            )
        else:
            error = risk_result["stderr"].strip() or risk_result["stdout"].strip()
            risk_summary.update({"status": "failed", "error": error})
            blockers.append(f"risk classification failed: {error or 'unknown error'}")
        emit_operation_event(operation_callback, "check_finished", "Patch risk classification finished.", current=3, total=4)

    try:
        pack_config = load_pack_checks(status.project_dir, str(run.get("pack") or DEFAULT_PACK))
        pack_checks_source = pack_config.get("source")
        pack_checks = pack_config["checks"]
        for index, check in enumerate(pack_checks, start=1):
            interrupted = cancelled_result()
            if interrupted is not None:
                return interrupted
            emit_operation_event(
                operation_callback,
                "check_started",
                f"Running {check['name']}.",
                current=index,
                total=len(pack_checks),
            )
            result = run_pack_check(
                check,
                project_dir=workspace_dir,
                run_dir=run_dir,
                patch_path=patch_path if patch_path.exists() else None,
            )
            checks.append(result)
            emit_operation_event(
                operation_callback,
                "check_finished",
                f"{check['name']} {result['status']}.",
                current=index,
                total=len(pack_checks),
                status=str(result["status"]),
            )
            if result["status"] != "passed":
                blockers.append(f"pack check failed: {result['name']} ({result['status']}).")
    except ValueError as error:
        blockers.append(f"pack checks could not be loaded: {error}")

    finished = utc_now()
    checks_passed = sum(1 for check in checks if check.get("status") == "passed")
    verification: dict[str, Any] = {
        "version": 1,
        "started_at": started,
        "finished_at": finished,
        "status": "failed" if blockers else "passed",
        "patch": patch_summary,
        "diff_policy": diff_summary,
        "risk": risk_summary,
        "pack": run.get("pack") or DEFAULT_PACK,
        "pack_checks_source": pack_checks_source,
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": checks_passed,
        "blockers": blockers,
    }
    signature = failure_signature(verification)
    if signature:
        previous = verification_state(run)
        if (
            isinstance(previous, dict)
            and previous.get("failure_signature") == signature
            and previous.get("status") == "failed"
        ):
            verification["stagnated"] = True
            append_unique(blockers, "stagnation: repeated equivalent verification failure.")
        verification["failure_signature"] = signature
    verification["blockers"] = blockers
    if blockers:
        verification["status"] = "failed"

    (run_dir / "verification.md").write_text(
        render_verification_markdown(verification),
        encoding="utf-8",
    )
    update_loop_diagnostic(run_dir, verification)

    updated_run = normalize_run_workflow_state(run)
    updated_run["verification"] = verification
    updated_run["updated_at"] = utc_now()
    updated_run["status"] = VERIFIED if not blockers else VERIFICATION_FAILED
    updated_run["blockers"] = [] if not blockers else blockers
    if not blockers:
        updated_run["current_stage"] = VERIFICATION_READY_STAGE
        updated_run["stage_statuses"]["verification"] = "complete"
        updated_run["stage_statuses"]["review"] = "pending"
        updated_run["human_gates"]["review_approval"] = {
            **initial_workflow_state()["human_gates"]["review_approval"],
            "status": "pending",
        }
        updated_run["publish_eligibility"] = {
            "eligible": False,
            "reasons": ["read-only review and approval are required before draft publication"],
        }
    else:
        updated_run["current_stage"] = "verification_blocked"
        updated_run["stage_statuses"]["verification"] = "blocked"
        if updated_run["stage_statuses"].get("review") not in {"approved", "complete"}:
            updated_run["stage_statuses"]["review"] = "pending"
        updated_run["publish_eligibility"] = {
            "eligible": False,
            "reasons": ["deterministic verification is blocked"],
        }
    persist_run_json(status.project_dir, run_json_path, updated_run)
    emit_operation_event(
        operation_callback,
        "completed" if not blockers else "blocked",
        "Verification passed." if not blockers else "Verification is blocked.",
        artifact=str(run_dir / "verification.md"),
        status="completed" if not blockers else "blocked",
    )

    return VerifyResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=updated_run,
        ok=not blockers,
        message="LoopForge verification passed." if not blockers else "LoopForge verification failed.",
        blockers=blockers,
        verification=verification,
    )


def implementation_gate_blockers(run: dict[str, Any]) -> list[str]:
    normalized = normalize_run_workflow_state(run)
    statuses = normalized.get("stage_statuses", {})
    gates = normalized.get("human_gates", {})
    if not isinstance(statuses, dict):
        statuses = {}
    if not isinstance(gates, dict):
        gates = {}
    plan_gate = gates.get("plan_approval")
    if not isinstance(plan_gate, dict):
        plan_gate = {}
    if statuses.get("plan") == "approved" and plan_gate.get("status") == "approved":
        return []
    return ["implementation requires an approved plan before adapter execution."]


def continue_run(
    project_dir: Path,
    *,
    adapter: str | None = None,
    adapter_args: list[str] | None = None,
    confirmed: bool = False,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> ContinueResult:
    status = current_status(project_dir)
    if not status.initialized:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            contract=None,
            ok=False,
            message="Initialize LoopForge before continuing.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            contract=status.loop_contract,
            ok=False,
            message="No current run is ready to continue.",
            blockers=status.blockers or [status.next_step],
        )

    contract = status.loop_contract or loop_contract_state(status.run_dir / "loop.md")
    run_status = str(status.run.get("status") or "")
    blockers = [] if run_status == ADAPTER_BLOCKED else list(status.blockers)
    for blocker in implementation_gate_blockers(status.run):
        append_unique(blockers, blocker)
    if contract["status"] != "valid":
        for error in contract.get("errors", []):
            append_unique(blockers, str(error))
    if not contract.get("success_checks"):
        append_unique(
            blockers,
            "loop contract has no success checks; add at least one under # Success Checks."
        )
    profile = str(status.run.get("profile", ""))
    if profile == "autonomous" and contract.get("subjective") and not contract.get("rubric"):
        append_unique(
            blockers,
            "subjective work needs a rubric before autonomous attempts; "
            "add it under # Subjective Rubric."
        )
    attempts = attempt_records(status.run)
    max_attempts = attempt_limit(status.run, contract)
    if len(attempts) >= max_attempts:
        append_unique(
            blockers,
            f"max attempts reached ({len(attempts)}/{max_attempts}); human review is required.",
        )
    workspace_dir = run_workspace_path(status.run, status.project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        append_unique(blockers, f"run workspace is not available: {workspace_dir}")
    if blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the loop contract.",
            blockers=blockers,
        )

    if adapter is None:
        profile_blockers = profile_transition_blockers(
            profile=status.run.get("profile", DEFAULT_PROFILE),
            action="adapter_attempt",
            confirmed=confirmed,
            run=status.run,
            contract=contract,
        )
        if profile_blockers:
            message = "Loop contract accepted; profile policy blocks adapter execution."
        else:
            message = (
                "Loop contract accepted; Phase 4 adapter execution is available "
                "with `loopforge continue --adapter <adapter>`."
            )
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=True,
            message=message,
            blockers=profile_blockers,
        )

    profile_blockers = profile_transition_blockers(
        profile=status.run.get("profile", DEFAULT_PROFILE),
        action="adapter_attempt",
        confirmed=confirmed,
        run=status.run,
        contract=contract,
    )
    if profile_blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the autonomy profile.",
            blockers=profile_blockers,
        )

    try:
        attempt = execute_attempt(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            adapter=adapter,
            adapter_args=adapter_args or [],
            operation_callback=operation_callback,
            cancel_event=cancel_event,
        )
        updated_run = update_run_after_attempt(
            project_dir=status.project_dir,
            run_json_path=status.run_json_path or (status.run_dir / "run.json"),
            run=status.run,
            attempt=attempt,
        )
    except (OSError, RuntimeError, ValueError) as error:
        blocker = f"adapter execution could not start: {error}"
        updated_run = dict(status.run)
        updated_run["status"] = ADAPTER_BLOCKED
        updated_run["blockers"] = [blocker]
        if status.run_json_path is not None:
            persist_run_json(status.project_dir, status.run_json_path, updated_run)
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=False,
            message="LoopForge adapter execution is blocked.",
            blockers=[blocker],
        )

    if attempt["status"] == "completed":
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=True,
            message="LoopForge adapter attempt completed; run is ready for verification.",
            blockers=[],
            attempt=attempt,
        )

    return ContinueResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated_run,
        contract=contract,
        ok=False,
        message="LoopForge adapter attempt ended in a blocked state.",
        blockers=updated_run.get("blockers", []),
        attempt=attempt,
    )
