"""Workflow state and approval domain for LoopForge runs.

Owns the persisted workflow-state shape (``current_stage``, ``stage_statuses``,
``human_gates``, ``publish_eligibility``), the pure state-machine application
helpers (``apply_*_approval`` / ``apply_draft_publication_prepared``), the
public approval commands (``approve_initial_task``, ``approve_plan``,
``approve_review``, ``complete_task_definition``), and the implementation gate
check (``implementation_gate_blockers``).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; lifecycle primitives are safe top-level
imports from the ``lifecycle`` sibling submodule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.engine.lifecycle import (
    RunStage,
    StageStatus,
)
from loopforge.engine.models.migrations import migrate_run

logger = logging.getLogger(__name__)


WORKFLOW_STAGES = (
    "task",
    "research",
    "plan",
    "implementation",
    "verification",
    "review",
    "publication",
)


@dataclass(frozen=True)
class RunResult:
    project_dir: Path
    config_path: Path
    run_dir: Path
    run_json_path: Path
    config: dict[str, Any]
    run: dict[str, Any]


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


def initial_workflow_state() -> dict[str, Any]:
    stage_statuses = {stage: "pending" for stage in WORKFLOW_STAGES}
    stage_statuses["task"] = "draft"
    return {
        "current_stage": RunStage.TASK_DRAFT.value,
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
            "required_gates": [],
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
        "acceptance_criteria": [],
        "verification_commands": [],
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
    normalized = dict(migrate_run(run))
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
    else:
        valid_stages = {stage.value for stage in RunStage}
        if current_stage not in valid_stages:
            logger.warning(
                "normalize_run_workflow_state: unrecognized stage %r, resetting to %r",
                current_stage,
                RunStage.TASK_DRAFT.value,
            )
            normalized["current_stage"] = RunStage.TASK_DRAFT.value

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

    for key in ("acceptance_criteria", "verification_commands"):
        value = normalized.get(key)
        if not isinstance(value, list):
            normalized[key] = []

    reasons = normalized["risk"].get("reasons")
    if not isinstance(reasons, list):
        normalized["risk"]["reasons"] = []
    required_gates = normalized["risk"].get("required_gates")
    if not isinstance(required_gates, list):
        normalized["risk"]["required_gates"] = []
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
    from loopforge.engine import utc_now

    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    task_validation = normalized.get("task_validation", {})
    task_is_valid = not isinstance(task_validation, dict) or task_validation.get(
        "status"
    ) in {None, "valid"}
    approved = approved and task_is_valid
    if approved:
        normalized["current_stage"] = RunStage.TASK_APPROVED.value
        normalized["stage_statuses"]["task"] = StageStatus.APPROVED.value
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

    normalized["current_stage"] = RunStage.TASK_DRAFT.value
    normalized["stage_statuses"]["task"] = StageStatus.DRAFT.value
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
    from loopforge.engine import utc_now

    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    normalized["current_stage"] = RunStage.IMPLEMENTATION_READY.value
    normalized["stage_statuses"]["plan"] = StageStatus.APPROVED.value
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
    from loopforge.engine import utc_now

    normalized = normalize_run_workflow_state(run)
    clean_source = source.strip() if isinstance(source, str) else ""
    normalized["current_stage"] = RunStage.REVIEW_READY.value
    normalized["stage_statuses"]["review"] = StageStatus.APPROVED.value
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
    normalized["current_stage"] = RunStage.DRAFT_PUBLICATION_READY.value
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


def approve_initial_task(
    project_dir: Path,
    *,
    source: str = "local",
) -> StageResult:
    """Record the explicit approval required before research can begin."""
    from loopforge.engine import current_status, persist_run_json, utc_now

    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="initial_task_approval",
            ok=False,
            message="Initialize LoopForge before approving a task.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="initial_task_approval",
            ok=False,
            message="No current run is ready for task approval.",
            blockers=status.blockers or [status.next_step],
        )

    run = normalize_run_workflow_state(status.run)
    gate = run.get("human_gates", {}).get("initial_task_approval", {})
    blockers: list[str] = []
    if not isinstance(gate, dict) or gate.get("status") != "pending":
        blockers.append("initial task approval is not pending.")
    task_validation = run.get("task_validation", {})
    if isinstance(task_validation, dict) and task_validation.get("status") not in {None, "valid"}:
        blockers.append("task approval requires a valid task definition.")
    if blockers:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="initial_task_approval",
            ok=False,
            message="LoopForge task approval is blocked.",
            blockers=blockers,
            artifact_path=status.run_dir / "task.md",
        )

    updated = apply_initial_task_approval(run, approved=True, source=source)
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="initial_task_approval",
        ok=True,
        message="LoopForge task approved; research is ready.",
        blockers=[],
        artifact_path=status.run_dir / "task.md",
    )


def complete_task_definition(
    project_dir: Path,
    *,
    success_check: str,
) -> StageResult:
    """Add objective proof to the current task contract without replacing its run."""
    from loopforge.engine import (
        DEFAULT_ALLOWED_TOOLS,
        DEFAULT_PACK,
        current_status,
        loop_contract_status,
        normalize_nonempty_strings,
        normalize_profile,
        normalize_unique_strings,
        persist_run_json,
        render_loop_contract,
        task_looks_subjective,
        utc_now,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="task_definition",
            ok=False,
            message="Initialize LoopForge before completing a task definition.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="task_definition",
            ok=False,
            message="No current run is ready for task completion.",
            blockers=status.blockers or [status.next_step],
        )

    proof = success_check.strip()
    if not proof:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            stage="task_definition",
            ok=False,
            message="LoopForge task completion is blocked.",
            blockers=["an objective success check is required."],
            artifact_path=status.run_dir / "task.md",
        )

    run = normalize_run_workflow_state(status.run)
    validation = run.get("task_validation", {})
    if isinstance(validation, dict) and validation.get("status") == "valid":
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="task_definition",
            ok=False,
            message="The current task definition is already complete.",
            blockers=["approve the task before starting research."],
            artifact_path=status.run_dir / "task.md",
        )

    task = str(run.get("task") or "").strip()
    checks = normalize_unique_strings(
        [
            *normalize_nonempty_strings(
                [str(value) for value in run.get("success_checks", [])]
                if isinstance(run.get("success_checks"), list)
                else []
            ),
            proof,
        ]
    )
    profile = normalize_profile(run.get("profile"))
    subjective = task_looks_subjective(task)
    contract = status.loop_contract if isinstance(status.loop_contract, dict) else {}
    rubric = str(contract.get("rubric") or "").strip()
    task_validation = validate_task_definition(
        task=task,
        success_checks=checks,
        profile=profile,
        subjective=subjective,
        subjective_rubric=rubric,
    )
    if task_validation["status"] != "valid":
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="task_definition",
            ok=False,
            message="LoopForge task completion is blocked.",
            blockers=[str(item) for item in task_validation["missing"]],
            artifact_path=status.run_dir / "task.md",
        )

    pack_contract = run.get("pack_contract", {})
    skills = (
        normalize_nonempty_strings([str(value) for value in pack_contract.get("skills", [])])
        if isinstance(pack_contract, dict) and isinstance(pack_contract.get("skills"), list)
        else []
    )
    allowed_tools = (
        normalize_nonempty_strings([str(value) for value in contract.get("allowed_tools", [])])
        if isinstance(contract.get("allowed_tools"), list)
        else list(DEFAULT_ALLOWED_TOOLS)
    )
    limits = run.get("limits", {})
    max_attempts = limits.get("max_attempts", 3) if isinstance(limits, dict) else 3
    timeout_seconds = limits.get("timeout_seconds", 1800) if isinstance(limits, dict) else 1800
    if not isinstance(max_attempts, int) or max_attempts < 1:
        max_attempts = 3
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        timeout_seconds = 1800
    loop_status = loop_contract_status(
        success_checks=checks,
        profile=profile,
        subjective=subjective,
        subjective_rubric=rubric,
    )
    updated = apply_initial_task_approval(run, approved=False, source="none")
    updated["success_checks"] = checks
    updated["task_validation"] = task_validation
    updated["status"] = loop_status
    updated["loop_contract"] = {
        **(run.get("loop_contract") if isinstance(run.get("loop_contract"), dict) else {}),
        "path": str(status.run_dir / "loop.md"),
        "version": 1,
        "status": loop_status,
        "subjective": subjective,
        "requires_rubric": profile == "autonomous" and subjective,
    }
    updated["blockers"] = []
    updated["updated_at"] = utc_now()
    (status.run_dir / "task.md").write_text(f"# Task\n\n{task}\n", encoding="utf-8")
    (status.run_dir / "loop.md").write_text(
        render_loop_contract(
            task=task,
            task_id=str(run.get("task_id") or run.get("run_id") or ""),
            project_dir=status.project_dir,
            base_commit=str(run.get("base_commit") or "") or None,
            profile=profile,
            pack=str(run.get("pack") or DEFAULT_PACK),
            skills=skills,
            allowed_tools=allowed_tools,
            success_checks=checks,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            subjective=subjective,
            subjective_rubric=rubric,
        ),
        encoding="utf-8",
    )
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="task_definition",
        ok=True,
        message="LoopForge task contract is complete; explicit task approval is next.",
        blockers=[],
        artifact_path=status.run_dir / "loop.md",
    )


def approve_plan(
    project_dir: Path,
    *,
    source: str = "local",
) -> StageResult:
    from loopforge.engine import (
        current_status,
        persist_run_json,
        utc_now,
        validate_readonly_stage_artifact,
    )

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
    elif not blockers:
        try:
            plan_text = plan_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            blockers.append(f"plan approval could not read plan.md: {error}")
        else:
            blockers.extend(validate_readonly_stage_artifact("plan", plan_text))
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
    from loopforge.engine import current_status, persist_run_json, utc_now

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
