"""Application command: verify the current run."""

from __future__ import annotations

from loopforge.commands.base import (
    CommandContext,
    _translate,
    register_command,
)
from loopforge.engine.models.commands import AppCommandResult


@register_command("verify")
def VerifyRun(
    ctx: CommandContext, *, confirmed: bool | None = None
) -> AppCommandResult:
    """Wrap ``verify_run`` into an AppCommandResult."""

    from loopforge.engine import verify_run

    result = verify_run(
        ctx.project_dir,
        confirmed=ctx.confirmed if confirmed is None else confirmed,
    )
    verification = (
        result.verification if isinstance(result.verification, dict) else {}
    )
    return _translate(
        "verify",
        ok=result.ok,
        message=result.message,
        blockers=result.blockers,
        project_dir=result.project_dir,
        run_id=str((result.run or {}).get("run_id") or "") or None,
        data={
            "run_dir": str(result.run_dir) if result.run_dir else None,
            "verification": verification,
            "status": str(verification.get("status") or ""),
            "checks_passed": verification.get("checks_passed"),
            "checks_total": verification.get("checks_total"),
        },
        effects=["verified run"] if result.ok else None,
    )
