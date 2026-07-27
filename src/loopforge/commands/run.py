"""Application commands: start and resume runs."""

from __future__ import annotations

from typing import Any

from loopforge.commands.base import (
    CommandContext,
    _failed,
    _ok,
    _scope,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("start_run")
def StartRun(
    ctx: CommandContext,
    *,
    task: str,
    pack: str | None = None,
    success_checks: list[str] | None = None,
    selected_skills: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    max_attempts: int = 3,
    timeout_seconds: int = 1800,
    subjective_rubric: str = "",
    source_metadata: dict[str, Any] | None = None,
    initial_approval: dict[str, Any] | None = None,
) -> AppCommandResult:
    """Wrap ``create_run`` into an AppCommandResult."""

    from loopforge.engine import create_run

    try:
        result = create_run(
            ctx.project_dir,
            task,
            pack=pack,
            success_checks=success_checks,
            selected_skills=selected_skills,
            allowed_tools=allowed_tools,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            subjective_rubric=subjective_rubric,
            source_metadata=source_metadata,
            initial_approval=initial_approval,
        )
    except (ValueError, FileNotFoundError) as error:
        return _failed("start_run", str(error))

    run_id = str(result.run.get("run_id") or "")
    project_id = str(result.config.get("project_id") or "")
    return _ok(
        "start_run",
        _scope(result.project_dir, project_id, run_id),
        {
            "run_id": run_id,
            "run_dir": str(result.run_dir),
            "task": str(result.run.get("task") or ""),
            "pack": str(result.run.get("pack") or ""),
            "status": str(result.run.get("status") or ""),
        },
        effects=["created run"],
    )


@register_command("resume_run")
def ResumeRun(ctx: CommandContext, *, run_id: str) -> AppCommandResult:
    """Wrap ``resume_run`` into an AppCommandResult."""

    from loopforge.engine import resume_run

    result = resume_run(ctx.project_dir, run_id)
    actual_id = ""
    if result.run is not None:
        actual_id = str(result.run.get("run_id") or "")
    return _translate(
        "resume_run",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=actual_id or None,
        data={
            "run_id": actual_id,
            "run_dir": str(result.run_dir) if result.run_dir else None,
        },
        effects=["resumed run"] if result.ok else None,
    )
