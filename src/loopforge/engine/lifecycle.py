"""Lifecycle stage enums for LoopForge runs.

Defines the typed run stages (``RunStage``) and stage statuses
(``StageStatus``) shared across the engine. The workflow transitions
themselves live in ``workflow.py`` (apply_* functions) and the direct stage
assignments in ``execution.py``; a readable reference table is in
``workflow_transitions.py``.
"""

from __future__ import annotations

from enum import Enum


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
