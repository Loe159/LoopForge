"""Serializable lifecycle transition models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LifecycleTransition:
    """Serializable representation of a single lifecycle transition."""

    event: str
    from_stage: str
    to_stage: str | None
    ok: bool
    timestamp: str
    source: str
    blockers: list[str] = field(default_factory=list)

    _KNOWN_KEYS = frozenset(
        {
            "event",
            "from_stage",
            "to_stage",
            "ok",
            "timestamp",
            "source",
            "blockers",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "ok": self.ok,
            "timestamp": self.timestamp,
            "source": self.source,
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_dict(cls, data: dict) -> LifecycleTransition:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            event=data["event"],
            from_stage=data["from_stage"],
            to_stage=data.get("to_stage"),
            ok=data["ok"],
            timestamp=data["timestamp"],
            source=data["source"],
            blockers=list(data.get("blockers", [])),
        )


from loopforge.engine.lifecycle import (  # noqa: E402  (re-export at module bottom)
    LifecycleEvent,
    RunStage,
    StageStatus,
    TransitionResult,
)

__all__ = [
    "LifecycleTransition",
    "RunStage",
    "StageStatus",
    "LifecycleEvent",
    "TransitionResult",
]
