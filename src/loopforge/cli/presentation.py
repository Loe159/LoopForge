"""Immutable CLI presentation models built from engine status and guidance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.cli.actions import ActionDescriptor, action_descriptors
from loopforge.engine import GuidanceResult, StatusResult


STATE_FAMILIES = {
    "not_initialized": "setup",
    "ready_for_run": "ready",
    "task_needs_input": "needs_human",
    "task_awaiting_approval": "needs_human",
    "research_pending": "ready",
    "plan_pending": "ready",
    "plan_awaiting_approval": "needs_human",
    "implementation_pending": "ready",
    "implementation_blocked": "blocked",
    "verification_pending": "ready",
    "verification_blocked": "blocked",
    "review_pending": "ready",
    "review_awaiting_approval": "needs_human",
    "publication_pending": "needs_human",
    "draft_publication_ready": "complete",
    "archived": "archived",
}

FAMILY_PRESENTATION = {
    "setup": ("Setup required", "◆", "attention"),
    "ready": ("Ready", "●", "ready"),
    "running": ("Running", "◉", "running"),
    "needs_human": ("Needs approval", "◆", "attention"),
    "blocked": ("Blocked", "×", "danger"),
    "complete": ("Complete", "✓", "success"),
    "waiting": ("Waiting", "○", "secondary"),
    "archived": ("Archived", "–", "secondary"),
}


@dataclass(frozen=True)
class ProjectSummary:
    name: str
    path: Path
    initialized: bool
    profile: str | None
    pack: str | None


@dataclass(frozen=True)
class RunSummary:
    id: str
    short_id: str
    task: str
    status: str
    family: str
    current_stage: str
    actor: str
    archived: bool
    next_action: ActionDescriptor | None


@dataclass(frozen=True)
class StageView:
    id: str
    title: str
    actor: str
    status: str
    family: str
    marker: str
    label: str
    permission_mode: str | None


@dataclass(frozen=True)
class ShellSnapshot:
    project: ProjectSummary
    run: RunSummary | None
    stages: tuple[StageView, ...]
    actions: tuple[ActionDescriptor, ...]
    blockers: tuple[str, ...]
    state: str
    family: str


def state_family(state: object, *, blocked: bool = False, archived: bool = False) -> str:
    if archived:
        return "archived"
    if blocked:
        return "blocked"
    return STATE_FAMILIES.get(str(state or ""), "waiting")


def family_presentation(family: str) -> tuple[str, str, str]:
    return FAMILY_PRESENTATION.get(family, FAMILY_PRESENTATION["waiting"])


def workflow_progress(run: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Return compatibility progress text while deriving stages from the pack."""

    stages = stage_views(run, guidance_state="")
    if not stages:
        return str(run.get("current_stage") or "unknown"), "unknown", []
    current_index = next(
        (index for index, stage in enumerate(stages) if not _stage_complete(stage.id, stage.status)),
        len(stages) - 1,
    )
    current = stages[current_index]
    summary = f"{current_index + 1}/{len(stages)} {current.title}"
    lines = [
        f"- {index + 1}. {stage.title}: "
        f"{'done' if stage.family == 'complete' else 'current' if index == current_index else 'pending'} "
        f"[{stage.status}] via {stage.actor}"
        for index, stage in enumerate(stages)
    ]
    return summary, current.actor, lines


def stage_views(run: dict[str, Any], *, guidance_state: str) -> tuple[StageView, ...]:
    contract = run.get("pack_contract", {})
    workflow = contract.get("workflow", []) if isinstance(contract, dict) else []
    statuses = run.get("stage_statuses", {})
    if not isinstance(workflow, list) or not isinstance(statuses, dict):
        return ()

    current_id = str(run.get("current_stage") or "")
    if not current_id or current_id not in statuses:
        current_id = next(
            (
                str(stage.get("id") or "")
                for stage in workflow
                if isinstance(stage, dict)
                and not _stage_complete(
                    str(stage.get("id") or ""),
                    str(statuses.get(stage.get("id"), "pending")),
                )
            ),
            current_id,
        )
    views: list[StageView] = []
    for index, stage in enumerate(workflow):
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id") or "unknown")
        status = str(statuses.get(stage_id, "pending"))
        actor_data = stage.get("actor", {})
        actor = (
            str(actor_data.get("id") or actor_data.get("type") or "unknown")
            if isinstance(actor_data, dict)
            else "unknown"
        )
        if stage_id == "task" and status != "approved":
            validation = run.get("task_validation", {})
            needs_input = isinstance(validation, dict) and validation.get("status") == "needs_input"
            actor = "user" if needs_input or guidance_state == "task_needs_input" else "human-approver"
        elif stage_id == "plan" and status == "awaiting_approval":
            actor = "human-approver"
        elif stage_id == "review" and status == "complete":
            actor = "human-approver"
        family = _stage_family(stage_id, status, current_id, index, guidance_state)
        label, marker, _ = family_presentation(family)
        permission_mode = stage.get("mode") if isinstance(stage.get("mode"), str) else None
        views.append(
            StageView(
                id=stage_id,
                title=str(stage.get("title") or stage_id),
                actor=actor,
                status=status,
                family=family,
                marker=marker,
                label=label,
                permission_mode=permission_mode,
            )
        )
    return tuple(views)


def _stage_family(stage_id: str, status: str, current_id: str, index: int, guidance_state: str) -> str:
    if _stage_complete(stage_id, status):
        return "complete"
    if status in {"blocked", "failed"}:
        return "blocked"
    if status in {"awaiting_approval", "complete"} and stage_id in {"plan", "review"}:
        return "needs_human"
    if stage_id == current_id or (not current_id and index == 0):
        return state_family(guidance_state)
    return "waiting"


def _stage_complete(stage_id: str, status: str) -> bool:
    if stage_id == "task":
        return status == "approved"
    if stage_id == "plan":
        return status in {"approved", "complete"}
    if stage_id == "review":
        return status == "approved"
    if stage_id == "publication":
        return status == "draft_prepared"
    return status == "complete"


def shell_snapshot(result: StatusResult, guidance: GuidanceResult) -> ShellSnapshot:
    actions = action_descriptors(guidance)
    config = result.config or {}
    run = result.run
    project = ProjectSummary(
        name=result.project_dir.name,
        path=result.project_dir,
        initialized=result.initialized,
        profile=str(config.get("profile")) if config.get("profile") else None,
        pack=str(run.get("pack")) if isinstance(run, dict) and run.get("pack") else None,
    )
    if not isinstance(run, dict):
        return ShellSnapshot(
            project=project,
            run=None,
            stages=(),
            actions=actions,
            blockers=tuple(str(value) for value in result.blockers),
            state=guidance.state,
            family=state_family(guidance.state, blocked=bool(result.blockers)),
        )
    stages = stage_views(run, guidance_state=guidance.state)
    current = next((stage for stage in stages if stage.family not in {"complete", "waiting"}), stages[-1] if stages else None)
    archived = bool(run.get("archived"))
    run_summary = RunSummary(
        id=str(run.get("run_id") or ""),
        short_id=str(run.get("run_id") or "")[:12],
        task=str(run.get("task") or ""),
        status=str(run.get("status") or "unknown"),
        family=state_family(guidance.state, blocked=bool(result.blockers), archived=archived),
        current_stage=current.id if current is not None else str(run.get("current_stage") or "unknown"),
        actor=current.actor if current is not None else "unknown",
        archived=archived,
        next_action=actions[0] if actions else None,
    )
    return ShellSnapshot(
        project=project,
        run=run_summary,
        stages=stages,
        actions=actions,
        blockers=tuple(str(value) for value in result.blockers),
        state=guidance.state,
        family=run_summary.family,
    )
