"""Application command: learn durable memory from a run."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("learn")
def LearnRun(
    ctx: CommandContext,
    *,
    approve: bool = False,
    notes: list[str] | None = None,
    confirmed: bool | None = None,
) -> AppCommandResult:
    """Wrap ``learn_run`` into an AppCommandResult."""

    from loopforge.engine import learn_run

    result = learn_run(
        ctx.project_dir,
        approve=approve,
        notes=notes,
        confirmed=ctx.confirmed if confirmed is None else confirmed,
    )
    return _translate(
        "learn",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=str((result.run or {}).get("run_id") or "") or None,
        data={
            "run_dir": str(result.run_dir) if result.run_dir else None,
            "proposals": list(result.proposals),
            "promoted": list(result.promoted),
            "rejected": list(result.rejected),
            "proposal_path": (
                str(result.proposal_path) if result.proposal_path else None
            ),
        },
        effects=(["promoted memory"] if (result.ok and result.promoted) else None),
    )
