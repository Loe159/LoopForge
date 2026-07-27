"""Application command: archive runs."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("archive")
def ArchiveRun(
    ctx: CommandContext, *, run_id: str | None = None
) -> AppCommandResult:
    """Wrap ``archive_current_run`` and ``archive_run`` into an AppCommandResult."""

    from loopforge.engine import archive_current_run, archive_run

    if run_id:
        result = archive_run(ctx.project_dir, run_id)
    else:
        result = archive_current_run(ctx.project_dir)
    return _translate(
        "archive",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        data={
            "config_path": str(result.config_path),
            "archived_run_id": run_id,
        },
        effects=["archived run"] if result.ok else None,
    )
