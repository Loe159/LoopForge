"""Typed models for app command results and errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AppCommandError:
    """Structured error produced by an app command."""

    code: str
    message: str
    remediation: str
    recoverable: bool

    _KNOWN_KEYS = frozenset({"code", "message", "remediation", "recoverable"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "recoverable": self.recoverable,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppCommandError:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            code=data["code"],
            message=data["message"],
            remediation=data["remediation"],
            recoverable=data["recoverable"],
        )


@dataclass(frozen=True)
class AppCommandResult:
    """Structured result of an app command execution."""

    command: str
    ok: bool
    target: Any  # ActionScope, typed as Any to avoid circular import
    new_revision: int | None
    data: Any
    errors: list[AppCommandError] = field(default_factory=list)
    next_actions: list[Any] = field(default_factory=list)  # ActionDescriptor, typed as Any
    effects: list[str] = field(default_factory=list)

    _KNOWN_KEYS = frozenset(
        {
            "command",
            "ok",
            "target",
            "new_revision",
            "data",
            "errors",
            "next_actions",
            "effects",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        def _serialize(value: Any) -> Any:
            if hasattr(value, "to_dict"):
                return value.to_dict()
            return value

        return {
            "command": self.command,
            "ok": self.ok,
            "target": _serialize(self.target),
            "new_revision": self.new_revision,
            "data": _serialize(self.data),
            "errors": [_serialize(error) for error in self.errors],
            "next_actions": [_serialize(action) for action in self.next_actions],
            "effects": list(self.effects),
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppCommandResult:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        raw_errors = data.get("errors", []) or []
        errors = [
            AppCommandError.from_dict(error) if isinstance(error, dict) else error
            for error in raw_errors
        ]
        return cls(
            command=data["command"],
            ok=data["ok"],
            target=data.get("target"),
            new_revision=data.get("new_revision"),
            data=data.get("data"),
            errors=errors,
            next_actions=list(data.get("next_actions", []) or []),
            effects=list(data.get("effects", []) or []),
        )
