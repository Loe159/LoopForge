"""Application command: approve the review stage."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("review")
def ReviewRun(
    ctx: CommandContext, *, source: str = "local"
) -> AppCommandResult:
    """Wrap ``approve_review`` into an AppCommandResult."""

    from loopforge.engine import approve_review

    result = approve_review(ctx.project_dir, source=source)
    return _translate(
        "review",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=str((result.run or {}).get("run_id") or "") or None,
        data={
            "stage": str(result.stage or "review"),
            "run_dir": str(result.run_dir) if result.run_dir else None,
            "artifact_path": (
                str(result.artifact_path) if result.artifact_path else None
            ),
        },
        effects=["approved review"] if result.ok else None,
    )
