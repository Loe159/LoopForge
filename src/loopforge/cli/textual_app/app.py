"""Textual application shell backed exclusively by immutable snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Container
from textual.events import Resize
from textual.widgets import Footer, Header, Static

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.models import UiSnapshot
from loopforge.cli.operations import OperationController
from loopforge.cli.state_store import StateStore
from loopforge.cli.textual_app.messages import LoadFailed, SnapshotPublished
from loopforge.cli.textual_app.screens import RecoverableErrorScreen
from loopforge.cli.textual_app.workers import load_project_snapshot

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


class LoopForgeActionProvider(Provider):
    """Expose engine-derived actions through Textual's built-in palette."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for action in self.app.available_actions:
            score = matcher.match(f"{action.label} {action.id}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(action.label),
                    lambda action=action: self.app.show_action_summary(action),
                    text=action.label,
                    help=action.description,
                )

    async def discover(self) -> Hits:
        for action in self.app.available_actions:
            yield DiscoveryHit(
                action.label,
                lambda action=action: self.app.show_action_summary(action),
                help=action.description,
            )


class LoopForgeApp(App[None]):
    """Initial Textual backend with worker-only loading and safe recovery.

    Vertical feature slices will replace the summary widgets gradually. This
    shell intentionally consumes the exact ``StateStore`` and action models as
    the legacy backend; it never recreates workflow state from disk while
    rendering.
    """

    TITLE = "LoopForge"
    CSS_PATH = str(Path(__file__).with_name("styles.tcss"))
    COMMANDS = App.COMMANDS | {LoopForgeActionProvider}
    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Actions", show=True),
        Binding("ctrl+c", "cancel_or_exit", "Cancel / exit", show=True),
        Binding("escape", "return_home", "Home", show=True),
    ]

    def __init__(
        self,
        shell: "InteractiveShell",
        *,
        snapshot: UiSnapshot | None = None,
        load_on_mount: bool = True,
    ) -> None:
        super().__init__()
        self.shell = shell
        self.store = StateStore(shell.project_dir)
        self._snapshot = snapshot or self.store.snapshot
        self._load_on_mount = load_on_mount
        self._operation: OperationController | None = None
        self._unsubscribe: Callable[[], None] | None = self.store.subscribe(
            self._post_snapshot
        )

    @property
    def snapshot(self) -> UiSnapshot:
        return self._snapshot

    @property
    def available_actions(self) -> tuple[ActionDescriptor, ...]:
        shell = self._snapshot.run.shell
        return shell.actions if shell is not None else ()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="main-content"):
            yield Static(id="screen-title")
            yield Static(id="screen-state", classes="secondary")
            yield Static(id="screen-body")
            yield Static(id="action-summary", classes="secondary")
        yield Footer()

    def on_mount(self) -> None:
        self._set_width_class(self.size.width)
        self._render_snapshot(self._snapshot)
        if self._load_on_mount:
            self.load_selected_project()

    def on_resize(self, event: Resize) -> None:
        """Map the four required terminal breakpoints to stable CSS classes."""

        self._set_width_class(event.size.width)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _post_snapshot(self, snapshot: UiSnapshot) -> None:
        """Bridge StateStore publications without allowing workers to touch widgets."""

        self.post_message(SnapshotPublished(snapshot))

    @on(SnapshotPublished)
    def _on_snapshot_published(self, message: SnapshotPublished) -> None:
        self._render_snapshot(message.snapshot)

    @on(LoadFailed)
    def _on_load_failed(self, message: LoadFailed) -> None:
        self.push_screen(RecoverableErrorScreen(message.message))

    @work(thread=True, exclusive=True, group="project-load", exit_on_error=False)
    def load_selected_project(self, project: Path | None = None) -> None:
        """Load a project in a Textual worker and publish its immutable result."""

        try:
            load_project_snapshot(self.store, project)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def select_project(self, project: Path) -> None:
        """Start a new load identity; stale worker results are discarded by the store."""

        self.store.select_project(project)
        self.load_selected_project(project)

    def show_action_summary(self, action: ActionDescriptor) -> None:
        """Present shared action metadata without bypassing confirmation gates.

        Executing lifecycle actions is deliberately deferred to the phase-8
        approval and operation screens. This palette already has the same
        authoritative discovery catalog as the legacy interface.
        """

        confirmation = "confirmation required" if action.requires_confirmation else "ready"
        self.query_one("#action-summary", Static).update(
            f"{action.label} — {confirmation}. {action.description}"
        )

    def begin_operation(self, operation: OperationController) -> None:
        """Attach an existing backend-neutral operation for display/cancellation."""

        self._operation = operation
        self.store.set_operation(operation)

    def action_cancel_or_exit(self) -> None:
        if self._operation is not None and not self._operation.finished:
            self._operation.cancel()
            self.store.record_operation_events(self._operation)
            self.store.flush()
            return
        self.exit()

    def action_return_home(self) -> None:
        self.query_one("#action-summary", Static).update("")

    def _render_snapshot(self, snapshot: UiSnapshot) -> None:
        self._snapshot = snapshot
        shell = snapshot.run.shell
        title = shell.project.name if shell is not None else snapshot.selected_project.name if snapshot.selected_project else "LoopForge"
        state = snapshot.project.state
        if shell is None:
            body = "Loading project state…" if state == "loading" else "No run selected. Create a run to begin."
        else:
            run = shell.run
            stage_lines = [
                f"{stage.marker} {stage.title} — {stage.label} ({stage.actor})"
                for stage in shell.stages
            ]
            run_line = (
                f"{run.task} · {run.short_id} · {shell.family}"
                if run is not None
                else "No selected run"
            )
            body = "\n".join([run_line, "", *stage_lines] if stage_lines else [run_line])
        self.query_one("#screen-title", Static).update(title)
        self.query_one("#screen-state", Static).update(
            f"{state} · revision {snapshot.revision}"
        )
        self.query_one("#screen-body", Static).update(body)

    def _set_width_class(self, width: int) -> None:
        self.remove_class("width-60", "width-80", "width-120", "width-160")
        width_class = (
            "width-60"
            if width < 80
            else "width-80"
            if width < 120
            else "width-120"
            if width < 160
            else "width-160"
        )
        self.add_class(width_class)

    def _handle_exception(self, error: Exception) -> None:
        """Keep the last good snapshot visible behind a recoverable error screen."""

        if self.is_running:
            self.call_after_refresh(self.push_screen, RecoverableErrorScreen(str(error)))
            return
        super()._handle_exception(error)
