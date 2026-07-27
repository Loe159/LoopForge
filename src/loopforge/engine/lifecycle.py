"""Lifecycle state machine for LoopForge runs.

Provides a single, typed, exhaustively testable state machine that owns all
lifecycle transitions. Replaces scattered transitions in apply_*_approval(),
verify_run(), and continue_run().
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

class RunStage(str, Enum):
    """Typed run stages in sequential workflow order."""

    TASK_DRAFT = "task_draft"
    TASK_APPROVED = "task_approved"
    RESEARCH_READY = "research_ready"
    RESEARCH_COMPLETED = "research_completed"
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    IMPLEMENTATION_READY = "implementation_ready"
    IMPLEMENTATION_IN_PROGRESS = "implementation_in_progress"
    VERIFICATION_READY = "verification_ready"
    VERIFICATION_BLOCKED = "verification_blocked"
    VERIFICATION_COMPLETE = "verification_complete"
    REVIEW_READY = "review_ready"
    REVIEW_APPROVED = "review_approved"
    DRAFT_PUBLICATION_READY = "draft_publication_ready"


class StageStatus(str, Enum):
    """Status of a workflow stage."""

    PENDING = "pending"
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class LifecycleEvent(str, Enum):
    """Events that can trigger a stage transition."""

    TASK_APPROVE = "task_approve"
    TASK_REJECT = "task_reject"
    RESEARCH_START = "research_start"
    RESEARCH_COMPLETE = "research_complete"
    PLAN_START = "plan_start"
    PLAN_APPROVE = "plan_approve"
    IMPLEMENTATION_START = "implementation_start"
    IMPLEMENTATION_COMPLETE = "implementation_complete"
    VERIFICATION_REQUEST = "verification_request"
    VERIFICATION_PASS = "verification_pass"
    VERIFICATION_FAIL = "verification_fail"
    REVIEW_START = "review_start"
    REVIEW_APPROVE = "review_approve"
    PUBLICATION_PREPARE = "publication_prepare"
    RESET_TO_DRAFT = "reset_to_draft"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------
# Maps (current_stage, event) -> (next_stage, [guard_names], [effect_names])

TRANSITION_TABLE: Dict[Tuple[str, str], Tuple[str, List[str], List[str]]] = {
    # ── Task phase ────────────────────────────────────────────────────────
    (
        RunStage.TASK_DRAFT.value,
        LifecycleEvent.TASK_APPROVE.value,
    ): (
        RunStage.TASK_APPROVED.value,
        ["has_approved_task"],
        ["mark_task_approved"],
    ),
    (
        RunStage.TASK_DRAFT.value,
        LifecycleEvent.TASK_REJECT.value,
    ): (
        RunStage.TASK_DRAFT.value,
        [],
        [],
    ),
    (
        RunStage.TASK_APPROVED.value,
        LifecycleEvent.RESET_TO_DRAFT.value,
    ): (
        RunStage.TASK_DRAFT.value,
        [],
        ["reset_approval"],
    ),

    # ── Research phase ────────────────────────────────────────────────────
    (
        RunStage.TASK_APPROVED.value,
        LifecycleEvent.RESEARCH_START.value,
    ): (
        RunStage.RESEARCH_READY.value,
        [],
        ["mark_research_in_progress"],
    ),
    (
        RunStage.RESEARCH_READY.value,
        LifecycleEvent.RESEARCH_COMPLETE.value,
    ): (
        RunStage.RESEARCH_COMPLETED.value,
        ["has_completed_research"],
        ["mark_research_completed"],
    ),

    # ── Plan phase ────────────────────────────────────────────────────────
    (
        RunStage.RESEARCH_COMPLETED.value,
        LifecycleEvent.PLAN_START.value,
    ): (
        RunStage.PLAN_READY.value,
        [],
        ["mark_plan_in_progress"],
    ),
    (
        RunStage.PLAN_READY.value,
        LifecycleEvent.PLAN_APPROVE.value,
    ): (
        RunStage.PLAN_APPROVED.value,
        ["has_approved_plan"],
        ["mark_plan_approved"],
    ),

    # ── Implementation phase ──────────────────────────────────────────────
    (
        RunStage.PLAN_APPROVED.value,
        LifecycleEvent.IMPLEMENTATION_START.value,
    ): (
        RunStage.IMPLEMENTATION_READY.value,
        [],
        ["mark_implementation_ready"],
    ),
    (
        RunStage.IMPLEMENTATION_READY.value,
        LifecycleEvent.IMPLEMENTATION_START.value,
    ): (
        RunStage.IMPLEMENTATION_IN_PROGRESS.value,
        [],
        ["mark_implementation_in_progress"],
    ),
    (
        RunStage.IMPLEMENTATION_IN_PROGRESS.value,
        LifecycleEvent.IMPLEMENTATION_COMPLETE.value,
    ): (
        RunStage.IMPLEMENTATION_READY.value,
        ["has_valid_implementation_candidate"],
        ["mark_implementation_candidate"],
    ),

    # ── Verification phase ────────────────────────────────────────────────
    (
        RunStage.IMPLEMENTATION_READY.value,
        LifecycleEvent.VERIFICATION_REQUEST.value,
    ): (
        RunStage.VERIFICATION_READY.value,
        [
            "has_approved_task",
            "has_approved_plan",
            "has_valid_implementation_candidate",
            "has_base_commit",
            "has_pack_trust",
            "has_executable_evidence",
            "risk_gates_satisfied",
        ],
        ["mark_verification_requested"],
    ),
    (
        RunStage.VERIFICATION_READY.value,
        LifecycleEvent.VERIFICATION_PASS.value,
    ): (
        RunStage.VERIFICATION_COMPLETE.value,
        [],
        ["mark_verification_passed"],
    ),
    (
        RunStage.VERIFICATION_READY.value,
        LifecycleEvent.VERIFICATION_FAIL.value,
    ): (
        RunStage.VERIFICATION_BLOCKED.value,
        [],
        ["mark_verification_blocked"],
    ),
    (
        RunStage.VERIFICATION_BLOCKED.value,
        LifecycleEvent.VERIFICATION_REQUEST.value,
    ): (
        RunStage.VERIFICATION_READY.value,
        [
            "has_approved_task",
            "has_approved_plan",
            "has_valid_implementation_candidate",
            "has_base_commit",
            "has_pack_trust",
            "has_executable_evidence",
            "risk_gates_satisfied",
        ],
        ["mark_verification_requested"],
    ),

    # ── Review phase ──────────────────────────────────────────────────────
    (
        RunStage.VERIFICATION_COMPLETE.value,
        LifecycleEvent.REVIEW_START.value,
    ): (
        RunStage.REVIEW_READY.value,
        [],
        ["mark_review_in_progress"],
    ),
    (
        RunStage.REVIEW_READY.value,
        LifecycleEvent.REVIEW_APPROVE.value,
    ): (
        RunStage.REVIEW_APPROVED.value,
        ["has_approved_review"],
        ["mark_review_approved"],
    ),

    # ── Publication phase ─────────────────────────────────────────────────
    (
        RunStage.REVIEW_APPROVED.value,
        LifecycleEvent.PUBLICATION_PREPARE.value,
    ): (
        RunStage.DRAFT_PUBLICATION_READY.value,
        [],
        ["mark_publication_ready"],
    ),
    (
        RunStage.DRAFT_PUBLICATION_READY.value,
        LifecycleEvent.PUBLICATION_PREPARE.value,
    ): (
        RunStage.DRAFT_PUBLICATION_READY.value,
        [],
        [],
    ),
}


# ---------------------------------------------------------------------------
# Guard registry
# ---------------------------------------------------------------------------

def guard_has_approved_task(run: dict, context: dict) -> bool:
    """Task must have been approved."""
    approval = run.get("approval", {})
    if not isinstance(approval, dict):
        return False
    return bool(approval.get("approved", False))


def guard_has_completed_research(run: dict, context: dict) -> bool:
    """Research stage must be completed."""
    stages = run.get("stage_statuses", {})
    if not isinstance(stages, dict):
        return False
    return stages.get("research") in (StageStatus.COMPLETED.value,)


def guard_has_approved_plan(run: dict, context: dict) -> bool:
    """Plan must be approved."""
    stages = run.get("stage_statuses", {})
    if not isinstance(stages, dict):
        return False
    return stages.get("plan") in (
        StageStatus.APPROVED.value,
        StageStatus.COMPLETED.value,
    )


def guard_has_valid_implementation_candidate(run: dict, context: dict) -> bool:
    """Must have at least one completed implementation attempt."""
    attempts = run.get("attempts", [])
    if not isinstance(attempts, list) or not attempts:
        return False
    return any(
        a.get("returncode", -1) == 0 or a.get("status") == "completed"
        for a in attempts
        if isinstance(a, dict)
    )


def guard_has_base_commit(run: dict, context: dict) -> bool:
    """A base commit must exist for version tracking."""
    base = run.get("base_commit")
    return isinstance(base, str) and bool(base)


def guard_has_pack_trust(run: dict, context: dict) -> bool:
    """The pack must be trusted (if trust checks are enabled).

    Currently always passes — pack trust checks are optional and can
    be extended with an actual trust store later.
    """
    return True


def guard_has_executable_evidence(run: dict, context: dict) -> bool:
    """Executable evidence must be present for verification.

    Currently always passes when verification is explicitly requested.
    """
    return True


def guard_has_approved_review(run: dict, context: dict) -> bool:
    """Review must be approved."""
    stages = run.get("stage_statuses", {})
    if not isinstance(stages, dict):
        return False
    return stages.get("review") == StageStatus.APPROVED.value


def guard_risk_gates_satisfied(run: dict, context: dict) -> bool:
    """Additional risk-based gates must be satisfied before verification.

    - risk=high    → plan_approval required even in autonomous mode
    - risk=critical → review_approval required before verification
    - risk=low/medium → no additional gates
    """
    risk = run.get("risk", {})
    if not isinstance(risk, dict):
        return True
    level = risk.get("level")
    required_gates = risk.get("required_gates", [])
    if not isinstance(required_gates, list):
        required_gates = []
    if not required_gates:
        return True
    gates = run.get("human_gates", {})
    if not isinstance(gates, dict):
        context["_risk_blockers"] = [f"Risk level '{level}' requires additional gates: {required_gates}"]
        return False
    unsatisfied = []
    if "plan_approval" in required_gates:
        plan_gate = gates.get("plan_approval")
        if not isinstance(plan_gate, dict) or plan_gate.get("status") != "approved":
            unsatisfied.append("plan_approval")
    if "review_approval" in required_gates:
        review_gate = gates.get("review_approval")
        if not isinstance(review_gate, dict) or review_gate.get("status") != "approved":
            unsatisfied.append("review_approval")
    if unsatisfied:
        context["_risk_blockers"] = [
            f"Risk level '{level}' requires additional gates: {unsatisfied}"
        ]
        return False
    return True


GUARDS: Dict[str, Callable] = {
    "has_approved_task": guard_has_approved_task,
    "has_completed_research": guard_has_completed_research,
    "has_approved_plan": guard_has_approved_plan,
    "has_valid_implementation_candidate": guard_has_valid_implementation_candidate,
    "has_base_commit": guard_has_base_commit,
    "has_pack_trust": guard_has_pack_trust,
    "has_executable_evidence": guard_has_executable_evidence,
    "has_approved_review": guard_has_approved_review,
    "risk_gates_satisfied": guard_risk_gates_satisfied,
}


# ---------------------------------------------------------------------------
# Effect registry
# ---------------------------------------------------------------------------

def effect_mark_task_approved(run: dict, context: dict) -> dict:
    """Mark task as approved and update stage status."""
    approval = run.setdefault("approval", {})
    approval["approved"] = True
    approval["source"] = context.get("source", "human")
    approval["approved_at"] = context.get("timestamp", "")
    run["stage_statuses"]["task"] = StageStatus.APPROVED.value
    gates = run.get("human_gates")
    if isinstance(gates, dict):
        gate = gates.get("initial_task_approval")
        if isinstance(gate, dict):
            gate["status"] = "approved"
    return run


def effect_reset_approval(run: dict, context: dict) -> dict:
    """Reset approval to draft state."""
    approval = run.setdefault("approval", {})
    approval["approved"] = False
    approval["source"] = "none"
    approval["approved_at"] = None
    run["stage_statuses"]["task"] = StageStatus.DRAFT.value
    return run


def effect_mark_research_in_progress(run: dict, context: dict) -> dict:
    run["stage_statuses"]["research"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_research_completed(run: dict, context: dict) -> dict:
    run["stage_statuses"]["research"] = StageStatus.COMPLETED.value
    return run


def effect_mark_plan_in_progress(run: dict, context: dict) -> dict:
    run["stage_statuses"]["plan"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_plan_approved(run: dict, context: dict) -> dict:
    run["stage_statuses"]["plan"] = StageStatus.APPROVED.value
    gates = run.get("human_gates")
    if isinstance(gates, dict):
        gate = gates.get("plan_approval")
        if isinstance(gate, dict):
            gate["status"] = "approved"
    return run


def effect_mark_implementation_ready(run: dict, context: dict) -> dict:
    run["stage_statuses"]["implementation"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_implementation_in_progress(run: dict, context: dict) -> dict:
    run["stage_statuses"]["implementation"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_implementation_candidate(run: dict, context: dict) -> dict:
    run["stage_statuses"]["implementation"] = StageStatus.COMPLETED.value
    return run


def effect_mark_verification_requested(run: dict, context: dict) -> dict:
    run["stage_statuses"]["verification"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_verification_passed(run: dict, context: dict) -> dict:
    run["stage_statuses"]["verification"] = StageStatus.COMPLETED.value
    return run


def effect_mark_verification_blocked(run: dict, context: dict) -> dict:
    run["stage_statuses"]["verification"] = StageStatus.BLOCKED.value
    return run


def effect_mark_review_in_progress(run: dict, context: dict) -> dict:
    run["stage_statuses"]["review"] = StageStatus.IN_PROGRESS.value
    return run


def effect_mark_review_approved(run: dict, context: dict) -> dict:
    run["stage_statuses"]["review"] = StageStatus.APPROVED.value
    gates = run.get("human_gates")
    if isinstance(gates, dict):
        gate = gates.get("review_approval")
        if isinstance(gate, dict):
            gate["status"] = "approved"
    run["publish_eligibility"] = {
        "eligible": True,
        "reasons": ["verified work has explicit review approval"],
    }
    return run


def effect_mark_publication_ready(run: dict, context: dict) -> dict:
    run["stage_statuses"]["publication"] = StageStatus.COMPLETED.value
    return run


EFFECTS: Dict[str, Callable] = {
    "mark_task_approved": effect_mark_task_approved,
    "reset_approval": effect_reset_approval,
    "mark_research_in_progress": effect_mark_research_in_progress,
    "mark_research_completed": effect_mark_research_completed,
    "mark_plan_in_progress": effect_mark_plan_in_progress,
    "mark_plan_approved": effect_mark_plan_approved,
    "mark_implementation_ready": effect_mark_implementation_ready,
    "mark_implementation_in_progress": effect_mark_implementation_in_progress,
    "mark_implementation_candidate": effect_mark_implementation_candidate,
    "mark_verification_requested": effect_mark_verification_requested,
    "mark_verification_passed": effect_mark_verification_passed,
    "mark_verification_blocked": effect_mark_verification_blocked,
    "mark_review_in_progress": effect_mark_review_in_progress,
    "mark_review_approved": effect_mark_review_approved,
    "mark_publication_ready": effect_mark_publication_ready,
}


# ---------------------------------------------------------------------------
# TransitionResult
# ---------------------------------------------------------------------------

@dataclass
class TransitionResult:
    """Result of attempting a state transition."""

    ok: bool
    current_stage: str
    new_stage: Optional[str]
    event: str
    updated_run: Optional[dict]
    blockers: List[str] = field(default_factory=list)
    guard_results: Dict[str, bool] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class LifecycleStateMachine:
    """Centralized state machine for run lifecycle transitions.

    Usage::

        sm = LifecycleStateMachine()
        result = sm.transition(run, LifecycleEvent.TASK_APPROVE, context={})
        if result.ok:
            run = result.updated_run
    """

    def transition(
        self,
        run: dict,
        event: LifecycleEvent,
        context: Optional[dict] = None,
    ) -> TransitionResult:
        """Attempt to apply an event to a run's current stage.

        The input *run* dict is never mutated — effects are applied to
        a shallow copy.

        Args:
            run: The run dict (copied before mutation).
            event: The lifecycle event to apply.
            context: Optional context dict for guards and effects
                (e.g. ``{"source": "human", "timestamp": "2024-..."}``).

        Returns:
            TransitionResult with ok, new_stage, updated_run, blockers.
        """
        context = context or {}
        current_stage = run.get("current_stage", RunStage.TASK_DRAFT.value)

        transition_key = (current_stage, event.value)
        if transition_key not in TRANSITION_TABLE:
            return TransitionResult(
                ok=False,
                current_stage=current_stage,
                new_stage=None,
                event=event.value,
                updated_run=None,
                blockers=[
                    f"No transition from '{current_stage}' "
                    f"for event '{event.value}'"
                ],
            )

        next_stage, guard_names, effect_names = TRANSITION_TABLE[transition_key]

        blockers: List[str] = []
        guard_results: Dict[str, bool] = {}
        for guard_name in guard_names:
            guard_fn = GUARDS.get(guard_name)
            if guard_fn is None:
                blockers.append(f"Unknown guard: {guard_name}")
                guard_results[guard_name] = False
                continue
            try:
                passed = guard_fn(run, context)
                guard_results[guard_name] = passed
                if not passed:
                    risk_blockers = context.pop("_risk_blockers", None)
                    if risk_blockers:
                        blockers.extend(risk_blockers)
                    else:
                        blockers.append(f"Guard '{guard_name}' failed")
            except Exception as exc:
                blockers.append(f"Guard '{guard_name}' error: {exc}")
                guard_results[guard_name] = False

        if blockers:
            return TransitionResult(
                ok=False,
                current_stage=current_stage,
                new_stage=None,
                event=event.value,
                updated_run=None,
                blockers=blockers,
                guard_results=guard_results,
            )

        updated_run = copy.deepcopy(run)
        updated_run["current_stage"] = next_stage

        for effect_name in effect_names:
            effect_fn = EFFECTS.get(effect_name)
            if effect_fn is not None:
                try:
                    updated_run = effect_fn(updated_run, context)
                except Exception as exc:
                    logger.error("Effect '%s' failed: %s", effect_name, exc)

        return TransitionResult(
            ok=True,
            current_stage=current_stage,
            new_stage=next_stage,
            event=event.value,
            updated_run=updated_run,
            blockers=[],
            guard_results=guard_results,
        )

    def allowed_events(self, run: dict) -> List[LifecycleEvent]:
        """Return the list of events allowed from the current stage."""
        current_stage = run.get("current_stage", RunStage.TASK_DRAFT.value)
        allowed: List[LifecycleEvent] = []
        for (stage, event_name), _ in TRANSITION_TABLE.items():
            if stage == current_stage:
                try:
                    allowed.append(LifecycleEvent(event_name))
                except ValueError:
                    pass
        return allowed

    def validate_transition_table(self) -> List[str]:
        """Validate the transition table for completeness.

        Returns a list of warnings (empty means valid).
        """
        warnings: List[str] = []
        for (stage, event), (_next_stage, guards, effects) in TRANSITION_TABLE.items():
            for guard_name in guards:
                if guard_name not in GUARDS:
                    warnings.append(
                        f"Missing guard '{guard_name}' in ({stage!r}, {event!r})"
                    )
            for effect_name in effects:
                if effect_name not in EFFECTS:
                    warnings.append(
                        f"Missing effect '{effect_name}' in ({stage!r}, {event!r})"
                    )
        return warnings


DEFAULT_STATE_MACHINE = LifecycleStateMachine()