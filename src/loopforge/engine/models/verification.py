"""Typed model for the verification result produced by verify_run()."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    """Frozen representation of the verification dict from verify_run()."""

    status: str
    checks_passed: int
    checks_total: int
    finished_at: str | None
    stagnated: bool
    patch: dict[str, Any]
    details: dict[str, Any]
    started_at: str | None = None
    command: str | None = None

    _KNOWN_KEYS = frozenset(
        {
            "status",
            "checks_passed",
            "checks_total",
            "finished_at",
            "stagnated",
            "patch",
            "details",
            "started_at",
            "command",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "finished_at": self.finished_at,
            "stagnated": self.stagnated,
            "patch": self.patch,
            "details": self.details,
            "started_at": self.started_at,
            "command": self.command,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VerificationResult:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            status=data["status"],
            checks_passed=data["checks_passed"],
            checks_total=data["checks_total"],
            finished_at=data.get("finished_at"),
            stagnated=data["stagnated"],
            patch=dict(data.get("patch", {})),
            details=dict(data.get("details", {})),
            started_at=data.get("started_at"),
            command=data.get("command"),
        )
