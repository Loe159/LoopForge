"""Application command: open or register a project."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _blocked,
    _ok,
    _scope,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("open_project")
def OpenProject(
    ctx: CommandContext,
    *,
    target: str | None = None,
    identity_resolution: str | None = None,
) -> AppCommandResult:
    """Wrap ``open_project`` into an AppCommandResult."""

    from loopforge.engine import open_project

    result = open_project(
        target,
        current_project_dir=ctx.project_dir,
        home=ctx.home,
        identity_resolution=identity_resolution,
    )
    if result.ok and result.init is not None:
        project_id = str(result.init.config.get("project_id") or "")
        return _ok(
            "open_project",
            _scope(result.init.project_dir, project_id),
            {
                "created": result.init.created,
                "repaired": result.init.repaired,
                "config_path": str(result.init.config_path),
                "config": result.init.config,
                "message": result.message,
            },
            effects=["opened project"],
        )
    return _blocked("open_project", result.message, list(result.blockers))
