"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import sysconfig
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
    command_without_windows_batch_launcher as kilo_command_without_windows_batch_launcher,
    command_with_prompt as kilo_command_with_prompt,
    headless_run_command as kilo_headless_run_command,
    is_kilo_run_command,
)
from loopforge.checks import validate_implementation_result
from loopforge.engine.lifecycle import (
    RunStage,
    StageStatus,
)
from loopforge.engine.packs import (
    EffectivePackContract,
    PackCycleError,
    PackRegistry,
    diagnose_pack_issues as _diagnose_pack_issues,
    freeze_pack_contract,
)
from loopforge.engine.metrics import MetricsService
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine import projects as project_registry
from loopforge.engine import indexes as run_indexes
from loopforge.engine.artifacts import (
    bullet_items,
    loop_contract_state,
    markdown_sections,
    native_artifact_state,
    parse_frontmatter,
    parse_loop_limits,
    positive_int_after_colon,
    section_text,
    text_matches_any_marker,
)
from loopforge.engine.workspace import (
    _check_git_available,
    _has_git,
    _resolve_git_executable,
    codex_workspace_preflight_blockers,
    detect_git_base_commit,
    git_toplevel,
    prepare_run_workspace,
    run_workspace_path,
    run_workspace_state,
)
from loopforge.engine.models.schema import (
    CURRENT_RUN_SCHEMA,
    CURRENT_CONFIG_SCHEMA,
)
from loopforge.engine.models.migrations import migrate_run
from loopforge.engine.git_state import DEFAULT_GIT_STATE_SERVICE
from loopforge.engine.path_resolvers import (
    resolve_confined,
    resolve_run_dir,
    validate_identifier,
)
from loopforge.engine.doctor import DoctorService
from loopforge.engine.installation import (
    InstallationResult,
    default_diff_policy,
    default_risk_policy,
    imported_check,
    install_loopforge,
    is_windows_app_execution_alias,
    isolated_process_module,
    local_implementation_adapter,
    loopforge_module_command,
    repository_root,
    usable_python_executable,
)
from loopforge.engine.models.scope import ActionScope
from loopforge.engine.memory import (
    LearnResult,
    durable_memory_items,
    durable_memory_path,
    ensure_project_memory,
    ensure_templates,
    learn_run,
    memory_item_count,
    memory_state,
    memory_status_from_proposals,
    parse_memory_candidate_text,
    read_project_template,
    render_run_memory_snapshot,
)

logger = logging.getLogger(__name__)

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
    "schema_version",
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

READONLY_STAGE_INPUT_ARTIFACTS = {
    "research": ("task.md", "loop.md", "memory.md"),
    "plan": ("task.md", "loop.md", "research.md", "memory.md"),
    "review": (
        "task.md",
        "loop.md",
        "research.md",
        "plan.md",
        "progress.md",
        "verification.md",
        "memory.md",
    ),
}

IMPLEMENTATION_INPUT_ARTIFACTS = (
    "task.md",
    "loop.md",
    "research.md",
    "plan.md",
    "memory.md",
    "scratch.md",
)

EMBEDDED_RUN_ARTIFACT_LIMIT = 12_000

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
class IndexRepairResult:
    project_dir: Path
    run_root: Path | None
    ok: bool
    message: str
    diagnostics: dict[str, Any]
    blockers: list[str]


from loopforge.engine.status_service import (
    DashboardResult,
    GlobalRunListResult,
    GuidanceResult,
    GuidedAction,
    ProjectListResult,
    RunListResult,
    StatusResult,
    current_guidance,
    current_or_selected_run,
    current_status,
    dashboard_snapshot,
    describe_next_step,
    guided_action,
    list_registered_projects,
    list_runs,
    list_runs_all_projects,
    workflow_stage_guidance,
)
from loopforge.engine.project_service import (
    ConfigUpdateResult,
    InitResult,
    OpenProjectResult,
    archive_current_run,
    archive_run,
    initialize_project,
    new_config,
    normalize_config,
    open_project,
    set_default_adapter,
    update_project_config,
)
from loopforge.engine.workflow import (
    RunResult,
    StageResult,
    VerifyResult,
    apply_draft_publication_prepared,
    apply_initial_task_approval,
    apply_plan_approval,
    apply_review_approval,
    approve_initial_task,
    approve_plan,
    approve_review,
    complete_task_definition,
    implementation_gate_blockers,
    initial_workflow_state,
    normalize_run_workflow_state,
    validate_task_definition,
)
from loopforge.engine.run_service import (
    CompactContextResult,
    ResumeRunResult,
    _rollback_run_creation,
    compact_current_context,
    create_run,
    directory_file_sizes,
    new_run_id,
    render_compact_context,
    resume_run,
)
from loopforge.engine.execution import (
    ContinueResult,
    MetricsRecordResult,
    MetricsSummaryResult,
    OperationCallback,
    attempt_limit,
    attempt_records,
    attempt_timeout,
    build_metrics_record,
    continue_run,
    execute_attempt,
    first_nonnegative_int,
    inferred_final_disposition,
    latest_attempt,
    metrics_cost,
    metrics_model,
    metrics_patch,
    metrics_tokens,
    model_from_command,
    nonnegative_int_or_none,
    read_attempt_protocol_result,
    record_run_metrics,
    summarize_run_metrics,
    update_run_after_attempt,
)
from loopforge.engine.adapter_runtime import (
    adapter_protocol_command,
    command_for_adapter,
    command_for_attempt,
    command_for_readonly_stage,
    decode_output,
    emit_adapter_output,
    emit_operation_event,
    execute_adapter_command,
    execute_fixture_command,
    execute_readonly_adapter_command,
    expand_check_value,
    pack_check_paths,
    parse_adapter_result,
    parse_adapter_result_file,
    resolve_child_executable,
    run_json_check,
    run_pack_check,
    run_streaming_process,
    run_with_isolated_process,
    synthetic_adapter_result,
    validate_attempt_result,
    write_bytes,
)
from loopforge.engine.stages import (
    execute_readonly_stage,
    next_readonly_stage,
    prepare_draft_publication,
    validate_readonly_stage_artifact,
)
from loopforge.engine.verification import (
    load_pack_checks,
    verify_run,
)
from loopforge.engine.rendering import (
    append_markdown_bullet,
    append_progress,
    compact_text,
    dashboard_adapter_comparison,
    dashboard_attempt_rows,
    dashboard_average_text,
    dashboard_memory_proposal_rows,
    dashboard_number_summary,
    dashboard_text_lines,
    draft_publication_body,
    remove_placeholder_item,
    render_adapter_prompt,
    render_embedded_run_artifacts,
    render_loop_contract,
    render_memory_proposals_markdown,
    render_stage_prompt,
    render_verification_markdown,
    update_loop_diagnostic,
)


def _load_config_scope(project_dir: Path) -> ActionScope | None:
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return None
    try:
        config = normalize_config(project_dir, read_json(config_path))[0]
    except (OSError, ValueError):
        return None
    return ActionScope(
        project_id=str(config.get("project_id") or ""),
        project_path=project_dir.resolve(),
        run_id=str(config.get("current_run_id") or "") or None,
    )


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
        write_json_atomic(run_json_path, run)
        return
    from loopforge.engine.repositories import RunRepository
    try:
        repo = RunRepository(run_json_path.parent)
        repo.write(run)
    except Exception:
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
    from loopforge.engine.repositories import ConfigRepository
    try:
        repo = ConfigRepository(config_path.parent, lock_timeout=2.0)
        repo.write(config)
    except Exception:
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


def diagnose_pack_issues(project_dir: Path) -> list[dict[str, str]]:
    """Facade over packs.diagnose_pack_issues for CLI and interactive doctor."""
    return _diagnose_pack_issues(project_dir)


def run_doctor(
    project_dir: Path | None = None,
    home: Path | None = None,
    *,
    rebuild_indexes_flag: bool = False,
) -> dict[str, Any]:
    """Unified diagnostic service replacing inline /doctor handling."""
    from loopforge.engine.doctor import DoctorResult

    service = DoctorService(home=home, project_dir=project_dir)
    result = service.examine()

    if rebuild_indexes_flag:
        rebuilt = 0
        messages: list[str] = []
        for diag in result.diagnostics:
            if diag.category == "stale_index" and diag.repairable:
                ok, msg = service.repair(diag)
                if ok:
                    rebuilt += 1
                messages.append(msg)
        return {
            "ok": result.ok,
            "diagnostics": [
                {
                    "level": d.level,
                    "category": d.category,
                    "source": d.source,
                    "message": d.message,
                    "proposed_action": d.proposed_action,
                    "repairable": d.repairable,
                }
                for d in result.diagnostics
            ],
            "summary": result.summary,
            "repairs_available": result.repairs_available,
            "rebuilt_indexes": rebuilt,
            "rebuild_messages": messages,
            "examined_at": result.examined_at,
        }

    return {
        "ok": result.ok,
        "diagnostics": [
            {
                "level": d.level,
                "category": d.category,
                "source": d.source,
                "message": d.message,
                "proposed_action": d.proposed_action,
                "repairable": d.repairable,
            }
            for d in result.diagnostics
        ],
        "summary": result.summary,
        "repairs_available": result.repairs_available,
        "examined_at": result.examined_at,
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


def _pack_registry(project_dir: Path) -> PackRegistry:
    return PackRegistry(
        project_dir,
        bundled_root=repository_root(),
        bundled_packs_root=Path(__file__).resolve().parents[1] / "packs",
        store=DEFAULT_JSON_STORE,
        config_dir=CONFIG_DIR,
        default_pack=DEFAULT_PACK,
    )


def pack_registry(project_dir: Path) -> PackRegistry:
    """Public facade for the project-scoped pack registry.

    CLI and interactive frontends should call this instead of the private
    ``_pack_registry`` helper so they depend only on the engine's public API.
    """

    return _pack_registry(project_dir)


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


def memory_artifact_dir(run_dir: Path) -> Path:
    return run_dir / "artifacts" / "memory"


def memory_proposal_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.json"


def memory_proposal_markdown_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.md"


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


def session_hash(seed: dict[str, Any], label: str) -> str:
    encoded = json.dumps({"label": label, **seed}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_issue_number(run: dict[str, Any]) -> int:
    direct = run.get("issue")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct >= 1:
        return direct

    evidence = run.get("evidence", {})
    source = evidence.get("source", {}) if isinstance(evidence, dict) else {}
    if isinstance(source, dict):
        for key in ("issue", "number", "issue_number"):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
                return value
        for key in ("reference", "url"):
            value = source.get(key)
            if not isinstance(value, str):
                continue
            match = re.search(r"(?:#|/issues/)([1-9][0-9]*)(?:\D|$)", value)
            if match:
                return int(match.group(1))

    # Native tasks do not always originate from an issue, while the portable
    # implementation-result contract requires a positive issue identifier.
    return 1


def implementation_base_commit(run: dict[str, Any]) -> str:
    value = run.get("base_commit")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value):
        return value
    return "0" * 40


def implementation_recovery_authorized(run: dict[str, Any]) -> bool:
    status = str(run.get("status") or "")
    if status == VERIFICATION_FAILED:
        return True
    if status != ADAPTER_BLOCKED:
        return False
    return any(
        attempt.get("workspace_changed") is True
        for attempt in attempt_records(run)
    )


def expected_session_for(run: dict[str, Any], adapter: str, workspace_dir: Path) -> dict[str, Any]:
    issue = run_issue_number(run)
    base_commit = implementation_base_commit(run)
    recovery_authorized = implementation_recovery_authorized(run)
    seed = {
        "issue": issue,
        "base_commit": base_commit,
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "adapter": adapter,
        "workspace": str(workspace_dir.resolve()),
        "recovery_authorized": recovery_authorized,
    }
    run_risk = run.get("risk", {})
    risk_level = (
        run_risk.get("level")
        if isinstance(run_risk, dict) and run_risk.get("level") in ("low", "medium", "high", "critical")
        else "low"
    )
    session = {
        "issue": issue,
        "risk": risk_level,
        "base_commit": base_commit,
        "workspace": str(workspace_dir.resolve()),
        "runner_id": adapter,
        "recovery_authorized": recovery_authorized,
        "preflight_sha256": session_hash(seed, "preflight"),
        "start_authorization_receipt_sha256": session_hash(seed, "start-authorization"),
    }
    return validate_implementation_result.validate_expected_session(session)


def relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return str(path)


def workspace_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    """Return a map of {relative_path: (size, mtime_ns)} for every tracked file.

    The runtime storage directory (``LOOPFORGE_HOME`` when it points inside the
    project, and ``.loopforge/``) is excluded so internal state never leaks into
    snapshots, patches, or prompts.
    """
    excluded = {".git", ".loopforge"}
    home = os.environ.get("LOOPFORGE_HOME")
    if home:
        try:
            home_path = Path(home).expanduser().resolve()
            project_resolved = project_dir.resolve()
            if home_path == project_resolved or str(home_path).startswith(str(project_resolved) + os.sep):
                home_rel = home_path.relative_to(project_resolved)
                excluded.add(home_rel.parts[0] if home_rel.parts else str(home_path))
        except (ValueError, OSError):
            pass

    snapshot: dict[str, tuple[int, int]] = {}
    for path in project_dir.rglob("*"):
        if any(part in excluded for part in path.parts):
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
    git_path = _resolve_git_executable()
    if git_path is None:
        return None
    from loopforge.engine.process_runner import ProcessRunner
    runner = ProcessRunner(output_limit_bytes=50000, timeout=10)
    receipt = runner.run(
        [git_path, "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_dir,
    )
    if not receipt.completed:
        return None
    return [line for line in receipt.stdout.splitlines() if line.strip()]


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


def retain_rejected_readonly_artifact(*, stage_dir: Path, stage: str, content: bytes) -> Path:
    """Keep each invalid read-only artifact candidate as inspectable evidence."""

    rejected_dir = stage_dir / "rejected-artifacts"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate_path = rejected_dir / f"{stage}-candidate-{index:03d}.md"
        if not candidate_path.exists():
            write_bytes(candidate_path, content)
            return candidate_path
        index += 1


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


def current_git_branch(project_dir: Path) -> str:
    state = DEFAULT_GIT_STATE_SERVICE.get(project_dir, allow_fallback=True)
    return state.branch or "HEAD"


def pack_protected_path_paths(project_dir: Path, pack: str) -> list[Path]:
    return _pack_registry(project_dir).protected_path_paths(pack)


def load_pack_protected_paths(project_dir: Path, pack: str) -> dict[str, Any]:
    return _pack_registry(project_dir).load_protected_paths(pack)


def merged_risk_policy_path(
    *,
    project_dir: Path,
    run_dir: Path,
    pack: str,
    run: dict[str, Any] | None = None,
) -> tuple[Path, list[str]]:
    base = read_json(default_risk_policy())
    sources = [str(default_risk_policy())]
    if run is not None:
        frozen_contract = run.get("pack_contract", {})
        if isinstance(frozen_contract, dict) and frozen_contract.get("protected_paths") is not None:
            protected_paths = frozen_contract.get("protected_paths", [])
            high_patterns = normalize_unique_strings(
                [
                    *[str(pattern) for pattern in base.get("high_path_patterns", [])],
                    *[str(item["pattern"]) for item in protected_paths if isinstance(item, dict) and item.get("severity") == "high"],
                ]
            )
            medium_patterns = normalize_unique_strings(
                [
                    *[str(pattern) for pattern in base.get("medium_path_patterns", [])],
                    *[str(item["pattern"]) for item in protected_paths if isinstance(item, dict) and item.get("severity") == "medium"],
                ]
            )
            if protected_paths:
                protected_source = load_pack_protected_paths(project_dir, pack)
                if protected_source.get("source"):
                    sources.append(str(protected_source["source"]))
            merged = dict(base)
            merged["high_path_patterns"] = high_patterns
            merged["medium_path_patterns"] = medium_patterns
            policy_path = run_dir / "artifacts" / "policies" / "risk-rules.merged.json"
            write_json_atomic(policy_path, merged)
            return policy_path, sources
    protected = load_pack_protected_paths(project_dir, pack)
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


def _build_criterion_results(
    acceptance_criteria: list[str],
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for criterion in acceptance_criteria:
        criterion_checks = [
            check for check in checks
            if check.get("criterion", "") == criterion
        ]
        if not criterion_checks:
            criterion_checks = checks
        passed = all(
            check.get("status") == "passed"
            for check in criterion_checks
            if isinstance(check, dict)
        )
        results.append(
            {
                "criterion": criterion,
                "status": "passed" if passed else "failed",
                "checks": criterion_checks,
            }
        )
    return results
