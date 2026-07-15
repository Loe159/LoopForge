"""Foreground-operation support for the full-screen console.

The engine remains synchronous and authoritative for lifecycle changes.  This
module only moves that synchronous work off prompt-toolkit's event loop and
turns its real progress callbacks into immutable UI events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class OperationEvent:
    """One factual foreground-operation update for the console."""

    operation_id: str
    kind: str
    message: str
    timestamp: datetime
    current: int | None = None
    total: int | None = None
    artifact: str | None = None
    status: str | None = None


OperationRunner = Callable[[Callable[[dict[str, Any]], None], Event], Any]


@dataclass
class ForegroundOperation:
    """Run one operation outside the UI loop with cooperative cancellation."""

    label: str
    operation_id: str = field(default_factory=lambda: f"op-{uuid4().hex[:12]}")
    cancel_event: Event = field(default_factory=Event)
    events: Queue[OperationEvent] = field(default_factory=Queue)
    started_at: float = field(default_factory=monotonic)
    result: Any = None
    error: BaseException | None = None
    finished: bool = False
    _thread: Thread | None = field(default=None, init=False, repr=False)

    def start(self, runner: OperationRunner) -> None:
        """Start ``runner`` once; it receives an event bridge and cancel token."""

        if self._thread is not None:
            raise RuntimeError("foreground operation is already running")

        def work() -> None:
            self.emit({"kind": "stage_started", "message": self.label})
            try:
                self.result = runner(self.emit, self.cancel_event)
                ok = bool(getattr(self.result, "ok", False))
                status = "completed" if ok else "blocked"
                if self.cancel_event.is_set() and not ok:
                    status = "cancelled"
                self.emit(
                    {
                        "kind": status,
                        "message": getattr(self.result, "message", self.label),
                        "status": status,
                    }
                )
            except BaseException as error:  # surfaced in the UI, never swallowed
                self.error = error
                self.emit({"kind": "failed", "message": str(error), "status": "failed"})
            finally:
                self.finished = True

        self._thread = Thread(target=work, name=self.operation_id, daemon=True)
        self._thread.start()

    def emit(self, payload: dict[str, Any]) -> None:
        """Accept engine callback payloads without coupling it to UI classes."""

        self.events.put(
            OperationEvent(
                operation_id=self.operation_id,
                kind=str(payload.get("kind") or "activity"),
                message=str(payload.get("message") or "Working…"),
                timestamp=datetime.now(timezone.utc),
                current=_integer_or_none(payload.get("current")),
                total=_integer_or_none(payload.get("total")),
                artifact=_text_or_none(payload.get("artifact")),
                status=_text_or_none(payload.get("status")),
            )
        )

    def cancel(self) -> None:
        """Request cooperative cancellation; the active child process is stopped."""

        if not self.cancel_event.is_set():
            self.cancel_event.set()
            self.emit({"kind": "cancellation_requested", "message": "Cancellation requested…"})

    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self.started_at)

    def drain_events(self) -> list[OperationEvent]:
        drained: list[OperationEvent] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except Empty:
                return drained


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
