"""Worker-safe operations used by the Textual shell.

The functions in this module may touch engine services, but widgets never do.
They return immutable snapshots which the app publishes on its UI thread.
"""

from __future__ import annotations

from pathlib import Path

from loopforge.cli.models import UiSnapshot
from loopforge.cli.state_store import StateStore


def load_project_snapshot(store: StateStore, project: Path | None = None) -> UiSnapshot:
    """Refresh one selected project outside a Textual event handler."""

    return store.refresh(project, reason="textual-load")
