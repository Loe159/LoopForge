"""Backend-neutral immutable state for interactive LoopForge frontends.

The engine remains the authority for workflow persistence.  This store owns
only navigation, cached read models, and publication of presentation-safe
snapshots.  Both prompt-toolkit and Textual can therefore consume the same
state without allowing workers to mutate widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable

from loopforge.cli.models import (
    EvidenceSnapshot,
    HomeSnapshot,
    OperationSnapshot,
    ProjectSnapshot,
    RunSnapshot,
    SettingsSnapshot,
    UiSnapshot,
)
from loopforge.cli.operations import OperationController, OperationEvent
from loopforge.cli.presentation import ShellSnapshot, shell_snapshot_from_status
from loopforge.engine import (
    StatusResult,
    list_registered_projects,
    list_runs_all_projects,
    list_runs_from_status,
)
from loopforge.engine.git_state import DEFAULT_GIT_STATE_SERVICE


@dataclass(frozen=True)
class LoadIdentity:
    """Identifies an asynchronous load and prevents stale publication."""

    project: Path
    run_id: str | None
    generation: int


SnapshotListener = Callable[[UiSnapshot], None]


class StateStore:
    """Own read models and publish only observable state changes.

    ``refresh`` is intentionally synchronous. A Textual worker may call
    :meth:`begin_load` and then use
    :meth:`publish_loaded` on its UI thread.  The identity guard discards a
    late result after navigation.
    """

    def __init__(
        self,
        project: Path,
        *,
        status_loader: Callable[[Path], StatusResult] | None = None,
        runs_loader: Callable[[StatusResult], Any] | None = None,
        projects_loader: Callable[[], Any] | None = None,
        global_runs_loader: Callable[[], Any] | None = None,
        branch_loader: Callable[[Path], str | None] | None = None,
    ) -> None:
        from loopforge.engine import current_status

        self._status_loader = status_loader or current_status
        self._runs_loader = runs_loader or list_runs_from_status
        self._projects_loader = projects_loader or list_registered_projects
        self._global_runs_loader = global_runs_loader or list_runs_all_projects
        self._branch_loader = branch_loader or (
            lambda path: DEFAULT_GIT_STATE_SERVICE.get(path).branch
        )
        self._selected_project = project.resolve()
        self._selected_run_id: str | None = None
        self._generation = 0
        self._revision = 0
        self._listeners: list[SnapshotListener] = []
        self._pending_reasons: set[str] = set()
        self._status: StatusResult | None = None
        self._runs: tuple[MappingProxyType[str, Any], ...] = ()
        self._project_rows: tuple[MappingProxyType[str, Any], ...] = ()
        self._global_runs: tuple[MappingProxyType[str, Any], ...] = ()
        self._run_blockers: tuple[str, ...] = ()
        self._branch = "no Git branch"
        self._evidence = EvidenceSnapshot("empty")
        self._operation = OperationSnapshot()
        self._snapshot = self._build_snapshot(reasons=("initial",))

    @property
    def snapshot(self) -> UiSnapshot:
        return self._snapshot

    @property
    def status(self) -> StatusResult | None:
        return self._status

    @property
    def runs(self) -> tuple[MappingProxyType[str, Any], ...]:
        return self._runs

    @property
    def project_rows(self) -> tuple[MappingProxyType[str, Any], ...]:
        return self._project_rows

    @property
    def run_blockers(self) -> tuple[str, ...]:
        return self._run_blockers

    def subscribe(self, listener: SnapshotListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def select_project(self, project: Path) -> LoadIdentity:
        self._selected_project = project.resolve()
        self._selected_run_id = None
        self._generation += 1
        # Preserve Home rows, but never render the old project's workflow as
        # though it belonged to the newly selected project while its load is in
        # flight.
        self._status = None
        self._runs = ()
        self._run_blockers = ()
        self._branch = "no Git branch"
        self._evidence = EvidenceSnapshot("empty")
        self.invalidate("project-selection")
        self.flush()
        return self.begin_load()

    def select_run(self, run_id: str | None) -> LoadIdentity:
        self._selected_run_id = run_id or None
        self._generation += 1
        self.invalidate("run-selection")
        self.flush()
        return self.begin_load()

    def begin_load(self) -> LoadIdentity:
        return LoadIdentity(self._selected_project, self._selected_run_id, self._generation)

    def accepts(self, identity: LoadIdentity) -> bool:
        return identity == self.begin_load()

    def invalidate(self, reason: str) -> None:
        self._pending_reasons.add(reason)

    def refresh(self, project: Path | None = None, *, reason: str = "refresh") -> UiSnapshot:
        if project is not None and project.resolve() != self._selected_project:
            self.select_project(project)
        identity = self.begin_load()
        status = self._status_loader(identity.project)
        runs_result = self._runs_loader(status)
        projects_result = self._projects_loader()
        global_runs_result = self._global_runs_loader()
        return self.publish_loaded(
            identity,
            status,
            runs_result,
            projects_result,
            global_runs_result=global_runs_result,
            reason=reason,
        )

    def publish_loaded(
        self,
        identity: LoadIdentity,
        status: StatusResult,
        runs_result: Any,
        projects_result: Any,
        *,
        global_runs_result: Any | None = None,
        reason: str = "load",
    ) -> UiSnapshot:
        """Publish a completed load only if it still targets current navigation."""

        if not self.accepts(identity):
            return self._snapshot
        shell = shell_snapshot_from_status(status)
        rows = [_frozen_row(row) for row in getattr(projects_result, "projects", ())]
        if not any(_row_path(row) == identity.project for row in rows):
            rows.insert(
                0,
                _frozen_row(
                    {
                        "name": identity.project.name,
                        "path": str(identity.project),
                        "initialized": status.initialized,
                        "run_count": len(getattr(runs_result, "runs", ())),
                        "attention": shell.family,
                        "branch": self._branch_loader(identity.project),
                        "last_activity": "current session",
                    }
                ),
            )
        run_dir_changed = self._status is not None and self._status.run_dir != status.run_dir
        self._status = status
        self._runs = tuple(_frozen_row(row) for row in getattr(runs_result, "runs", ()))
        self._run_blockers = tuple(str(value) for value in getattr(runs_result, "blockers", ()))
        self._project_rows = tuple(rows)
        if global_runs_result is not None:
            self._global_runs = tuple(
                _frozen_row(row) for row in getattr(global_runs_result, "runs", ())
            )
        record = next((row for row in rows if _row_path(row) == identity.project), None)
        self._branch = str(
            (record or {}).get("branch")
            or self._branch_loader(identity.project)
            or "no Git branch"
        )
        if run_dir_changed:
            self._evidence = EvidenceSnapshot("empty")
        self.invalidate(reason)
        return self.flush(shell=shell)

    def set_evidence(
        self,
        items: Iterable[Any],
        *,
        query: str = "",
        state: str = "ready",
        publish: bool = True,
    ) -> UiSnapshot:
        self._evidence = EvidenceSnapshot(state, tuple(items), query)
        self.invalidate("evidence")
        return self.flush() if publish else self._snapshot

    def set_operation(self, operation: OperationController | None) -> UiSnapshot:
        if operation is None:
            self._operation = OperationSnapshot()
        else:
            self._operation = _operation_snapshot(operation, operation.history)
        self.invalidate("operation")
        return self.flush()

    def record_operation_events(self, operation: OperationController) -> UiSnapshot:
        """Coalesce worker events; caller flushes once per UI-loop turn."""

        operation.collect_events()
        self._operation = _operation_snapshot(operation, operation.history)
        self.invalidate("operation-event")
        return self._snapshot

    def flush(self, *, shell: ShellSnapshot | None = None) -> UiSnapshot:
        shell = shell or (
            shell_snapshot_from_status(self._status)
            if self._status is not None
            else None
        )
        reasons = tuple(sorted(self._pending_reasons))
        # Invalidation reasons explain a publication; they do not themselves
        # make state observable.  Compare the actual view model first so an
        # unchanged refresh does not cause repaint churn.
        candidate = self._build_snapshot(
            shell=shell,
            reasons=self._snapshot.reasons,
            revision=self._snapshot.revision,
        )
        self._pending_reasons.clear()
        if candidate == self._snapshot:
            return self._snapshot
        self._revision += 1
        self._snapshot = self._build_snapshot(shell=shell, reasons=reasons, revision=self._revision)
        for listener in tuple(self._listeners):
            listener(self._snapshot)
        return self._snapshot

    def _build_snapshot(
        self,
        *,
        shell: ShellSnapshot | None = None,
        reasons: tuple[str, ...] = (),
        revision: int | None = None,
    ) -> UiSnapshot:
        shell = shell or (
            shell_snapshot_from_status(self._status)
            if self._status is not None
            else None
        )
        project_state = "blocked" if self._run_blockers else "ready" if shell else "loading"
        run_state = "empty" if shell is None or shell.run is None else project_state
        home_state = "empty" if not self._project_rows else "ready"
        return UiSnapshot(
            revision=self._revision if revision is None else revision,
            reasons=reasons,
            selected_project=self._selected_project,
            selected_run_id=self._selected_run_id,
            home=HomeSnapshot(home_state, self._project_rows, (), self._global_runs),
            project=ProjectSnapshot(
                project_state,
                self._selected_project,
                shell,
                self._runs,
                self._run_blockers,
                self._branch,
            ),
            run=RunSnapshot(run_state, shell),
            evidence=self._evidence,
            settings=SettingsSnapshot(),
            operation=self._operation,
        )


def _frozen_row(value: Any) -> MappingProxyType[str, Any]:
    return MappingProxyType(dict(value) if isinstance(value, dict) else {})


def _row_path(row: MappingProxyType[str, Any]) -> Path | None:
    try:
        return Path(str(row.get("path") or "")).resolve()
    except OSError:
        return None


def _operation_snapshot(
    operation: OperationController,
    events: tuple[OperationEvent, ...],
) -> OperationSnapshot:
    if not operation.finished:
        state = "loading"
    elif operation.error is not None:
        state = "failed"
    elif operation.cancel_event.is_set() and not bool(getattr(operation.result, "ok", False)):
        state = "blocked"
    else:
        state = "ready" if bool(getattr(operation.result, "ok", False)) else "blocked"
    message = events[-1].message if events else operation.label
    return OperationSnapshot(
        state,
        operation.operation_id,
        operation.label,
        events,
        operation.finished,
        operation.cancel_event.is_set(),
        message,
    )
