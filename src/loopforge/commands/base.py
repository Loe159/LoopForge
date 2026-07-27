"""Base infrastructure for application commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loopforge.engine.models.commands import AppCommandResult, AppCommandError
from loopforge.engine.models.scope import ActionScope


@dataclass(frozen=True)
class CommandContext:
    """Per-invocation context for application commands."""

    project_dir: Path
    home: Path | None = None
    confirmed: bool = False
    renderer: Any = None  # TerminalRenderer or None for headless
    streams: dict[str, Any] = field(default_factory=dict)


# Registry: command name -> callable
_REGISTRY: dict[str, Callable[..., AppCommandResult]] = {}


def register_command(name: str):
    """Decorator to register a command function."""

    def decorator(
        func: Callable[..., AppCommandResult]
    ) -> Callable[..., AppCommandResult]:
        _REGISTRY[name] = func
        return func

    return decorator


def execute_command(name: str, ctx: CommandContext, **kwargs) -> AppCommandResult:
    """Execute a registered command by name."""

    func = _REGISTRY.get(name)
    if func is None:
        return AppCommandResult(
            command=name,
            ok=False,
            target=None,
            new_revision=None,
            data={},
            errors=[
                AppCommandError(
                    code="UNKNOWN_COMMAND",
                    message=f"unknown command: {name}",
                    remediation="check available commands",
                    recoverable=False,
                )
            ],
            next_actions=[],
            effects=[],
        )
    return func(ctx, **kwargs)


def _ok(
    name: str,
    target: ActionScope | None,
    data: Any = None,
    effects: list[str] | None = None,
) -> AppCommandResult:
    """Build a success result."""

    return AppCommandResult(
        command=name,
        ok=True,
        target=target,
        new_revision=None,
        data=data or {},
        errors=[],
        next_actions=[],
        effects=effects or [],
    )


def _blocked(
    name: str,
    message: str,
    blockers: list[str],
    target: ActionScope | None = None,
) -> AppCommandResult:
    """Build a blocked result."""

    return AppCommandResult(
        command=name,
        ok=False,
        target=target,
        new_revision=None,
        data={},
        errors=[
            AppCommandError(
                code="BLOCKED",
                message=message,
                remediation="; ".join(blockers),
                recoverable=True,
            )
        ],
        next_actions=[],
        effects=[],
    )


def _failed(
    name: str,
    message: str,
    *,
    code: str = "FAILED",
    recoverable: bool = True,
    target: ActionScope | None = None,
) -> AppCommandResult:
    """Build a failure result for an engine error."""

    return AppCommandResult(
        command=name,
        ok=False,
        target=target,
        new_revision=None,
        data={},
        errors=[
            AppCommandError(
                code=code,
                message=message,
                remediation="",
                recoverable=recoverable,
            )
        ],
        next_actions=[],
        effects=[],
    )


def _scope(
    project_dir: Path,
    project_id: str | None,
    run_id: str | None = None,
) -> ActionScope | None:
    """Build an ActionScope target when a project identity is known."""

    if not project_id:
        return None
    return ActionScope(
        project_id=str(project_id),
        project_path=Path(project_dir),
        run_id=run_id or None,
    )


def _resolve_target(
    project_dir: Path | None, run_id: str | None = None
) -> ActionScope | None:
    """Resolve a target ActionScope from the on-disk project config."""

    if project_dir is None:
        return None
    try:
        from loopforge.engine import _load_config_scope

        scope = _load_config_scope(Path(project_dir))
    except Exception:
        return None
    if scope is None:
        return None
    if run_id:
        return ActionScope(
            project_id=scope.project_id,
            project_path=scope.project_path,
            run_id=run_id,
        )
    return scope


def _translate(
    name: str,
    *,
    ok: bool,
    message: str,
    blockers: list[str],
    project_dir: Path | None = None,
    run_id: str | None = None,
    target: ActionScope | None = None,
    data: dict[str, Any] | None = None,
    effects: list[str] | None = None,
) -> AppCommandResult:
    """Translate a common engine result shape (ok/message/blockers) into AppCommandResult."""

    if target is None and project_dir is not None:
        target = _resolve_target(project_dir, run_id)
    payload = dict(data or {})
    payload.setdefault("message", message)
    if ok:
        return _ok(name, target, payload, effects)
    return _blocked(name, message, list(blockers or []), target)
