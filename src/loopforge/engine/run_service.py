"""Run creation, resume, and compact-context domain for LoopForge.

Owns the run-creation transaction (``create_run`` with its rollback
compensation), run resume (``resume_run``), and the compact-context
reporting helpers (``compact_current_context`` / ``render_compact_context``
/ ``directory_file_sizes``).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; lifecycle/path/storage/schema and the
``status_service``/``workspace``/``workflow`` sibling primitives are safe
top-level imports.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.engine.lifecycle import RunStage
from loopforge.engine.path_resolvers import (
    resolve_confined,
    resolve_run_dir,
    validate_identifier,
)
from loopforge.engine import projects as project_registry
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.models.schema import CURRENT_RUN_SCHEMA
from loopforge.engine.status_service import StatusResult
from loopforge.engine.workspace import WORKSPACE_MODE_GIT_WORKTREE
from loopforge.engine.workflow import RunResult


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


def resume_run(project_dir: Path, run_id: str) -> ResumeRunResult:
    from loopforge.engine import (
        current_status,
        persist_project_config,
        read_json,
        utc_now,
    )

    if not run_id.strip():
        return ResumeRunResult(
            project_dir=project_dir.resolve(),
            run_dir=None,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=["run id must not be empty"],
        )
    validate_identifier(run_id, "run")

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
    run_dir = resolve_run_dir(run_root, run_id.strip())
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
    from loopforge.engine import utc_now

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
    from loopforge.engine import current_status

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
    from loopforge.engine import utc_now

    timestamp = utc_now().replace("-", "").replace(":", "").replace("Z", "Z")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def _cleanup_workspace(project_dir: Path, workspace_path: str) -> None:
    """Remove a git worktree after a run creation failure.

    This is deliberately lenient: if the directory or worktree metadata is
    already gone the call is idempotent.
    """
    path = Path(workspace_path)
    if not path.exists():
        return
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    shutil.rmtree(path, ignore_errors=True)


def _rollback_run_creation(
    run_dir: Path | None,
    workspace_state: dict[str, Any] | None,
    project_dir: Path,
) -> None:
    """Idempotent cleanup of all artifacts created during a run creation attempt.

    Called when any step in the creation phase fails, this removes the run
    directory and any git worktree so no partial artifacts are left behind.
    """
    logger = logging.getLogger(__name__)
    if run_dir is not None and run_dir.exists():
        logger.warning("Rolling back incomplete run creation: %s", run_dir)
        shutil.rmtree(run_dir, ignore_errors=True)

    if workspace_state is not None and workspace_state.get("mode") == WORKSPACE_MODE_GIT_WORKTREE:
        workspace_path = workspace_state.get("path")
        if isinstance(workspace_path, str) and workspace_path.strip():
            _cleanup_workspace(project_dir, workspace_path)


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
    from loopforge.engine import (
        DEFAULT_ALLOWED_TOOLS,
        _check_git_available,
        _pack_registry,
        apply_initial_task_approval,
        detect_git_base_commit,
        detect_project_pack,
        ensure_project_memory,
        freeze_pack_contract,
        initial_workflow_state,
        load_pack_checks,
        load_pack_contract,
        loop_contract_status,
        normalize_config,
        normalize_nonempty_strings,
        normalize_profile,
        normalize_unique_strings,
        pack_skill_entries,
        persist_project_config,
        persist_run_json,
        prepare_run_workspace,
        profile_policy,
        project_config_path,
        read_json,
        read_project_template,
        render_loop_contract,
        render_run_memory_snapshot,
        task_looks_subjective,
        utc_now,
        validate_task_definition,
        write_json_atomic,
    )

    # ── Phase 1: Validation (no side effects) ──────────────────────────

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
    run_profile = normalize_profile(config["profile"])
    project_id = str(config.get("project_id") or "")
    if project_id:
        validate_identifier(project_id, "project")

    _check_git_available(project_dir)

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

    pack_check_config = load_pack_checks(project_dir, selected_pack)
    pack_checks = pack_check_config.get("checks", [])
    acceptance_criteria: list[str] = list(normalized_success_checks)
    verification_commands: list[dict[str, Any]] = []
    if pack_checks:
        for check in pack_checks:
            verification_commands.append(
                {
                    "criterion": check.get("name", ""),
                    "command": check.get("command", []),
                    "cwd": None,
                    "env": check.get("env", {}),
                    "timeout": check.get("timeout_seconds", 300),
                }
            )

    subjective = task_looks_subjective(task)
    normalized_rubric = subjective_rubric.strip()
    pack_skills = pack_skill_entries(pack_contract)
    normalized_skills = normalize_unique_strings(
        [*pack_skills, *normalize_nonempty_strings(selected_skills)]
    )
    normalized_allowed_tools = normalize_nonempty_strings(allowed_tools) or list(
        DEFAULT_ALLOWED_TOOLS
    )

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

    # ── Phase 2: Creation (transactional with compensation) ────────────

    run_root = Path(str(config["run_root"])).expanduser()
    run_id = new_run_id()
    run_dir = resolve_run_dir(run_root, run_id)
    while run_dir.exists():
        run_id = new_run_id()
        run_dir = resolve_run_dir(run_root, run_id)

    now = utc_now()
    base_commit = detect_git_base_commit(project_dir)
    workspace_state: dict[str, Any] | None = None

    try:
        attempts_dir = resolve_confined(run_dir, "attempts")
        artifacts_dir = resolve_confined(run_dir, "artifacts")
        metrics_dir = resolve_confined(run_dir, "metrics")
        for directory in (attempts_dir, artifacts_dir, metrics_dir):
            directory.mkdir(parents=True, exist_ok=False)
        (artifacts_dir / "publication").mkdir(parents=True, exist_ok=False)

        workspace_state = prepare_run_workspace(
            project_dir=project_dir,
            run_id=run_id,
            base_commit=base_commit,
            now=now,
            project_id=str(config.get("project_id") or "") or None,
        )
    except Exception:
        _rollback_run_creation(run_dir, workspace_state, project_dir)
        raise

    project_memory = ensure_project_memory(project_dir)
    task_id = run_id

    run_data: dict[str, Any] = {
        "schema_version": int(CURRENT_RUN_SCHEMA),
        "run_id": run_id,
        "task_id": task_id,
        "task": task.strip(),
        "project_root": str(project_dir),
        "base_commit": base_commit,
        "workspace": workspace_state,
        "profile": run_profile,
        "profile_policy": profile_policy(run_profile),
        "pack": selected_pack,
        "pack_contract": freeze_pack_contract(
            project_dir,
            selected_pack,
            registry=_pack_registry(project_dir),
            detection_mode=pack_detection,
            detection_score=pack_contract.get("detection_score", 0),
        ).to_dict(),
        "status": contract_status,
        **initial_workflow_state(),
        "task_validation": task_validation,
        "created_at": now,
        "success_checks": normalized_success_checks,
        "acceptance_criteria": acceptance_criteria,
        "verification_commands": verification_commands,
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

    try:
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
    except Exception:
        _rollback_run_creation(run_dir, workspace_state, project_dir)
        raise

    return RunResult(
        project_dir=project_dir,
        config_path=config_path,
        run_dir=run_dir,
        run_json_path=run_dir / "run.json",
        config=updated_config,
        run=run_data,
    )
