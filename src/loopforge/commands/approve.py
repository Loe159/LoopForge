"""Application command: approve workflow stages."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _blocked,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult

_APPROVAL_STAGES = ("plan", "review", "task", "task_definition")


@register_command("approve")
def ApproveStage(
    ctx: CommandContext,
    *,
    stage: str,
    source: str = "local",
    success_check: str | None = None,
) -> AppCommandResult:
    """Wrap the approval engine functions into one AppCommandResult."""

    from loopforge.engine import (
        approve_initial_task,
        approve_plan,
        approve_review,
        complete_task_definition,
    )

    if stage == "plan":
        result = approve_plan(ctx.project_dir, source=source)
    elif stage == "review":
        result = approve_review(ctx.project_dir, source=source)
    elif stage == "task":
        result = approve_initial_task(ctx.project_dir, source=source)
    elif stage == "task_definition":
        if not success_check or not success_check.strip():
            return _blocked(
                "approve",
                "LoopForge task completion is blocked.",
                ["an objective success check is required."],
            )
        result = complete_task_definition(
            ctx.project_dir, success_check=success_check
        )
    else:
        return _blocked(
            "approve",
            f"unknown approval stage: {stage}",
            [
                f"expected one of: {', '.join(_APPROVAL_STAGES)}; got {stage}"
            ],
        )

    return _translate(
        "approve",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=str((result.run or {}).get("run_id") or "") or None,
        data={
            "stage": str(result.stage or stage),
            "run_dir": str(result.run_dir) if result.run_dir else None,
            "artifact_path": (
                str(result.artifact_path) if result.artifact_path else None
            ),
        },
        effects=[f"approved {stage}"] if result.ok else None,
    )
