"""Application command: execute a read-only workflow stage."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("execute_stage")
def ExecuteStage(
    ctx: CommandContext,
    *,
    stage: str,
    adapter: str | None = None,
    adapter_args: list[str] | None = None,
) -> AppCommandResult:
    """Wrap ``execute_readonly_stage`` into an AppCommandResult."""

    from loopforge.engine import (
        current_status,
        execute_readonly_stage,
        next_readonly_stage,
    )

    if adapter is None:
        status = current_status(ctx.project_dir)
        config = status.config or {}
        adapter = str(config.get("default_adapter") or "codex")
        if adapter_args is None:
            raw_args = config.get("default_adapter_args")
            if isinstance(raw_args, list) and raw_args:
                adapter_args = [str(value) for value in raw_args]

    result = execute_readonly_stage(
        ctx.project_dir,
        stage=stage,
        adapter=adapter,
        adapter_args=adapter_args,
    )

    next_stage = None
    if result.run is not None:
        next_stage = next_readonly_stage(result.run)

    return _translate(
        "execute_stage",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=str((result.run or {}).get("run_id") or "") or None,
        data={
            "stage": str(result.stage or stage),
            "adapter": adapter,
            "run_dir": str(result.run_dir) if result.run_dir else None,
            "artifact_path": (
                str(result.artifact_path) if result.artifact_path else None
            ),
            "next_stage": next_stage,
        },
        effects=[f"executed {stage} stage"] if result.ok else None,
    )
