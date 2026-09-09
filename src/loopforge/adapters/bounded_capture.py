"""Thread-safe combined output bounds for streamed adapter processes."""

from __future__ import annotations

import threading


class BoundedCapture:
    """Retain at most one combined byte budget across stdout and stderr."""

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("stream capture limit must be a positive integer")
        self.limit = limit
        self._captured = 0
        self._lock = threading.Lock()
        self.exceeded = threading.Event()

    @property
    def captured(self) -> int:
        with self._lock:
            return self._captured

    def append(self, buffer: bytearray, chunk: bytes) -> bytes:
        """Append the retained prefix of *chunk* and signal on overflow."""

        if not chunk:
            return b""
        with self._lock:
            remaining = max(0, self.limit - self._captured)
            retained = chunk[:remaining]
            if retained:
                buffer.extend(retained)
                self._captured += len(retained)
            if len(chunk) > remaining:
                self.exceeded.set()
            return retained
