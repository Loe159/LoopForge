"""Application command: initialize a LoopForge project."""

from __future__ import annotations

from loopforge.commands.base import CommandContext, _ok, _scope, register_command
from loopforge.engine.models.commands import AppCommandResult


@register_command("init")
def InitProject(
    ctx: CommandContext, *, profile: str = "supervised"
) -> AppCommandResult:
    """Wrap ``initialize_project`` into an AppCommandResult."""

    from loopforge.engine import initialize_project

    result = initialize_project(ctx.project_dir, profile=profile, home=ctx.home)
    project_id = str(result.config.get("project_id") or "")
    if result.created:
        effects = ["created project metadata"]
    elif result.repaired:
        effects = ["repaired project metadata"]
    else:
        effects = []
    return _ok(
        "init",
        _scope(result.project_dir, project_id),
        {
            "created": result.created,
            "repaired": result.repaired,
            "config_path": str(result.config_path),
            "config": result.config,
            "migrated_run_root": (
                str(result.migrated_run_root) if result.migrated_run_root else None
            ),
        },
        effects=effects,
    )
