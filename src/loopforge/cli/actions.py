"""Shared guided-action descriptors for text and interactive CLI surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from loopforge.engine import GuidedAction, GuidanceResult


@dataclass(frozen=True)
class ActionDescriptor:
    """A presentation-safe action derived from authoritative engine guidance."""

    id: str
    label: str
    description: str
    risk: str
    requires_confirmation: bool
    available: bool
    command_fallback: str
    executor_key: str


# These keys select a CLI adapter only.  Eligibility, labels, risk, and
# confirmation requirements always come from ``current_guidance``.
ACTION_EXECUTORS = {
    "init": "initialize",
    "complete-task": "complete-task",
    "approve-task": "approve-task",
    "run-research": "run-readonly-stage",
    "run-plan": "run-readonly-stage",
    "approve-plan": "approve-plan",
    "continue": "continue",
    "retry-attempt": "continue",
    "verify": "verify",
    "run-review": "run-readonly-stage",
    "approve-review": "approve-review",
    "prepare-draft": "prepare-draft",
    "status": "status",
    "create-run": "collect-task",
    "choose-adapter": "adapter",
}


def action_descriptors(guidance: GuidanceResult) -> tuple[ActionDescriptor, ...]:
    """Expose current engine guidance through one stable action contract."""

    return tuple(action_descriptor(action) for action in guidance.recommended_actions)


def action_descriptor(action: GuidedAction) -> ActionDescriptor:
    return ActionDescriptor(
        id=action.id,
        label=action.label,
        description=action.why,
        risk=action.risk,
        requires_confirmation=action.requires_confirmation,
        available=True,
        command_fallback=action.command,
        executor_key=ACTION_EXECUTORS.get(action.id, "command"),
    )


def primary_action(guidance: GuidanceResult) -> ActionDescriptor | None:
    actions = action_descriptors(guidance)
    return actions[0] if actions else None
