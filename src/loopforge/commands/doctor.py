"""Application command: run project diagnostics."""

from __future__ import annotations

from typing import Any

from loopforge.commands.base import (
    CommandContext,
    _blocked,
    _ok,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("doctor")
def Doctor(
    ctx: CommandContext, *, rebuild_indexes: bool = False
) -> AppCommandResult:
    """Wrap ``run_doctor`` into an AppCommandResult."""

    from loopforge.engine import run_doctor

    data: dict[str, Any] = run_doctor(
        ctx.project_dir,
        ctx.home,
        rebuild_indexes_flag=rebuild_indexes,
    )
    if data.get("ok"):
        return _ok(
            "doctor",
            None,
            data,
            effects=(["rebuilt stale indexes"] if rebuild_indexes else None),
        )
    diagnostics = data.get("diagnostics") or []
    blockers = [
        str(item.get("message") or item)
        for item in diagnostics
        if isinstance(item, dict) and item.get("level") in {"error", "warning"}
    ] or [str(data.get("summary") or "LoopForge doctor reported issues.")]
    return _blocked("doctor", "LoopForge doctor found problems.", blockers)
