"""Textual screens rendered exclusively from immutable LoopForge snapshots."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable, Iterable

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Container
from textual.events import Resize
from textual.widgets import Footer, Header, Static

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.evidence import EvidenceIndex, EvidenceItem, approval_summary
from loopforge.cli.models import UiSnapshot
from loopforge.cli.operations import OperationController
from loopforge.cli.presentation import FAMILY_PRESENTATION
from loopforge.cli.state_store import StateStore
from loopforge.cli.textual_app.messages import LoadFailed, SnapshotPublished
from loopforge.cli.textual_app.screens import (
    ConfirmationScreen,
    RecoverableErrorScreen,
    TextEntryScreen,
)
from loopforge.cli.textual_app.workers import load_project_snapshot
from loopforge.cli.ui import TerminalRenderer

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


SCREENS = ("home", "project", "run", "evidence", "settings")


class LoopForgeActionProvider(Provider):
    """Expose the shared action descriptors in Textual's command palette."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for action in self.app.available_actions:
            score = matcher.match(f"{action.label} {action.id}")
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(action.label),
                    lambda action=action: self.app.request_action(action),
                    text=action.label,
                    help=action.description,
                )

    async def discover(self) -> Hits:
        for action in self.app.available_actions:
            yield DiscoveryHit(
                action.label,
                lambda action=action: self.app.request_action(action),
                help=action.description,
            )


class LoopForgeApp(App[None]):
    """Keyboard-first Textual migration with no engine work in render callbacks."""

    TITLE = "LoopForge"
    CSS_PATH = str(Path(__file__).with_name("styles.tcss"))
    COMMANDS = App.COMMANDS | {LoopForgeActionProvider}
    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Actions", show=True),
        Binding("ctrl+p", "show_home", "Projects", show=True),
        Binding("enter", "open_selected", "Open", show=True),
        Binding("up,k", "move_up", "Up", show=False),
        Binding("down,j", "move_down", "Down", show=False),
        Binding("n", "new_run", "New run", show=True),
        Binding("a", "archive", "Archive", show=False),
        Binding("e", "show_evidence", "Evidence", show=False),
        Binding("s", "show_settings", "Settings", show=False),
        Binding("slash", "command", "Command", show=True),
        Binding("f", "filter", "Filter", show=False),
        Binding("c", "copy_evidence", "Copy", show=False),
        Binding("x", "export_evidence", "Export", show=False),
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+c", "cancel_or_exit", "Cancel / exit", show=True),
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
        self._operation_completion_handled = False
        self._screen = "home"
        self._selected_index = 0
        self._filter = ""
        self._evidence_index: EvidenceIndex | None = None
        self._evidence_preview = ""
        self._notice = ""
        self._unsubscribe: Callable[[], None] | None = self.store.subscribe(self._post_snapshot)

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
            yield Static(id="screen-notice", classes="secondary")
            yield Static(id="screen-help", classes="secondary")
        yield Footer()

    def on_mount(self) -> None:
        self._set_width_class(self.size.width)
        self._render_snapshot(self._snapshot)
        self.set_interval(0.12, self._poll_operation)
        if self._load_on_mount:
            self.load_selected_project()

    def on_resize(self, event: Resize) -> None:
        self._set_width_class(event.size.width)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _post_snapshot(self, snapshot: UiSnapshot) -> None:
        self.post_message(SnapshotPublished(snapshot))

    @on(SnapshotPublished)
    def _on_snapshot_published(self, message: SnapshotPublished) -> None:
        self._render_snapshot(message.snapshot)

    @on(LoadFailed)
    def _on_load_failed(self, message: LoadFailed) -> None:
        self.push_screen(RecoverableErrorScreen(message.message))

    @work(thread=True, exclusive=True, group="project-load", exit_on_error=False)
    def load_selected_project(self, project: Path | None = None) -> None:
        try:
            load_project_snapshot(self.store, project)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def select_project(self, project: Path) -> None:
        """Navigate immediately; its project read remains a worker operation."""

        project = project.resolve()
        self.shell.project_dir = project
        self.store.select_project(project)
        self._screen = "project"
        self._selected_index = 0
        self.load_selected_project(project)

    @work(thread=True, exclusive=True, group="run-load", exit_on_error=False)
    def _open_run_worker(self, run_id: str) -> None:
        try:
            from loopforge.engine import resume_run

            result = resume_run(self.shell.project_dir, run_id)
            if not result.ok:
                raise RuntimeError(result.message)
            self.store.select_run(run_id)
            load_project_snapshot(self.store, self.shell.project_dir)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    @work(thread=True, exclusive=True, group="evidence-load", exit_on_error=False)
    def _load_evidence_worker(self, query: str = "") -> None:
        try:
            status = self.store.status
            index = EvidenceIndex.build(status.run_dir if status is not None else None)
            self._evidence_index = index
            if not query.strip():
                self.store.set_evidence(index.items, query="")
                return
            for items in index.search_batches(query):
                self.store.set_evidence(items, query=query, state="ready")
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    @work(thread=True, exclusive=True, group="evidence-preview", exit_on_error=False)
    def _open_evidence_worker(self, item: EvidenceItem) -> None:
        try:
            if self._evidence_index is None:
                return
            preview = self._evidence_index.preview(item, query=self._snapshot.evidence.query)
            self.call_from_thread(self._set_evidence_preview, preview)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _set_evidence_preview(self, preview: str) -> None:
        self._evidence_preview = preview
        self._render_snapshot(self._snapshot)

    def action_move_up(self) -> None:
        self._move(-1)

    def action_move_down(self) -> None:
        self._move(1)

    def _move(self, delta: int) -> None:
        items = self._screen_items()
        if items:
            self._selected_index = (self._selected_index + delta) % len(items)
        self._render_snapshot(self._snapshot)

    def action_show_home(self) -> None:
        self._screen = "home"
        self._selected_index = 0
        self._render_snapshot(self._snapshot)

    def action_show_evidence(self) -> None:
        if self._screen != "run" or self.store.status is None or self.store.status.run_dir is None:
            self._notice = "Open a run to view its evidence."
            self._render_snapshot(self._snapshot)
            return
        self._screen = "evidence"
        self._selected_index = 0
        self._evidence_preview = ""
        self._load_evidence_worker(self._snapshot.evidence.query)
        self._render_snapshot(self._snapshot)

    def action_show_settings(self) -> None:
        self._screen = "settings"
        self._selected_index = 0
        self._render_snapshot(self._snapshot)

    def action_go_back(self) -> None:
        if self._screen == "evidence" and self._evidence_preview:
            self._evidence_preview = ""
        else:
            self._screen = {"home": "home", "project": "home", "run": "project", "evidence": "run", "settings": "run"}[self._screen]
            self._selected_index = 0
        self._render_snapshot(self._snapshot)

    def action_open_selected(self) -> None:
        if self._screen == "home":
            projects = self._filtered_projects()
            if projects:
                self.select_project(Path(str(projects[self._selected_index].get("path") or self.shell.project_dir)))
            return
        if self._screen == "project":
            runs = self._filtered_runs()
            if runs:
                run_id = str(runs[self._selected_index].get("run_id") or "")
                if run_id:
                    self._screen = "run"
                    self._selected_index = 0
                    self._open_run_worker(run_id)
            return
        if self._screen == "run":
            action = self._snapshot.run.shell.run.next_action if self._snapshot.run.shell and self._snapshot.run.shell.run else None
            if action is not None:
                self.request_action(action)
            return
        if self._screen == "evidence":
            items = self._visible_evidence()
            if items:
                self._open_evidence_worker(items[self._selected_index])

    def action_new_run(self) -> None:
        self.push_screen(
            TextEntryScreen("Create run", "Describe the task for this supervised workflow.", submit_label="Create"),
            self._create_run,
        )

    def _create_run(self, task: str | None) -> None:
        if task is None or not task.strip():
            return
        self._run_shell_operation("Create run", lambda: self.shell.cmd_run(task.strip()))

    def action_command(self) -> None:
        """Open the existing slash-command surface from the full-screen UI."""

        self.push_screen(
            TextEntryScreen(
                "Run LoopForge command",
                "Enter a slash command, for example /status or /report --help.",
                value="/",
                submit_label="Run",
            ),
            self._run_slash_command,
        )

    def _run_slash_command(self, command: str | None) -> None:
        if command is None or not command.strip():
            return
        line = command.strip()
        if not line.startswith("/"):
            line = f"/{line}"
        self._run_shell_operation("Run command", lambda: self._dispatch_slash_command(line))

    def _dispatch_slash_command(self, line: str) -> SimpleNamespace:
        """Route through the compatibility shell without writing over Textual's screen."""

        captured = io.StringIO()
        original_output = self.shell.output
        original_error = self.shell.error
        original_renderer = self.shell.renderer
        self.shell.output = captured
        self.shell.error = captured
        self.shell.renderer = TerminalRenderer(captured, mode="plain", theme=self.shell.theme)
        try:
            result = self.shell.dispatch(line)
        finally:
            self.shell.output = original_output
            self.shell.error = original_error
            self.shell.renderer = original_renderer
        output = captured.getvalue().strip()
        if len(output) > 1200:
            output = output[:1197] + "..."
        return SimpleNamespace(
            exit_code=result.exit_code,
            should_exit=result.should_exit,
            message=output or ("Command completed." if result.exit_code == 0 else "Command was blocked."),
        )

    def action_filter(self) -> None:
        value = self._snapshot.evidence.query if self._screen == "evidence" else self._filter
        self.push_screen(TextEntryScreen("Filter", "Filter the current list.", value=value), self._apply_filter)

    def _apply_filter(self, value: str | None) -> None:
        if value is None:
            return
        self._selected_index = 0
        if self._screen == "evidence":
            self._evidence_preview = ""
            self._load_evidence_worker(value)
        else:
            self._filter = value.strip()
        self._render_snapshot(self._snapshot)

    def action_archive(self) -> None:
        if self._screen != "project" and self._screen != "run":
            return
        lines = ("Archive the selected run?", "The run remains available in history and can be inspected later.")
        self.push_screen(ConfirmationScreen("Archive run", lines, approve_label="Archive"), self._archive_confirmed)

    def _archive_confirmed(self, approved: bool) -> None:
        if approved:
            self._run_shell_operation("Archive run", lambda: self.shell.cmd_archive())

    def request_action(self, action: ActionDescriptor) -> None:
        if action.executor_key == "collect-task":
            self.action_new_run()
            return
        if not action.requires_confirmation:
            self._execute_action(action)
            return
        self._load_confirmation(action)

    @work(thread=True, exclusive=True, group="confirmation", exit_on_error=False)
    def _load_confirmation(self, action: ActionDescriptor) -> None:
        try:
            stages = {"approve-plan": "plan", "approve-review": "review"}
            stage = stages.get(action.id)
            status = self.store.status
            if stage and status is not None:
                summary = approval_summary(status.run_dir, status.run, stage)
                title, lines = summary.title, summary.lines
            else:
                title = f"{action.label}?"
                lines = (action.description, "Permissions follow the selected pack and stage.", "This remains a local LoopForge action.")
            self.call_from_thread(self._show_confirmation, action, title, lines)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _show_confirmation(self, action: ActionDescriptor, title: str, lines: tuple[str, ...]) -> None:
        self.push_screen(ConfirmationScreen(title, lines), lambda approved: self._execute_action(action) if approved else None)

    def _execute_action(self, action: ActionDescriptor) -> None:
        self._run_shell_operation(action.label, lambda: self.shell.execute_guided_action(action))

    def _run_shell_operation(self, label: str, runner: Callable[[], object]) -> None:
        if self._operation is not None and not self._operation.finished:
            self._notice = "A foreground operation is already running."
            self._render_snapshot(self._snapshot)
            return
        operation = OperationController(label)
        self.begin_operation(operation)
        operation.start(lambda emit, cancelled: _operation_result(runner(), cancelled.is_set()))

    def begin_operation(self, operation: OperationController) -> None:
        self._operation = operation
        self._operation_completion_handled = False
        self.store.set_operation(operation)

    def _poll_operation(self) -> None:
        if self._operation is None:
            return
        self.store.record_operation_events(self._operation)
        self.store.flush()
        if self._operation.finished and not self._operation_completion_handled:
            self._operation_completion_handled = True
            self._notice = self._snapshot.operation.message
            if bool(getattr(self._operation.result, "should_exit", False)):
                self.exit()
                return
            self.load_selected_project()

    def action_cancel_or_exit(self) -> None:
        if self._operation is not None and not self._operation.finished:
            self._operation.cancel()
            self.store.record_operation_events(self._operation)
            self.store.flush()
            return
        self.exit()

    def action_copy_evidence(self) -> None:
        if not self._evidence_preview:
            self._notice = "Open an evidence item before copying it."
        else:
            self.copy_to_clipboard(self._evidence_preview)
            self._notice = "Evidence copied to the clipboard."
        self._render_snapshot(self._snapshot)

    def action_export_evidence(self) -> None:
        items = self._visible_evidence()
        if self._screen != "evidence" or not items:
            self._notice = "Select evidence to export."
            self._render_snapshot(self._snapshot)
            return
        self._export_evidence_worker(items[self._selected_index])

    @work(thread=True, exclusive=True, group="evidence-export", exit_on_error=False)
    def _export_evidence_worker(self, item: EvidenceItem) -> None:
        try:
            import shutil

            status = self.store.status
            if status is None or status.run_dir is None:
                raise RuntimeError("No run is selected.")
            destination = status.run_dir / "artifacts" / "exports" / item.path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item.path, destination)
            self.call_from_thread(self._set_notice, f"Exported {destination.relative_to(status.run_dir)}")
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _set_notice(self, notice: str) -> None:
        self._notice = notice
        self._render_snapshot(self._snapshot)

    def _render_snapshot(self, snapshot: UiSnapshot) -> None:
        self._snapshot = snapshot
        title, body, help_text = self._screen_view(snapshot)
        self.query_one("#screen-title", Static).update(title)
        self.query_one("#screen-state", Static).update(f"{self._screen.title()} · {self._state_label(snapshot)}")
        self.query_one("#screen-body", Static).update(body)
        self.query_one("#screen-notice", Static).update(self._notice or self._operation_text(snapshot))
        self.query_one("#screen-help", Static).update(help_text)

    def _screen_view(self, snapshot: UiSnapshot) -> tuple[str, str, str]:
        if self._screen == "home":
            projects = self._filtered_projects()
            project_lines = _selected_lines(projects, self._selected_index, _project_line)
            recent = tuple(snapshot.home.runs[:5])
            recent_lines = [_run_line(row) for row in recent] or ["No recent runs."]
            body = "Projects\n" + ("\n".join(project_lines) or "No registered projects.")
            body += "\n\nRecent runs\n" + "\n".join(recent_lines)
            return "LoopForge", body, "Enter open · Ctrl+P projects · n new run · Ctrl+K actions"
        if self._screen == "project":
            project = snapshot.project.project or self.shell.project_dir
            runs = self._filtered_runs()
            body = f"{project.name} · {snapshot.project.branch} · {len(snapshot.project.runs)} runs\n\nRuns\n"
            body += "\n".join(_selected_lines(runs, self._selected_index, _run_line)) or "No runs yet. Press n to create one."
            if snapshot.project.blockers:
                body += "\n\nProject health\n" + "\n".join(f"× {item}" for item in snapshot.project.blockers)
            return project.name, body, "Enter open · / filter · n new · a archive · Esc projects"
        if self._screen == "run":
            shell = snapshot.run.shell
            if shell is None or shell.run is None:
                return "Run", "Loading run state…", "Esc runs"
            label, marker, _ = FAMILY_PRESENTATION[shell.family]
            stages = "\n".join(f"{stage.marker} {stage.title} — {stage.label} ({stage.actor})" for stage in shell.stages)
            blockers = "\n".join(f"× {item}" for item in shell.blockers)
            action = shell.run.next_action.label if shell.run.next_action is not None else "No action available"
            body = f"{shell.run.task}\n{marker} {label} · {shell.run.short_id} · {shell.run.actor}\n\nPipeline\n{stages or 'No workflow stages.'}\n\nNext action\n{action}"
            if blockers:
                body += "\n\nBlockers\n" + blockers
            return shell.run.task or "Run", body, "Enter action · e evidence · Ctrl+K actions · Esc runs"
        if self._screen == "evidence":
            items = self._visible_evidence()
            if self._evidence_preview:
                return "Evidence", self._evidence_preview, "Esc list · c copy · x export"
            body = "Evidence\n" + ("\n".join(_selected_lines(items, self._selected_index, _evidence_line)) or "No evidence available.")
            return "Evidence", body, "Enter open · / search · c copy · x export · Esc run"
        values = [
            ("Theme", getattr(self.shell, "theme", "default")),
            ("Statusline", getattr(self.shell, "statusline", "default")),
            ("Keymap", getattr(self.shell, "editing_mode", "emacs")),
            ("Adapter", getattr(self.shell, "selected_adapter", "default")),
            ("Project", str(snapshot.selected_project or self.shell.project_dir)),
            ("Git", snapshot.project.branch),
            ("Snapshot", str(snapshot.revision)),
        ]
        return "Settings and diagnostics", "\n".join(f"{key}: {value}" for key, value in values), "Esc run · Ctrl+P projects"

    def _screen_items(self) -> tuple[object, ...]:
        if self._screen == "home":
            return self._filtered_projects()
        if self._screen == "project":
            return self._filtered_runs()
        if self._screen == "evidence" and not self._evidence_preview:
            return self._visible_evidence()
        return ()

    def _filtered_projects(self) -> tuple[object, ...]:
        return _filter_rows(self._snapshot.home.projects, self._filter)

    def _filtered_runs(self) -> tuple[object, ...]:
        return _filter_rows(self._snapshot.project.runs, self._filter)

    def _visible_evidence(self) -> tuple[EvidenceItem, ...]:
        return tuple(self._snapshot.evidence.items)  # StateStore publishes only indexed items.

    def _state_label(self, snapshot: UiSnapshot) -> str:
        state = getattr(snapshot, self._screen).state
        return f"{state} · revision {snapshot.revision}"

    def _operation_text(self, snapshot: UiSnapshot) -> str:
        operation = snapshot.operation
        if operation.state == "empty":
            return ""
        progress = operation.events[-1] if operation.events else None
        suffix = ""
        if progress is not None and progress.current is not None and progress.total is not None:
            suffix = f" {progress.current}/{progress.total}"
        return f"{operation.label}{suffix} — {operation.message}"

    def _set_width_class(self, width: int) -> None:
        self.remove_class("width-60", "width-80", "width-120", "width-160")
        self.add_class(
            "width-60" if width < 80 else "width-80" if width < 120 else "width-120" if width < 160 else "width-160"
        )

    def _handle_exception(self, error: Exception) -> None:
        if self.is_running:
            self.call_after_refresh(self.push_screen, RecoverableErrorScreen(str(error)))
            return
        super()._handle_exception(error)


def _filter_rows(rows: Iterable[object], query: str) -> tuple[object, ...]:
    needle = query.strip().casefold()
    values = tuple(rows)
    if not needle:
        return values
    return tuple(row for row in values if needle in str(dict(row) if hasattr(row, "items") else row).casefold())


def _selected_lines(rows: Iterable[object], selected: int, formatter: Callable[[object], str]) -> list[str]:
    values = tuple(rows)
    if not values:
        return []
    selected = min(selected, len(values) - 1)
    return [("› " if index == selected else "  ") + formatter(row) for index, row in enumerate(values)]


def _project_line(row: object) -> str:
    value = dict(row) if hasattr(row, "items") else {}
    return f"{value.get('attention', 'ready')}  {value.get('name', 'unknown')} · {value.get('run_count', 0)} runs"


def _run_line(row: object) -> str:
    value = dict(row) if hasattr(row, "items") else {}
    return f"{value.get('attention', value.get('status', 'ready'))}  {value.get('task') or value.get('run_id', 'Untitled run')}"


def _evidence_line(item: object) -> str:
    return f"{getattr(item, 'label', 'File')}  {getattr(item, 'relative_path', '')}"


def _operation_result(value: object, cancelled: bool) -> SimpleNamespace:
    exit_code = getattr(value, "exit_code", 0)
    ok = not cancelled and exit_code == 0
    return SimpleNamespace(
        ok=ok,
        should_exit=bool(getattr(value, "should_exit", False)),
        message=(
            "Operation cancelled."
            if cancelled
            else str(getattr(value, "message", "Action completed." if ok else "Action was blocked."))
        ),
    )
