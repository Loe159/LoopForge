"""Backend messages carrying immutable state-store publications."""

from __future__ import annotations

from textual.message import Message

from loopforge.cli.models import UiSnapshot


class SnapshotPublished(Message):
    """Deliver one state-store revision to the Textual UI thread."""

    def __init__(self, snapshot: UiSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot


class LoadFailed(Message):
    """Surface a background-load failure without terminating the console."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message
