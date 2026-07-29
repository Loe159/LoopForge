"""Status, guidance, dashboard, and run-list reporting for LoopForge projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.engine import projects as project_registry


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
class GlobalRunListResult:
    home: Path
    runs: list[dict[str, Any]]
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


def describe_next_step(run: dict[str, Any]) -> str:
    from loopforge.engine import (
        ADAPTER_BLOCKED,
        LOOP_CONTRACT_DRAFT,
        LOOP_CONTRACT_READY,
        READY_FOR_VERIFICATION,
        VERIFICATION_FAILED,
        VERIFIED,
        normalize_run_workflow_state,
    )

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
                if normalized.get("status") == VERIFICATION_FAILED:
                    return (
                        "Inspect verification.md, address the diagnostic with a bounded "
                        "adapter attempt, then run `loopforge verify` again."
                    )
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
        return (
            "Inspect verification.md, address the diagnostic with a bounded adapter "
            "attempt, then run `loopforge verify` again."
        )
    if status == VERIFIED:
        return "Review the verified patch and decide whether to continue, commit, or hand off."
    return "Inspect the run artifacts and decide the next bounded action."


def current_status(project_dir: Path) -> StatusResult:
    from loopforge.engine import (
        append_unique,
        loop_contract_state,
        memory_state,
        native_artifact_state,
        normalize_config,
        normalize_run_workflow_state,
        project_config_path,
        read_json,
        verification_state,
    )

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
    from loopforge.engine import (
        ADAPTER_BLOCKED,
        VERIFICATION_FAILED,
        normalize_run_workflow_state,
    )

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
        recovery_attempt = (
            statuses.get("verification") == "blocked"
            and run_status == VERIFICATION_FAILED
        )
        action = guided_action(
            "retry-attempt" if recovery_attempt else "verify",
            (
                f"Retry the developer with {adapter} to address verification diagnostics"
                if recovery_attempt
                else "Generate the patch and run deterministic checks"
            ),
            (
                f"loopforge continue --adapter {adapter}"
                if recovery_attempt
                else "loopforge verify"
            ),
            risk="adapter-execution" if recovery_attempt else "verification",
            requires_confirmation=(profile != "autonomous") if recovery_attempt else profile == "strict",
            why=(
                "A bounded follow-up attempt may address the recorded deterministic diagnostic."
                if recovery_attempt
                else "Checks and policy evidence are required before review."
            ),
        )
        state = "verification_blocked" if statuses.get("verification") == "blocked" else "verification_pending"
        summary = (
            "Verification failed; inspect diagnostics and run a bounded correction attempt."
            if recovery_attempt
            else "Implementation is complete; verification is next."
        )
        return state, summary, "verification", action

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


def current_guidance(project_dir: Path) -> GuidanceResult:
    """Compatibility wrapper for callers that only have a project path."""

    from loopforge.engine import current_status, guidance_from_status

    return guidance_from_status(current_status(project_dir))


def list_runs(project_dir: Path) -> RunListResult:
    """List compact runs without loading the current authoritative run."""

    from loopforge.engine import (
        list_runs_from_status,
        normalize_config,
        project_config_path,
        read_json,
    )

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


def list_registered_projects(home: Path | None = None) -> ProjectListResult:
    from loopforge.engine import (
        attention_order,
        loopforge_home,
        project_registry_summary,
    )

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
    from loopforge.engine import attention_order

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
    from loopforge.engine import read_json

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


def dashboard_snapshot(project_dir: Path) -> DashboardResult:
    from loopforge.engine import (
        append_unique,
        attempt_limit,
        attempt_timeout,
        dashboard_adapter_comparison,
        dashboard_attempt_rows,
        dashboard_memory_proposal_rows,
        summarize_run_metrics,
    )

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
