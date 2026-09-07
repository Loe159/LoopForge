"""Worker-safe operations used by the Textual shell.

The functions in this module may touch engine services, but widgets never do.
They return immutable snapshots which the app publishes on its UI thread.
"""

from __future__ import annotations

from pathlib import Path

from loopforge.cli.models import UiSnapshot
from loopforge.cli.state_store import LoadIdentity, StateStore


def _capture_identity(store: StateStore) -> LoadIdentity:
    return store.begin_load()


def _identity_stale(store: StateStore, identity: LoadIdentity) -> bool:
    return not store.accepts(identity)


def load_project_snapshot(
    store: StateStore,
    project: Path | None = None,
    *,
    lazy_global_runs: bool = False,
) -> UiSnapshot:
    """Load a project, publishing Home data early when requested."""

    if not lazy_global_runs:
        return store.refresh(project, reason="textual-load")

    if project is not None and project.resolve() != store.begin_load().project:
        store.select_project(project)
    identity = _capture_identity(store)
    primary = store.refresh(
        reason="textual-load",
        include_global_runs=False,
    )
    if _identity_stale(store, identity):
        return primary
    return store.refresh_global_runs(
        identity,
        reason="textual-global-runs-load",
    )
