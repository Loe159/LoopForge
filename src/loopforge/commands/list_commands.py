"""Application command: list runs."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _blocked,
    _ok,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("list_runs")
def ListRuns(
    ctx: CommandContext, *, all_projects: bool = False
) -> AppCommandResult:
    """Wrap ``list_runs`` and ``list_runs_all_projects`` into an AppCommandResult."""

    from loopforge.engine import list_runs, list_runs_all_projects

    if all_projects:
        result = list_runs_all_projects(ctx.home)
        if result.blockers and not result.runs:
            return _blocked(
                "list_runs",
                "LoopForge run listing is blocked.",
                list(result.blockers),
            )
        return _ok(
            "list_runs",
            None,
            {"runs": list(result.runs), "home": str(result.home)},
        )

    result = list_runs(ctx.project_dir)
    if not result.initialized:
        return _blocked(
            "list_runs",
            "LoopForge run listing is blocked.",
            list(result.blockers) or ["Initialize LoopForge first."],
        )
    return _ok(
        "list_runs",
        None,
        {
            "runs": list(result.runs),
            "run_root": str(result.run_root) if result.run_root else None,
            "current_run_id": result.current_run_id,
        },
    )
