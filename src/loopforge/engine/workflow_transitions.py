"""Reference: LoopForge workflow transitions.

This module documents the valid workflow stage transitions. It is NOT
executable logic -- the authoritative implementation lives in the ``apply_*``
functions in ``workflow.py`` and the direct stage assignments in
``execution.py``. The transition tuples below are kept as a readable reference
so the centralized contract that the former ``LifecycleStateMachine`` provided
is not lost.

Each entry is ``(from_stage, event, to_stage, guards, effects)``:

* ``from_stage`` / ``to_stage`` -- ``RunStage`` value strings.
* ``event`` -- human-readable description of the triggering action.
* ``guards`` -- named preconditions that the business code enforces (or
  ``[]`` when there are none beyond being in the source stage).
* ``effects`` -- the state mutations the transition produces (mirrored by the
  ``apply_*`` / direct-assignment logic).
"""

from __future__ import annotations

from typing import NamedTuple


class WorkflowTransition(NamedTuple):
    from_stage: str
    event: str
    to_stage: str
    guards: tuple[str, ...]
    effects: tuple[str, ...]


# Pre-verification gate bundle, enforced (or to be enforced) by the business
# path before a run reaches the verification stage.
_VERIFICATION_GATES = (
    "has_approved_task",
    "has_approved_plan",
    "has_valid_implementation_candidate",
    "has_base_commit",
    "has_pack_trust",
    "has_executable_evidence",
    "risk_gates_satisfied",
)

_VERIFICATION_REQUEST_EFFECTS = ("mark_verification_requested",)

WORKFLOW_TRANSITIONS: list[WorkflowTransition] = [
    # -- Task phase ---------------------------------------------------------
    WorkflowTransition(
        "task_draft",
        "approve task",
        "task_approved",
        guards=("has_approved_task",),
        effects=("mark_task_approved",),
    ),
    WorkflowTransition(
        "task_draft",
        "reject task",
        "task_draft",
        guards=(),
        effects=(),
    ),
    WorkflowTransition(
        "task_approved",
        "reset to draft",
        "task_draft",
        guards=(),
        effects=("reset_approval",),
    ),
    # -- Research phase -----------------------------------------------------
    WorkflowTransition(
        "task_approved",
        "start research",
        "research_ready",
        guards=(),
        effects=("mark_research_in_progress",),
    ),
    WorkflowTransition(
        "research_ready",
        "complete research",
        "research_completed",
        guards=("has_completed_research",),
        effects=("mark_research_completed",),
    ),
    # -- Plan phase ---------------------------------------------------------
    WorkflowTransition(
        "research_completed",
        "start plan",
        "plan_ready",
        guards=(),
        effects=("mark_plan_in_progress",),
    ),
    WorkflowTransition(
        "plan_ready",
        "approve plan",
        "plan_approved",
        guards=(),
        effects=("mark_plan_approved",),
    ),
    # -- Implementation phase ----------------------------------------------
    WorkflowTransition(
        "plan_approved",
        "start implementation",
        "implementation_ready",
        guards=(),
        effects=("mark_implementation_ready",),
    ),
    WorkflowTransition(
        "implementation_ready",
        "start implementation",
        "implementation_in_progress",
        guards=(),
        effects=("mark_implementation_in_progress",),
    ),
    WorkflowTransition(
        "implementation_in_progress",
        "complete implementation",
        "implementation_ready",
        guards=("has_valid_implementation_candidate",),
        effects=("mark_implementation_candidate",),
    ),
    # -- Verification phase -------------------------------------------------
    WorkflowTransition(
        "implementation_ready",
        "request verification",
        "verification_ready",
        guards=_VERIFICATION_GATES,
        effects=_VERIFICATION_REQUEST_EFFECTS,
    ),
    WorkflowTransition(
        "verification_ready",
        "verification pass",
        "verification_complete",
        guards=(),
        effects=("mark_verification_passed",),
    ),
    WorkflowTransition(
        "verification_ready",
        "verification fail",
        "verification_blocked",
        guards=(),
        effects=("mark_verification_blocked",),
    ),
    WorkflowTransition(
        "verification_blocked",
        "request verification (retry)",
        "verification_ready",
        guards=_VERIFICATION_GATES,
        effects=_VERIFICATION_REQUEST_EFFECTS,
    ),
    # -- Review phase -------------------------------------------------------
    WorkflowTransition(
        "verification_complete",
        "start review",
        "review_ready",
        guards=(),
        effects=("mark_review_in_progress",),
    ),
    WorkflowTransition(
        "review_ready",
        "approve review",
        "review_approved",
        guards=("has_approved_review",),
        effects=("mark_review_approved",),
    ),
    # -- Publication phase --------------------------------------------------
    WorkflowTransition(
        "review_approved",
        "prepare publication",
        "draft_publication_ready",
        guards=(),
        effects=("mark_publication_ready",),
    ),
    WorkflowTransition(
        "draft_publication_ready",
        "prepare publication (idempotent)",
        "draft_publication_ready",
        guards=(),
        effects=(),
    ),
]


def transitions_from(stage: str) -> list[WorkflowTransition]:
    """Return the documented transitions available from *stage*."""
    return [t for t in WORKFLOW_TRANSITIONS if t.from_stage == stage]
