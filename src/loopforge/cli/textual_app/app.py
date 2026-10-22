"""Textual screens rendered exclusively from immutable LoopForge snapshots."""

from __future__ import annotations

import io
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable, Iterable

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.binding import Binding
from textual.containers import Container
from textual.events import Resize
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Collapsible, Footer, Header, Input, OptionList, Select, Static
from textual.widgets._collapsible import CollapsibleTitle

from loopforge import __version__
from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.errors import persistence_error
from loopforge.engine.locking import LockTimeoutError
from loopforge.engine.repositories import RevisionConflictError
from loopforge.cli.evidence import EvidenceIndex, EvidenceItem, approval_summary
from loopforge.cli.models import UiSnapshot
from loopforge.cli.task_intake import TaskDraft, load_task_context
from loopforge.cli.operations import OperationController
from loopforge.cli.presentation import FAMILY_PRESENTATION
from loopforge.cli.state_store import StateStore
from loopforge.cli.run_projection import project_events
from loopforge.cli.textual_app.messages import LoadFailed, SnapshotPublished
from loopforge.cli.textual_app.command_palette import (
    LoopForgeCommandPalette,
    PaletteEntry,
    build_palette_entries,
)
from loopforge.cli.textual_app.run_presenter import (
    ascii_only as _ascii_only,
    compact_count as _compact_count,
    event_color as _event_color,
    event_marker as _event_marker,
    family_color as _family_color,
    run_activity_text as _run_activity_text,
    run_attempt_heading as _run_attempt_heading,
    run_glyph,
    execution_result,
    task_summary,
    run_progress as _run_progress,
    run_uptime as _run_uptime,
)
from loopforge.cli.textual_app.widgets import (
    HomeCommandBar,
    HomeCommandInput,
    HomeDashboard,
    HomeHeader,
    HomeHotkeyBar,
    HomeListPanel,
    HomeMetrics,
    RunActivityFeed,
    RunCommandBar,
    RunContextSidebar,
    RunDashboard,
    RunHeader,
    RunRequiredAction,
    RunToolEntry,
    RunFileChangeEntry,
    RunDelegationEntry,
    RunDocumentView,
    RunChangesExplorer,
    RunDetailEntry,
    ScreenList,
)
from loopforge.cli.textual_app.screens import (
    AdapterSelectionScreen,
    ConfirmationScreen,
    RecoverableErrorScreen,
    RunDetailScreen,
    RunSupervisionScreen,
    TextEntryScreen,
)
from loopforge.cli.textual_app.workers import load_project_snapshot, _identity_stale
from loopforge.cli.textual_app.task_composer import TaskComposer
from loopforge.cli.textual_app.settings import SettingsDashboard
from loopforge.cli.ui import TerminalRenderer
from loopforge.engine import (
    AGENT_COMMANDS,
    ActionScope,
    DEFAULT_AGENT_EXECUTION_MODE,
    SUPPORTED_ADAPTERS,
    SUPPORTED_PROFILES,
    current_status,
    loopforge_home,
    profile_policy,
    set_default_adapter,
    user_preferences_path,
)

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


SCREENS = ("home", "project", "run", "evidence", "settings")


TEXTUAL_THEME_BY_PREFERENCE = {
    # The ANSI themes leave surface and panel colors at the terminal default.
    # That lets the full-screen console inherit a black, blue, white, or custom
    # terminal background instead of painting Textual's own backdrop over it.
    "default": "ansi-dark",
    "dark": "ansi-dark",
    "light": "ansi-light",
    "mono": "ansi-dark",
}


def textual_theme_name(preference: str) -> str:
    """Return the terminal-native Textual theme for a LoopForge preference."""

    return TEXTUAL_THEME_BY_PREFERENCE.get(preference, TEXTUAL_THEME_BY_PREFERENCE["default"])


EXPERT_COMMANDS = (
    ("/context", "Compact run context"),
    ("/diff", "Show pending diff"),
    ("/fork", "Fork this run"),
    ("/permissions", "Show permissions"),
    ("/report", "Generate evidence report"),
)


class LoopForgeApp(App[None]):
    HOME_DETAILS_DELAY = 0.15

    """Keyboard-first Textual migration with no engine work in render callbacks."""

    TITLE = "LoopForge"
    CSS_PATH = [Path(__file__).with_name(name) for name in ("styles.tcss", "settings.tcss")]
    COMMANDS = set()  # Ctrl+K opens the LoopForge modal, not Textual's stock palette.
    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Actions", show=True),
        Binding("f4", "run_detail", "Detail", show=False),
        Binding("f6", "run_supervision", "Supervision", show=False),
        Binding("end", "run_follow", "Follow live", show=False),
        Binding("ctrl+enter", "run_required_action", "Required action", show=False),
        Binding("ctrl+p", "show_home", "Projects", show=True),
        Binding("enter", "home_open_selected", show=False, priority=True),
        Binding("up,k", "home_move_up", show=False, priority=True),
        Binding("down,j", "home_move_down", show=False, priority=True),
        Binding("left,h", "home_move_left", show=False, priority=True),
        Binding("right,l", "home_move_right", show=False, priority=True),
        Binding("n,ctrl+n", "home_new_run", show=False, priority=True),
        Binding("slash", "home_command", show=False, priority=True),
        Binding("enter", "root_open_selected", show=False, priority=True),
        Binding("up,k", "root_move_up", show=False, priority=True),
        Binding("down,j", "root_move_down", show=False, priority=True),
        Binding("n,ctrl+n", "root_new_run", show=False, priority=True),
        Binding("a", "root_archive", show=False, priority=True),
        Binding("e", "root_show_evidence", show=False, priority=True),
        Binding("s", "root_show_settings", show=False, priority=True),
        Binding("slash", "root_command", show=False, priority=True),
        Binding("escape", "root_go_back", show=False, priority=True),
        Binding("ctrl+c", "root_cancel_or_exit", show=False, priority=True),
        Binding("enter", "open_selected", "Open", show=True),
        Binding("up,k", "move_up", "Up", show=False),
        Binding("down,j", "move_down", "Down", show=False),
        Binding("left,h", "move_left", "Projects", show=False),
        Binding("right,l", "move_right", "Runs", show=False),
        Binding("n,ctrl+n", "new_run", "New run", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("a", "archive", "Archive", show=False),
        Binding("e", "show_evidence", "Evidence", show=False),
        Binding("s", "show_settings", "Settings", show=False),
        Binding("slash", "command", "Command", show=True),
        Binding("f", "filter", "Filter", show=False),
        Binding("c", "copy_evidence", "Copy", show=False),
        Binding("x", "export_evidence", "Export", show=False),
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+c", "cancel_or_exit", "Cancel / exit", show=True, priority=True),
        Binding("pageup", "evidence_page_up", "Page up", show=False),
        Binding("pagedown", "evidence_page_down", "Page down", show=False),
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
        self._apply_shell_theme()
        self.store = StateStore(shell.project_dir)
        self._snapshot = snapshot or self.store.snapshot
        self._load_on_mount = load_on_mount
        self._operation: OperationController | None = None
        self._operation_completion_handled = False
        self._operation_spinner_phase = 0
        self._operation_run_label = "current run"
        self._operation_run_identity = (
            _snapshot_run_identity(self._snapshot)
            if self._snapshot.operation.state != "empty"
            else None
        )
        self._refreshing_after_operation = False
        self._run_follow_tail = True
        self._run_scope = None
        self._seen_events: dict[object, int] = {}
        self._session_options_signature = None
        self._syncing_session_select = False
        self._screen = "home"
        self._settings_opener = "home"
        self._settings_return_focus: Widget | None = None
        self._home_focus = "projects"
        self._task_operation_screen: TaskComposer | None = None
        self._home_details_timer: Timer | None = None
        self._filter = ""
        self._evidence_index: EvidenceIndex | None = None
        self._evidence_preview = ""
        self._evidence_lines: list[str] = []
        self._evidence_page_offset = 0
        self._evidence_page_size = 20
        self._notice = ""
        # Adapter diagnostics probe PATH via shutil.which.  Computing them once
        # and caching the result keeps the render path free of filesystem I/O.
        self._adapter_diagnostic_cache: dict[str, str] | None = None
        self._unsubscribe: Callable[[], None] | None = self.store.subscribe(self._post_snapshot)

    @property
    def snapshot(self) -> UiSnapshot:
        return self._snapshot

    @property
    def available_actions(self) -> tuple[ActionDescriptor, ...]:
        shell = self._snapshot.run.shell
        return shell.actions if shell is not None else ()

    def action_command_palette(self) -> None:
        """Open the current context's compact command palette."""

        if len(self.screen_stack) > 1:
            return
        from loopforge.cli.interactive import contextual_commands

        if self._screen == "home":
            selected = self._home_selected_project()
            project_dir = Path(str(selected["path"])) if selected else None
            has_project = selected is not None
        else:
            project_dir = self.shell.project_dir
            has_project = project_dir is not None

        has_run = self._screen == "run" and (
            self._snapshot.run.shell is not None
            and self._snapshot.run.shell.run is not None
        )
        try:
            commands = contextual_commands(project_dir)
        except (OSError, ValueError):
            # An inaccessible project must never become an executable
            # workflow shortcut just because palette discovery failed.
            commands = {"help": "Show command help.",
                        "commands": "List available interactive commands."}

        entries = build_palette_entries(
            self.available_actions if has_run else (),
            commands,
            expert_commands=EXPERT_COMMANDS,
            has_run=has_run,
            has_project=has_project,
        )
        self.push_screen(LoopForgeCommandPalette(entries), self._palette_selected)

    def _palette_selected(self, entry: PaletteEntry | None) -> None:
        """Route a selection through the existing guarded action/command paths."""

        if entry is None:
            return
        if entry.action is not None:
            # The snapshot may have advanced while a modal was open. Never
            # execute an old action just because it was shown in the palette.
            current = next(
                (action for action in self.available_actions
                 if action.id == entry.action.id and action.available),
                None,
            )
            if current is None:
                self._set_notice("This action is no longer available. Refresh the run.")
                return
            self.request_action(current)
            return

        command = entry.command
        if command in {"/run", "/new"}:
            self.action_new_run()
        elif command == "/archive":
            self.action_archive()
        elif command in {"/trust", "/untrust"}:
            self._prefill_palette_command(command + " pack ")
        elif command in {"/do", "/cd", "/resume", "/complete-task",
                         "/fork", "/report"}:
            self._prefill_palette_command(command + " ")
        elif command == "/update":
            # Never install software from a single discovery keystroke.
            self._prefill_palette_command(command)
        else:
            self._run_slash_command(command)

    def _prefill_palette_command(self, command: str) -> None:
        """Use the existing slash input for commands requiring user arguments."""

        field: HomeCommandInput | None = None
        if self._screen == "home":
            field = self.query_one("#home-command-input", HomeCommandInput)
        elif self._screen == "run":
            command_bar = self.query_one("#run-command-bar", RunCommandBar)
            if command_bar.display:
                field = self.query_one("#run-command-input", HomeCommandInput)
        if field is None:
            self.push_screen(
                TextEntryScreen(
                    "Run LoopForge command",
                    "Complete the command and press Enter.",
                    value=command,
                    submit_label="Run",
                ),
                self._run_slash_command,
            )
            return
        field.value = command
        field.cursor_position = len(command)
        field.set_command_active(True)
        field.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable the dashboard's priority bindings only on its own surface."""

        if any(isinstance(screen, LoopForgeCommandPalette) for screen in self.screen_stack):
            return False  # Only the modal's own bindings may consume keys.
        if any(isinstance(screen, TaskComposer) for screen in self.screen_stack):
            if action in {"focus_next", "focus_previous"}:
                return super().check_action(action, parameters)
            return False  # The composer and its confirmation own their native keys.
        if self._screen == "settings":
            # Settings owns navigation. In particular Enter must never open the
            # project adapter picker or trigger a workflow action behind it.
            return action in {
                "focus_next", "focus_previous", "command_palette", "show_home",
                "cancel_or_exit", "root_cancel_or_exit", "quit",
            }
        if action in {"root_open_selected", "open_selected"} and self._screen == "run":
            if (len(self.screen_stack) == 1 and isinstance(self.focused, Button)
                    and (self.focused.id or "").startswith("run-")):
                return False  # A focused run control owns Enter, never the next stage.
            element = self.focused
            while element is not None:
                if isinstance(element, RunDocumentView):
                    return False
                element = element.parent
        if action in {"root_open_selected", "open_selected"} and (
            isinstance(self.focused, (Select, OptionList)) or
            isinstance(getattr(self.focused, "parent", None), (RunToolEntry, RunDetailEntry, RunDelegationEntry))
        ):
            return False  # Native selection and disclosures own Enter.
        if action.startswith("home_"):
            return self._screen == "home" and not isinstance(self.focused, Input)
        if action.startswith("root_"):
            owns_root = (
                self._screen != "home"
                and len(self.screen_stack) == 1
            ) or (
                action in {
                    "root_go_back",
                    "root_cancel_or_exit",
                    "root_show_evidence",
                }
                and self._screen == "home"
                and len(self.screen_stack) == 1
            )
            if not owns_root:
                return False
            if isinstance(self.focused, Input):
                return action in {"root_go_back", "root_cancel_or_exit"}
            if self._screen == "run" and isinstance(self.focused, (Select, OptionList)):
                return action not in {"root_open_selected", "root_move_up", "root_move_down"}
            return True
        return super().check_action(action, parameters)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield HomeDashboard()
        yield RunDashboard()
        yield SettingsDashboard()
        with Container(id="main-content"):
            yield Static(id="screen-title")
            yield Static(id="screen-state", classes="secondary")
            yield Static(id="screen-body")
            yield ScreenList()
            yield Static(id="screen-after", classes="secondary")
            with Container(id="operation-panel"):
                yield Static(id="operation-status", markup=False)
                yield Static(id="operation-log", classes="secondary", markup=False)
            yield Static(id="screen-notice", classes="secondary")
            yield Static(id="screen-help", classes="secondary")
        yield Footer()

    def on_mount(self) -> None:
        self._set_width_class(self.size.width)
        self._render_snapshot(self._snapshot)
        # S5.2: the 120ms timer polls operations; _poll_operation is a cheap
        # no-op when no operation is running (returns immediately), so idle
        # CPU stays near zero.
        self.set_interval(0.12, self._poll_operation)
        if self._load_on_mount:
            self.load_selected_project()

    def on_resize(self, event: Resize) -> None:
        self._set_width_class(event.size.width)
        short = event.size.height <= 26
        self.set_class(short, "run-short")
        for picker in self.query("#run-session-select").results(Select):
            picker.compact = short
        self._render_operation_panel(self._snapshot)

    def on_unmount(self) -> None:
        self._cancel_home_details_timer()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _post_snapshot(self, snapshot: UiSnapshot) -> None:
        self.post_message(SnapshotPublished(snapshot))

    @on(SnapshotPublished)
    def _on_snapshot_published(self, message: SnapshotPublished) -> None:
        if self._refreshing_after_operation and "textual-load" in message.snapshot.reasons:
            self._refreshing_after_operation = False
        self._render_snapshot(message.snapshot)

    @on(LoadFailed)
    def _on_load_failed(self, message: LoadFailed) -> None:
        self._refreshing_after_operation = False
        self.push_screen(RecoverableErrorScreen(message.message))

    @work(thread=True, exclusive=True, group="project-load", exit_on_error=False)
    def load_selected_project(self, project: Path | None = None) -> None:
        try:
            load_project_snapshot(
                self.store,
                project,
                lazy_global_runs=self._screen == "home",
            )
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def select_project(self, project: Path) -> None:
        """Navigate immediately; its project read remains a worker operation."""

        project = self._select_project_context(project)
        self._screen = "project"
        self._reset_list_cursor()
        self.load_selected_project(project)

    def _select_project_context(self, project: Path) -> Path:
        """Adopt a project through the existing session and StateStore seams."""

        project = project.resolve()
        self.shell.project_dir = project
        # Keep project selection and its adapter configuration in one session update.
        if hasattr(self.shell, "refresh_session_config"):
            self.shell.refresh_session_config()
        self.store.select_project(project)
        return project

    def _open_home_run(self, project: Path, run_id: str) -> None:
        """Open a dashboard run without inserting the legacy Project screen."""

        self._select_project_context(project)
        self._screen = "run"
        self._run_follow_tail = True
        self._run_scope = None
        self._reset_list_cursor()
        self._render_snapshot(self._snapshot)
        self.call_after_refresh(self.set_focus, None)
        self._open_run_worker(run_id)

    @work(thread=True, exclusive=True, group="run-load", exit_on_error=False)
    def _open_run_worker(self, run_id: str) -> None:
        try:
            from loopforge.commands import CommandContext, ResumeRun

            # Freshness must span the resume side effect as well as the later read.
            identity = self.store.begin_load()
            project_dir = self.shell.project_dir
            ctx = CommandContext(project_dir=project_dir)
            result = ResumeRun(ctx, run_id=run_id)
            if _identity_stale(self.store, identity):
                return
            if not result.ok:
                message = result.errors[0].message if result.errors else "LoopForge resume failed."
                raise RuntimeError(message)
            self.store.select_run(run_id)
            load_project_snapshot(
                self.store,
                project_dir,
                lazy_global_runs=False,
            )
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    @work(thread=True, exclusive=True, group="evidence-load", exit_on_error=False)
    def _load_evidence_worker(self, query: str = "") -> None:
        try:
            identity = self.store.begin_load()
            status = self.store.status
            index = EvidenceIndex.build(status.run_dir if status is not None else None)
            self._evidence_index = index
            if _identity_stale(self.store, identity):
                return
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
            identity = self.store.begin_load()
            if self._evidence_index is None:
                return
            preview = self._evidence_index.preview(item, query=self._snapshot.evidence.query)
            if _identity_stale(self.store, identity):
                return
            self.call_from_thread(self._set_evidence_preview, preview)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _set_evidence_preview(self, preview: str) -> None:
        self._evidence_preview = preview
        self._evidence_lines = preview.split("\n")
        self._evidence_page_offset = 0
        self._render_snapshot(self._snapshot)

    def _evidence_page_text(self) -> str:
        """Return the current page of evidence preview with a status footer."""
        if not self._evidence_lines:
            return self._evidence_preview
        total = len(self._evidence_lines)
        page_size = self._evidence_page_size
        start = self._evidence_page_offset
        end = min(start + page_size, total)
        page = self._evidence_lines[start:end]
        footer = f"\n\n--- lines {start + 1}–{end} / {total} · PgUp/PgDn to navigate ---"
        return "\n".join(page) + footer

    def action_evidence_page_up(self) -> None:
        if self._screen == "evidence" and self._evidence_lines:
            self._evidence_page_offset = max(0, self._evidence_page_offset - self._evidence_page_size)
            self._render_snapshot(self._snapshot)

    def action_evidence_page_down(self) -> None:
        if self._screen == "evidence" and self._evidence_lines:
            max_offset = max(0, len(self._evidence_lines) - self._evidence_page_size)
            self._evidence_page_offset = min(max_offset, self._evidence_page_offset + self._evidence_page_size)
            self._render_snapshot(self._snapshot)

    def action_move_up(self) -> None:
        self._move(-1)

    def action_home_move_up(self) -> None:
        self.action_move_up()

    def action_root_move_up(self) -> None:
        self.action_move_up()

    def action_move_down(self) -> None:
        self._move(1)

    def action_home_move_down(self) -> None:
        self.action_move_down()

    def action_root_move_down(self) -> None:
        self.action_move_down()

    def action_move_left(self) -> None:
        if self._screen == "home":
            if self._home_focus == "runs":
                self._home_focus = "projects"
            else:
                self._home_project_list().reset_cursor()
                self._home_run_list().reset_cursor()
                self._schedule_home_details_render()
            self._render_home_interaction()

    def action_home_move_left(self) -> None:
        self.action_move_left()

    def action_move_right(self) -> None:
        if self._screen == "home":
            self._commit_home_details()
            if self._home_run_list().item_count:
                self._home_focus = "runs"
                self._render_home_interaction()

    def action_home_move_right(self) -> None:
        self.action_move_right()

    def _move(self, delta: int) -> None:
        if self._screen == "home":
            if isinstance(self.focused, Input):
                return
            if self._home_focus == "runs":
                self._home_run_list().move_cursor(delta)
                return
            target = self._home_project_list()
            before = self._home_project_key()
            target.move_cursor(delta)
            if self._home_project_key() != before:
                self._home_run_list().reset_cursor()
                self._schedule_home_details_render()
                self._render_home_interaction()
            return
        if self._screen == "run":
            activity = self.query_one("#run-activity-feed", RunActivityFeed)
            target = (activity if self._snapshot.run.reading.view == "Live"
                      else self.query_one("#run-document-view", RunDocumentView))
            live_reading = self._snapshot.run.reading.view == "Live"
            if live_reading and delta < 0:
                # Cancel a pending follow callback *before* manual scrolling.
                self._suspend_run_follow()
            target.scroll_relative(y=delta, animate=False, force=True, immediate=True)
            if live_reading and delta > 0:
                if activity.scroll_y >= activity.max_scroll_y:
                    # Returning to the tail restores live follow after inspection.
                    self._run_follow_tail = True
                    self.store.save_reading_position(scroll_y=0, following=True)
                    self.store.invalidate("run-reading-position")
                    self.store.flush()
                else:
                    self._suspend_run_follow()
            return
        self._screen_list().move_cursor(delta)

    def action_show_home(self) -> None:
        self._screen = "home"
        self._home_focus = "projects"
        self._reset_list_cursor()
        try:
            self._home_project_list().reset_cursor()
            self._home_run_list().reset_cursor()
        except NoMatches:
            pass
        self._render_snapshot(self._snapshot)

    def action_show_evidence(self) -> None:
        if self._screen != "run" or self.store.status is None or self.store.status.run_dir is None:
            self._notice = "Open a run to view its evidence."
            self._render_snapshot(self._snapshot)
            return
        self._screen = "evidence"
        self._reset_list_cursor()
        self._evidence_preview = ""
        self._load_evidence_worker(self._snapshot.evidence.query)
        self._render_snapshot(self._snapshot)

    def action_root_show_evidence(self) -> None:
        self.action_show_evidence()

    def action_show_settings(self) -> None:
        if self._screen == "settings" or len(self.screen_stack) != 1:
            return
        if self._screen == "home":
            self._commit_home_details()
        self._settings_opener = self._screen
        self._settings_return_focus = self.focused
        self._screen = "settings"
        self._render_snapshot(self._snapshot)
        self.query_one(SettingsDashboard).focus_navigation()

    @on(SettingsDashboard.BackRequested)
    def _settings_back_requested(self, event: SettingsDashboard.BackRequested) -> None:
        event.stop()
        self._close_settings()

    def _close_settings(self) -> None:
        if self._screen != "settings":
            return
        self._screen = self._settings_opener
        self._render_snapshot(self._snapshot)
        self.call_after_refresh(self._restore_settings_focus)

    def _restore_settings_focus(self) -> None:
        if self._screen != self._settings_opener or len(self.screen_stack) != 1:
            return
        previous = self._settings_return_focus
        if previous is None or previous.is_attached:
            self.set_focus(previous)

    def action_root_show_settings(self) -> None:
        self.action_show_settings()

    def show_adapter_selector(self) -> None:
        """Open the adapter control without routing through the slash shell."""

        self.push_screen(
            AdapterSelectionScreen(
                SUPPORTED_ADAPTERS,
                self.shell.selected_adapter,
                self._adapter_diagnostics(),
                selected_args=tuple(self.shell.selected_adapter_args),
            ),
            self._select_adapter,
        )

    def _select_adapter(self, adapter: str | None) -> None:
        if adapter is None:
            return
        result = set_default_adapter(self.shell.project_dir, adapter)
        if not result.ok:
            details = "; ".join(result.blockers) or result.message
            self._notice = f"Adapter was not changed: {details}"
            self._render_snapshot(self._snapshot)
            return
        self.shell.refresh_session_config()
        diagnostic = self._adapter_diagnostics().get(adapter, "diagnostic unavailable")
        self._notice = f"Adapter set to {adapter}. {diagnostic}"
        self._render_snapshot(self._snapshot)
        self.load_selected_project(self.shell.project_dir)

    def action_go_back(self) -> None:
        if self._screen == "settings":
            self.query_one(SettingsDashboard).action_back()
            return
        if self._screen == "home":
            command_input = self.query_one("#home-command-input", Input)
            if command_input.has_focus:
                if isinstance(command_input, HomeCommandInput):
                    command_input.set_command_active(False)
                else:
                    command_input.blur()
                self._home_focus = "projects"
                self._render_home(self._snapshot)
            return
        if self._screen == "run":
            if isinstance(self.focused, CollapsibleTitle):
                disclosure = self.focused.parent
                if isinstance(disclosure, (RunDelegationEntry, RunToolEntry)):
                    ancestor = disclosure.parent
                    while ancestor is not None and not isinstance(ancestor, RunDelegationEntry):
                        ancestor = ancestor.parent
                    if isinstance(disclosure, RunDelegationEntry) and not disclosure.collapsed:
                        disclosure.collapsed = True
                        return
                    if isinstance(ancestor, RunDelegationEntry):
                        if not disclosure.collapsed:
                            disclosure.collapsed = True
                        elif not ancestor.collapsed:
                            ancestor.collapsed = True
                            ancestor.query_one(CollapsibleTitle).focus()
                        return
            command_input = self.query_one("#run-command-input", HomeCommandInput)
            if command_input.has_focus:
                command_input.set_command_active(False)
                self._render_run(self._snapshot)
                return
        if self._screen == "evidence" and self._evidence_preview:
            self._evidence_preview = ""
        else:
            self._screen = {"home": "home", "project": "home", "run": "project", "evidence": "run", "settings": "run"}[self._screen]
            self._reset_list_cursor()
        self._render_snapshot(self._snapshot)

    def action_root_go_back(self) -> None:
        self.action_go_back()

    def action_open_selected(self) -> None:
        if self._screen == "home":
            if isinstance(self.focused, Input):
                self._submit_home_command(self.focused)
                return
            if self._home_focus == "projects":
                self._commit_home_details()
                if self._home_run_list().item_count:
                    self._home_focus = "runs"
                    self._home_run_list().reset_cursor()
                    self._render_home_interaction()
                return
            item = self._home_run_list().selected_item
            if item is not None:
                value = dict(item) if hasattr(item, "items") else {}
                run_id = str(value.get("run_id") or "")
                project = Path(str(value.get("project_path") or self.shell.project_dir))
                if run_id:
                    self._open_home_run(project, run_id)
            return
        if self._screen == "project":
            item = self._screen_list().selected_item
            if item is not None:
                value = dict(item) if hasattr(item, "items") else {}
                run_id = str(value.get("run_id") or "")
                if run_id:
                    self._screen = "run"
                    self._run_follow_tail = True
                    self._reset_list_cursor()
                    self._render_snapshot(self._snapshot)
                    self.call_after_refresh(self.set_focus, None)
                    self._open_run_worker(run_id)
            return
        if self._screen == "run":
            if isinstance(self.focused, CollapsibleTitle):
                parent = self.focused.parent
                if isinstance(parent, (RunFileChangeEntry, RunDelegationEntry)) or (
                        isinstance(parent, Collapsible) and parent.has_class("run-file-change-row")):
                    parent.collapsed = not parent.collapsed
                    return
            action = self._available_run_action(self._snapshot)
            if action is not None:
                self.request_action(action)
            return
        if self._screen == "evidence":
            item = self._screen_list().selected_item
            if item is not None:
                self._open_evidence_worker(item)
            return
        if self._screen == "settings":
            self.query_one(SettingsDashboard).action_focus_content()

    def action_home_open_selected(self) -> None:
        self.action_open_selected()

    def action_root_open_selected(self) -> None:
        self.action_open_selected()

    def action_new_run(self) -> None:
        if self._run_operation_busy(self._snapshot) or len(self.screen_stack) > 1:
            return
        target = self.shell.project_dir
        if self._screen == "home":
            project = self._home_selected_project()
            if project is None:
                return
            target = Path(str(project.get("path") or target))
        self._select_project_context(target)
        self.push_screen(TaskComposer(target), self._task_form_closed)

    def action_home_new_run(self) -> None:
        self.action_new_run()

    def action_root_new_run(self) -> None:
        self.action_new_run()

    def action_complete_task(self) -> None:
        if self._run_operation_busy(self._snapshot) or len(self.screen_stack) > 1:
            return
        run_id = self._snapshot.selected_run_id
        if not run_id:
            return
        self.push_screen(
            TaskComposer(self.shell.project_dir, complete=True, run_id=run_id),
            self._task_form_closed,
        )

    def _task_form_closed(self, run_id: str | None) -> None:
        self._task_operation_screen = None
        if run_id:
            self._screen = "run"
            self._run_follow_tail = True
            self._run_scope = None
            # Never publish the completed operation beside pre-operation guidance.
            self.store.select_project(self.shell.project_dir)
            self.store.select_run(run_id)
            self._snapshot = self.store.snapshot
            self._open_run_worker(run_id)
        self._render_snapshot(self._snapshot)
        if run_id:
            self.call_after_refresh(self.set_focus, None)

    def submit_task_draft(self, screen: TaskComposer, draft: TaskDraft) -> None:
        context = screen.context
        if context is None or self._run_operation_busy(self._snapshot):
            screen.show_failure("Another operation is in progress. Wait, then retry.")
            return
        self._task_operation_screen = screen

        def run(_emit, _cancelled):
            fresh = load_task_context(context.scope.project_path)
            if (fresh.scope != context.scope
                    or self.shell.project_dir.resolve() != context.scope.project_path
                    or self.store.begin_load().project != context.scope.project_path):
                return SimpleNamespace(exit_code=1, should_exit=False, context_changed=True,
                                       message="The project or current run changed. Recheck the project before submitting.")
            self._operation.commit_started = True
            result = self._capture_shell_result(
                (lambda: self.shell.complete_current_task_definition(
                    draft.success_checks[0], expected_scope=context.scope))
                if screen.complete else
                (lambda: self.shell.create_run_from_intake(
                    draft.task, success_checks=list(draft.success_checks), rubric=draft.rubric))
            )
            if screen.complete and result.exit_code == 0:
                result.run_id = context.scope.run_id
            return result

        self._run_shell_operation(
            "Save criterion" if screen.complete else "Create run", run,
        )

    def action_command(self) -> None:
        """Open the existing slash-command surface from the full-screen UI."""

        if self._screen == "home":
            command_input = self.query_one("#home-command-input", HomeCommandInput)
            if not command_input.value:
                command_input.value = "/"
                command_input.cursor_position = 1
            command_input.set_command_active(True)
            self.set_focus(command_input)
            return
        if self._screen == "run":
            command_bar = self.query_one("#run-command-bar", RunCommandBar)
            if command_bar.display:
                command_input = self.query_one("#run-command-input", HomeCommandInput)
                if not command_input.value:
                    command_input.value = "/"
                    command_input.cursor_position = 1
                command_input.set_command_active(True)
                self.set_focus(command_input)
                return
        if self._screen in {"project", "evidence"}:
            self.action_filter()
            return
        self.push_screen(
            TextEntryScreen(
                "Run LoopForge command",
                "Enter a slash command, for example /status or /report --help.",
                value="/",
                submit_label="Run",
            ),
            self._run_slash_command,
        )

    def action_home_command(self) -> None:
        self.action_command()

    def action_root_command(self) -> None:
        self.action_command()

    @on(Input.Submitted, "#home-command-input")
    def _on_home_command_submitted(self, event: Input.Submitted) -> None:
        self._submit_home_command(event.input)

    @on(Input.Submitted, "#run-command-input")
    def _on_run_command_submitted(self, event: Input.Submitted) -> None:
        self._submit_run_command(event.input)

    def _submit_home_command(self, command_input: Input) -> None:
        """Dispatch slash commands; leave plain text untouched and inert."""

        line = self._consume_slash_input(command_input)
        if line is None:
            return
        self._home_focus = "projects"
        self._run_slash_command(line)

    def _submit_run_command(self, command_input: Input) -> None:
        """Keep plain text inert and route slash commands through the shared shell."""

        line = self._consume_slash_input(command_input)
        if line is None:
            return
        self._run_slash_command(line)

    @staticmethod
    def _consume_slash_input(command_input: Input) -> str | None:
        line = command_input.value.strip()
        if not line.startswith("/"):
            return None
        command_input.value = ""
        if isinstance(command_input, HomeCommandInput):
            command_input.set_command_active(False)
        else:
            command_input.blur()
        return line

    def action_quit(self) -> None:
        self.exit()

    def _run_slash_command(self, command: str | None) -> None:
        if command is None or not command.strip():
            return
        line = command.strip()
        if not line.startswith("/"):
            line = f"/{line}"
        self._run_shell_operation(
            "Run command",
            lambda emit, cancelled: self._dispatch_slash_command(
                line,
                operation_callback=emit,
                cancel_event=cancelled,
            ),
        )

    def _dispatch_slash_command(
        self,
        line: str,
        *,
        operation_callback=None,
        cancel_event=None,
    ) -> SimpleNamespace:
        """Route through the compatibility shell without writing over Textual's screen."""

        command, args, implicit_run = self.shell.parse_line(line)
        command, args = self.shell.canonical_command(command, args)
        if implicit_run:
            return self._capture_shell_result(lambda: self.shell.cmd_run(args))
        if command == "continue":
            return self._capture_shell_result(
                lambda: self.shell.cmd_continue(
                    args,
                    default_execution_mode=DEFAULT_AGENT_EXECUTION_MODE,
                    operation_callback=operation_callback,
                    cancel_event=cancel_event,
                )
            )
        if command == "verify":
            return self._capture_shell_result(
                lambda: self.shell.cmd_verify(
                    args,
                    operation_callback=operation_callback,
                    cancel_event=cancel_event,
                )
            )
        if command == "do":
            return self._capture_shell_result(
                lambda: self.shell.cmd_do(
                    args,
                    operation_callback=operation_callback,
                    cancel_event=cancel_event,
                )
            )
        return self._capture_shell_result(lambda: self.shell.dispatch(line))

    def _capture_shell_result(self, runner: Callable[[], object]) -> SimpleNamespace:
        """Capture compatibility output so Textual remains the sole terminal writer."""

        captured = io.StringIO()
        original_output = self.shell.output
        original_error = self.shell.error
        original_renderer = self.shell.renderer
        self.shell.output = captured
        self.shell.error = captured
        self.shell.renderer = TerminalRenderer(captured, mode="plain", theme=self.shell.theme)
        try:
            result = runner()
        except (LockTimeoutError, RevisionConflictError) as error:
            refusal = persistence_error(error)
            captured.write(f"{refusal.title}: {refusal.detail}\n")
            if refusal.fix:
                captured.write(refusal.fix)
            result = SimpleNamespace(exit_code=refusal.exit_code, should_exit=False)
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
            run_id=getattr(result, "run_id", None),
            message=output or ("Command completed." if result.exit_code == 0 else "Command was blocked."),
        )

    def action_filter(self) -> None:
        value = self._snapshot.evidence.query if self._screen == "evidence" else self._filter
        self.push_screen(TextEntryScreen("Filter", "Filter the current list.", value=value), self._apply_filter)

    def _apply_filter(self, value: str | None) -> None:
        if value is None:
            return
        self._reset_list_cursor()
        if self._screen == "evidence":
            self._evidence_preview = ""
            self._load_evidence_worker(value)
        else:
            self._filter = value.strip()
        self._render_snapshot(self._snapshot)

    def action_archive(self) -> None:
        if self._screen != "project" and self._screen != "run":
            return
        run_id = self._target_run_id()
        if not run_id:
            self._notice = "Select a run to archive."
            self._render_snapshot(self._snapshot)
            return
        project_name = self.shell.project_dir.name
        lines = (
            f"Archive run {run_id[:16]}?",
            f"Project: {project_name}  ·  Revision: {self._snapshot.revision}",
            "The run remains available in history and can be inspected later.",
        )
        self.push_screen(ConfirmationScreen("Archive run", lines, approve_label="Archive"), lambda approved: self._archive_confirmed(approved, run_id))

    def action_root_archive(self) -> None:
        self.action_archive()

    def _archive_confirmed(self, approved: bool, run_id: str) -> None:
        if approved:
            self._run_shell_operation(
                "Archive run",
                lambda _emit, _cancelled: self._capture_shell_result(
                    lambda: self.shell.cmd_archive_run(run_id)
                ),
            )

    def _target_run_id(self) -> str | None:
        """Return the run_id that actions should target based on screen context.

        On the 'run' screen this is the opened run from the immutable snapshot;
        on the 'project' screen this is the ScreenList cursor's selected item.
        Keeping these sources separate prevents an open run from inheriting the
        project list's cursor.
        """

        if self._screen == "run":
            return self._snapshot.selected_run_id
        if self._screen == "project":
            item = self._screen_list().selected_item
            if item is None:
                return None
            value = dict(item) if hasattr(item, "items") else {}
            return str(value.get("run_id") or "") or None
        return None

    def request_action(self, action: ActionDescriptor) -> None:
        if action.executor_key == "adapter":
            self.show_adapter_selector()
            return
        if action.executor_key == "collect-task":
            self.action_new_run()
            return
        if action.executor_key == "complete-task":
            self.action_complete_task()
            return
        if not action.requires_confirmation:
            self._execute_action(action)
            return
        identity = self.store.begin_load()
        shown_run = self._snapshot.run.shell.run if self._snapshot.run.shell is not None else None
        shown_run_id = str(shown_run.id) if shown_run is not None else None
        cursor_run_id = self._target_run_id()
        if (
            shown_run_id is None
            or (cursor_run_id is not None and cursor_run_id != shown_run_id)
            or (identity.run_id is not None and identity.run_id != shown_run_id)
        ):
            self._notice = "The selected run changed. Refresh and confirm again."
            self._render_snapshot(self._snapshot)
            return
        try:
            status = current_status(identity.project)
        except (OSError, ValueError) as error:
            self._notice = f"Could not load confirmation context: {error}"
            self._render_snapshot(self._snapshot)
            return
        if (
            not status.initialized
            or status.config is None
            or status.run is None
            or shown_run_id != status.run.get("run_id")
        ):
            self._notice = "The selected run changed. Refresh and confirm again."
            self._render_snapshot(self._snapshot)
            return
        requested_scope = ActionScope(
            project_id=str(status.config.get("project_id") or ""),
            project_path=status.project_dir,
            run_id=str(status.run.get("run_id") or "") or None,
            revision=status.run.get("run_revision", 0),
            config_revision=status.config.get("config_revision", 0),
        )
        self._load_confirmation(action, identity, requested_scope)

    @work(thread=True, exclusive=True, group="confirmation", exit_on_error=False)
    def _load_confirmation(self, action: ActionDescriptor, identity, requested_scope: ActionScope) -> None:
        try:
            stages = {"approve-task": "task", "approve-plan": "plan", "approve-review": "review"}
            stage = stages.get(action.id)
            status = current_status(identity.project)
            if not status.initialized or status.config is None or status.run is None:
                self.call_from_thread(self._set_notice, "The current run changed. Refresh and confirm again.")
                return
            if (
                status.project_dir != requested_scope.project_path
                or status.config.get("project_id") != requested_scope.project_id
                or status.config.get("current_run_id") != requested_scope.run_id
                or status.config.get("config_revision", 0) != requested_scope.config_revision
                or status.run.get("run_id") != requested_scope.run_id
                or status.run.get("run_revision", 0) != requested_scope.revision
            ):
                self.call_from_thread(self._set_notice, "The selected run changed. Refresh and confirm again.")
                return
            scope = requested_scope
            if stage:
                summary = approval_summary(status.run_dir, status.run, stage)
                title, lines = summary.title, (f"Run: {scope.run_id}", *summary.lines)
                scope = ActionScope(
                    project_id=scope.project_id,
                    project_path=scope.project_path,
                    run_id=scope.run_id,
                    revision=scope.revision,
                    snapshot=summary.artifact_sha256,
                    config_revision=scope.config_revision,
                )
            else:
                title = f"{action.label}?"
                lines = (f"Run: {scope.run_id}", action.description, "Permissions follow the selected pack and stage.", "This remains a local LoopForge action.")
            if _identity_stale(self.store, identity):
                return
            self.call_from_thread(self._show_confirmation, action, title, lines, scope, identity)
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _show_confirmation(self, action: ActionDescriptor, title: str, lines: tuple[str, ...], scope: ActionScope, identity) -> None:
        if not self.store.accepts(identity):
            return
        confirmation = ConfirmationScreen(
            title, lines, approve_label="Approve task" if action.id == "approve-task" else "Approve",
            cancel_label="Back" if action.id == "approve-task" else "Cancel",
        )
        if action.id == "approve-task":
            confirmation.add_class("task-confirmation")
        self.push_screen(
            confirmation,
            lambda approved: self._execute_action(action, expected_scope=scope) if approved else None,
        )

    def show_trust_confirmation(
        self,
        pack_name: str,
        pack_hash: str,
        commands: list[str],
        on_approved: Callable[[], None],
    ) -> None:
        lines = (
            f"Pack '{pack_name}' is not yet trusted.",
            f"Hash: {pack_hash}",
            "Commands: " + ", ".join(commands) if commands else "none",
            "",
            "Trust this pack to allow its checks to execute?",
        )
        self.push_screen(
            ConfirmationScreen(
                f"Trust pack '{pack_name}'?",
                lines,
                approve_label="Trust pack",
            ),
            lambda approved: on_approved() if approved else None,
        )

    def _execute_action(self, action: ActionDescriptor, *, expected_scope: ActionScope | None = None) -> None:
        self._run_shell_operation(
            action.label,
            lambda emit, cancelled: self._capture_shell_result(
                lambda: self.shell.execute_guided_action(
                    action,
                    expected_scope=expected_scope,
                    implementation_mode=DEFAULT_AGENT_EXECUTION_MODE,
                    operation_callback=emit,
                    cancel_event=cancelled,
                )
            ),
        )

    def _run_shell_operation(self, label: str, runner: Callable[[object, object], object]) -> None:
        if self._operation is not None and not self._operation.finished:
            self._notice = f"{self._operation.label} is already running; live status is shown below."
            self._render_snapshot(self._snapshot)
            return
        operation = OperationController(label)
        self.begin_operation(operation)
        operation.start(
            lambda emit, cancelled: _operation_result(
                operation,
                runner(emit, cancelled),
                cancelled.is_set(),
            )
        )

    def begin_operation(self, operation: OperationController) -> None:
        self._operation_run_label = _snapshot_run_label(self._snapshot)
        self._operation_run_identity = _snapshot_run_identity(self._snapshot)
        self._operation = operation
        self._operation_completion_handled = False
        self._operation_spinner_phase = 0
        self._notice = ""
        if self._screen == "run":
            self._run_follow_tail = True
        self._snapshot = self.store.set_operation(operation)

    def _poll_operation(self) -> None:
        operation = self._operation
        if operation is None:
            return
        if operation.finished and self._operation_completion_handled:
            return
        history = operation.collect_events()
        has_new_events = history != self._snapshot.operation.events
        if operation.finished:
            # Let the project refresh publish the terminal snapshot together
            # with the post-action run state. Publishing it here would pair a
            # completed operation with the stale pre-action guidance.
            self.store.record_operation_events(operation)
            self._operation_completion_handled = True
            if self._task_operation_screen is not None:
                form = self._task_operation_screen
                self._task_operation_screen = None
                result = operation.result
                run_id = getattr(result, "run_id", None)
                if getattr(result, "ok", False) and run_id:
                    form.dismiss(run_id)
                else:
                    self.store.flush()
                    message = str(operation.error or getattr(result, "message", "Could not save this task."))
                    # An exception may happen after persistence. Recheck before a retry.
                    form.show_failure(message, changed=bool(operation.error or
                                      getattr(result, "context_changed", False) or
                                      (getattr(result, "ok", False) and not run_id)))
                return
            self._notice = (
                "Operation completed."
                if bool(getattr(operation.result, "ok", False))
                else "Operation blocked; inspect retained evidence."
            )
            if bool(getattr(operation.result, "should_exit", False)):
                self.exit()
                return
            self._refreshing_after_operation = True
            self._render_snapshot(self._snapshot)
            self.load_selected_project()
            return
        if has_new_events:
            self._snapshot = self.store.record_operation_events(operation)
            self._snapshot = self.store.flush()
            if self._screen != "run":
                self._render_operation_panel(self._snapshot)
        self._operation_spinner_phase = (self._operation_spinner_phase + 1) % 10
        self._refresh_operation_status()

    def action_cancel_or_exit(self) -> None:
        if self._operation is not None and not self._operation.finished:
            self._operation.cancel()
            self.store.record_operation_events(self._operation)
            self.store.flush()
            return
        self.exit()

    def action_root_cancel_or_exit(self) -> None:
        self.action_cancel_or_exit()

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
        item = self._screen_list().selected_item
        if item is not None:
            self._export_evidence_worker(item)

    @work(thread=True, exclusive=True, group="evidence-export", exit_on_error=False)
    def _export_evidence_worker(self, item: EvidenceItem) -> None:
        try:
            import hashlib
            import shutil

            from datetime import datetime, timezone

            # S3.1: capture identity and target run_dir BEFORE the side effect.
            identity = self.store.begin_load()
            status = self.store.status
            if status is None or status.run_dir is None:
                raise RuntimeError("No run is selected.")
            run_dir = status.run_dir
            source_path = item.path
            exports_dir = run_dir / "artifacts" / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            # S4.3: unique destination to avoid overwriting same-name artifacts.
            destination = exports_dir / item.path.name
            counter = 1
            while destination.exists():
                stem = item.path.stem
                suffix = item.path.suffix
                destination = exports_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            shutil.copyfile(source_path, destination)
            # S4.3: write a receipt with full identity.
            content_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
            receipt = {
                "project": str(self.shell.project_dir.name),
                "run_id": str(self._snapshot.selected_run_id or ""),
                "artifact": str(item.path.name),
                "content_hash": content_hash,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "destination": str(destination.relative_to(run_dir)),
            }
            receipt_path = exports_dir / f"{destination.stem}.receipt.json"
            receipt_path.write_text(
                __import__("json").dumps(receipt, indent=2),
                encoding="utf-8",
            )
            # Check freshness AFTER the effect but BEFORE publishing.
            if _identity_stale(self.store, identity):
                return
            self.call_from_thread(
                self._set_notice,
                f"Exported {destination.relative_to(run_dir)} (hash {content_hash})",
            )
        except Exception as error:
            self.post_message(LoadFailed(str(error)))

    def _set_notice(self, notice: str) -> None:
        self._notice = notice
        self._render_snapshot(self._snapshot)

    def _screen_list(self) -> ScreenList:
        return self.query_one("#screen-list", ScreenList)

    def _reset_list_cursor(self) -> None:
        try:
            self.query_one("#screen-list", ScreenList).reset_cursor()
        except NoMatches:
            pass

    def _home_project_list(self) -> ScreenList:
        return self._base_query_one("#home-project-list", ScreenList)

    def _home_run_list(self) -> ScreenList:
        return self._base_query_one("#home-run-list", ScreenList)

    def _base_query_one(self, selector: str, expect_type):
        """Query the default application screen even while a modal is active."""

        return self.screen_stack[0].query_one(selector, expect_type)

    def _home_project_key(self) -> str:
        item = self._home_project_list().selected_item
        value = dict(item) if item is not None and hasattr(item, "items") else {}
        return str(value.get("path") or "__all__")

    def _home_selected_project(self) -> dict[str, object] | None:
        item = self._home_project_list().selected_item
        if item is None or not hasattr(item, "items"):
            return None
        value = dict(item)
        return None if value.get("all_projects") else value

    def _home_active_runs(
        self,
        project: dict[str, object] | None,
        rows: tuple[object, ...] | None = None,
    ) -> tuple[object, ...]:
        if rows is None:
            rows = tuple(
                row
                for row in self._snapshot.home.runs
                if not bool(row.get("archived"))
            )
        if project is None:
            return rows
        project_id = str(project.get("project_id") or "")
        project_path = Path(str(project.get("path") or ""))
        return tuple(
            row
            for row in rows
            if (
                str(row.get("project_id") or "") == project_id
                if project_id and row.get("project_id")
                else _same_path(Path(str(row.get("project_path") or "")), project_path)
            )
        )

    def _home_metrics(
        self,
        projects: tuple[object, ...],
        project: dict[str, object] | None,
        runs: tuple[object, ...],
    ) -> tuple[tuple[str, str], ...]:
        if project is None:
            attention = sum(
                1
                for row in projects
                if str(dict(row).get("attention") or "") in {"needs_human", "blocked"}
            )
            adapters = {
                str(dict(row).get("default_adapter") or "").strip()
                for row in projects
                if str(dict(row).get("default_adapter") or "").strip()
            }
            if not adapters:
                adapter = str(getattr(self.shell, "selected_adapter", "unknown"))
            elif len(adapters) == 1:
                adapter = next(iter(adapters))
            else:
                adapter = "mixed"
            return (
                ("Projects", str(len(projects))),
                ("Active runs", str(len(runs))),
                ("Need attention", str(attention)),
                ("Default adapter", adapter),
            )

        latest = max(
            (dict(row) for row in runs),
            key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
            default={},
        )
        adapter = str(project.get("default_adapter") or "").strip()
        if not adapter and _same_path(
            Path(str(project.get("path") or "")), Path(self.shell.project_dir)
        ):
            adapter = str(getattr(self.shell, "selected_adapter", "unknown"))
        return (
            ("Project", str(project.get("name") or "unknown")),
            ("Git", str(project.get("branch") or "no branch")),
            (
                "Pack",
                str(
                    latest.get("pack")
                    or project.get("latest_pack")
                    or project.get("profile")
                    or "none"
                ),
            ),
            ("Adapter", adapter or "unknown"),
        )

    def _render_home(self, snapshot: UiSnapshot) -> None:
        self._cancel_home_details_timer()
        project_rows = tuple(snapshot.home.projects)
        active_runs = tuple(row for row in snapshot.home.runs if not bool(row.get("archived")))
        total_runs = sum(int(row.get("run_count") or 0) for row in project_rows)
        all_projects = {
            "all_projects": True,
            "name": "All projects",
            "run_count": total_runs,
            "attention": "",
        }
        project_list = self._home_project_list()
        list_width = max(
            28,
            self.size.width - 10 if self.size.width <= 60 else self.size.width // 2 - 12,
        )
        project_list.populate(
            [all_projects, *project_rows],
            lambda row: _home_project_line(row, width=list_width),
        )
        attention_count = sum(
            1
            for row in project_rows
            if str(row.get("attention") or "") in {"needs_human", "blocked"}
        )
        self._base_query_one("#home-header", HomeHeader).update_content(
            version=__version__,
            project_count=len(project_rows),
            attention_count=attention_count,
        )
        self._render_home_details(
            snapshot,
            project_rows=project_rows,
            active_runs=active_runs,
            list_width=list_width,
        )
        hint = self._notice
        if snapshot.operation.state != "empty":
            hint = self._operation_status(snapshot)
        self._base_query_one("#home-command-bar", HomeCommandBar).update_hint(hint)
        self._render_home_interaction()

    def _render_home_details(
        self,
        snapshot: UiSnapshot,
        *,
        project_rows: tuple[object, ...] | None = None,
        active_runs: tuple[object, ...] | None = None,
        list_width: int | None = None,
    ) -> None:
        if project_rows is None:
            project_rows = tuple(snapshot.home.projects)
        if active_runs is None:
            active_runs = tuple(
                row for row in snapshot.home.runs if not bool(row.get("archived"))
            )
        if list_width is None:
            list_width = max(
                28,
                self.size.width - 10 if self.size.width <= 60 else self.size.width // 2 - 12,
            )
        selected_project = self._home_selected_project()
        runs = self._home_active_runs(selected_project, active_runs)
        self._home_run_list().populate(
            list(runs),
            lambda row: _home_run_line(
                row,
                aggregate=selected_project is None,
                width=list_width,
            ),
        )
        if self._home_focus == "runs" and not runs:
            self._home_focus = "projects"
        self._base_query_one("#home-metrics", HomeMetrics).update_values(
            self._home_metrics(project_rows, selected_project, runs if selected_project else active_runs)
        )

    def _render_home_interaction(self) -> None:
        selected_project = self._home_selected_project()
        self._base_query_one("#home-project-panel", HomeListPanel).set_active(
            self._home_focus == "projects"
        )
        self._base_query_one("#home-run-panel", HomeListPanel).set_active(
            self._home_focus == "runs"
        )
        self._base_query_one("#home-hotkeys", HomeHotkeyBar).update_state(
            project_selected=selected_project is not None,
            focus=self._home_focus,
        )

    def _cancel_home_details_timer(self) -> None:
        if self._home_details_timer is not None:
            self._home_details_timer.stop()
            self._home_details_timer = None

    def _schedule_home_details_render(self) -> None:
        self._cancel_home_details_timer()
        self._home_details_timer = self.set_timer(
            self.HOME_DETAILS_DELAY,
            self._render_pending_home_details,
        )

    def _render_pending_home_details(self) -> None:
        self._home_details_timer = None
        if self._screen != "home" or not self.screen_stack:
            return
        self._render_home_details(self._snapshot)
        self._render_home_interaction()

    def _commit_home_details(self) -> None:
        if self._home_details_timer is None:
            return
        self._cancel_home_details_timer()
        self._render_home_details(self._snapshot)

    def _sync_screen_surface(self) -> None:
        home = self._base_query_one("#home-dashboard", HomeDashboard)
        run = self._base_query_one("#run-dashboard", RunDashboard)
        settings = self._base_query_one("#settings-dashboard", SettingsDashboard)
        main = self._base_query_one("#main-content", Container)
        legacy_header = self._base_query_one("Header", Header)
        legacy_footer = self._base_query_one("Footer", Footer)
        is_home = self._screen == "home"
        is_run = self._screen == "run"
        is_settings = self._screen == "settings"
        home.display = is_home
        run.display = is_run
        settings.display = is_settings
        main.display = not is_home and not is_run and not is_settings
        legacy_header.display = main.display
        legacy_footer.display = main.display

    def _render_snapshot(self, snapshot: UiSnapshot) -> None:
        self._apply_shell_theme()
        self._snapshot = snapshot
        if not self.screen_stack:
            return
        if any(isinstance(screen, TaskComposer) for screen in self.screen_stack):
            return  # Keep the form, draft and focus stable through background refreshes.
        try:
            self._sync_screen_surface()
        except NoMatches:
            # Queued worker snapshots may arrive while Textual removes the screen.
            return
        if self._screen == "home":
            self._render_home(snapshot)
            return
        if self._screen == "run":
            self._render_run(snapshot)
            return
        if self._screen == "settings":
            self._render_settings(snapshot)
            return
        title, before, items, formatter, after, help_text = self._screen_layout(snapshot)
        try:
            title_widget = self.query_one("#screen-title", Static)
        except NoMatches:
            # A final timer tick can race Textual's screen teardown.
            return
        title_widget.update(title)
        self.query_one("#screen-state", Static).update(f"{self._screen.title()} · {self._state_label(snapshot)}")
        self.query_one("#screen-body", Static).update(before)
        screen_list = self.query_one("#screen-list", ScreenList)
        if items and formatter:
            screen_list.populate(list(items), formatter)
            screen_list.display = True
        else:
            screen_list.display = False
        self.query_one("#screen-after", Static).update(after)
        self._render_operation_panel(snapshot)
        self.query_one("#screen-notice", Static).update(self._notice)
        self.query_one("#screen-help", Static).update(help_text)

    def _render_settings(self, snapshot: UiSnapshot) -> None:
        """Supply existing, read-only information to the approved global frame."""

        diagnostics = self._adapter_diagnostics()
        harnesses = Text()
        harnesses.append("Harness pris en charge\n\n", style="bold")
        for name in AGENT_COMMANDS:
            harnesses.append(f"{name}\n", style="#CBC3D7")
            harnesses.append(f"  {diagnostics[name]}\n")
        harnesses.append("\nLa présence du binaire ne confirme pas la connexion.", style="#958EA0")
        workflow = Text("Les étapes et leurs acteurs sont définis par le contrat du pack.\n\n")
        shell = snapshot.run.shell
        if shell is not None and shell.stages:
            workflow.append("Contexte du run courant\n", style="bold")
            for stage in shell.stages:
                workflow.append(f"{stage.title}\n")
        else:
            workflow.append("Aucun workflow de run sélectionné.", style="#958EA0")
        autonomy = Text()
        autonomy.append("Profils disponibles\n\n", style="bold")
        for name in SUPPORTED_PROFILES:
            autonomy.append(f"{name}\n", style="#CBC3D7")
            autonomy.append(f"{profile_policy(name)['summary']}\n\n")
        diagnostic_text = Text(f"Révision du snapshot : {snapshot.revision}\n\n")
        diagnostic_text.append(harnesses)
        self._base_query_one("#settings-dashboard", SettingsDashboard).update_values({
            "behavior": Text(
                f"Thème utilisateur : {getattr(self.shell, 'theme', 'default')}\n\n"
                "Le mode d’exécution se choisit au lancement de l’opération.\n"
                f"Mode par défaut : {DEFAULT_AGENT_EXECUTION_MODE}"
            ),
            "harnesses": harnesses,
            "workflow": workflow,
            "autonomy": autonomy,
            "storage": Text(
                f"Préférences utilisateur\n{user_preferences_path()}\n\n"
                f"Données LoopForge\n{loopforge_home()}"
            ),
            "diagnostics": diagnostic_text,
        })

    def _render_run(self, snapshot: UiSnapshot) -> None:
        """Render the dedicated live surface from immutable run state."""

        shell = snapshot.run.shell
        header = self.query_one("#run-header", RunHeader)
        sidebar = self.query_one("#run-context", RunContextSidebar)
        action_dock = self.query_one("#run-required-action", RunRequiredAction)
        command_bar = self.query_one("#run-command-bar", RunCommandBar)
        compact_context = self.query_one("#run-compact-context", Static)
        separator = run_glyph(" · ", " - ")

        if shell is None or shell.run is None:
            unknown = run_glyph("—", "-")
            header.update_content(
                version=__version__,
                project=self.shell.project_dir.name,
                run_number=None,
                title="Loading run",
                branch=snapshot.project.branch,
                status="Loading",
                status_color="#958EA0",
            )
            sidebar.update_content(
                status="Loading",
                status_color="#958EA0",
                progress=unknown,
                uptime=unknown,
                tokens=unknown,
                steps=(),
                current_stage="",
                project=self.shell.project_dir.name,
                branch=snapshot.project.branch,
                pack=unknown,
                adapter=str(getattr(self.shell, "selected_adapter", "default")),
            )
            compact_context.update(
                "Loading run context..." if unknown == "-" else "Loading run context…"
            )
            self._render_run_activity(snapshot)
            action_dock.update_action(None)
            command_bar.display = True
            return

        label, _, _ = FAMILY_PRESENTATION[shell.family]
        status_color = _family_color(shell.family)
        progress = _run_progress(shell.stages)
        uptime = _run_uptime(snapshot.run.created_at)
        tokens = _compact_count(snapshot.run.total_tokens)
        adapter = snapshot.run.agent.adapter or str(
            getattr(self.shell, "selected_adapter", "default")
        )
        project_name = shell.project.name
        pack = shell.project.pack or "none"
        branch = snapshot.project.branch
        header_status = "Waiting for approval" if shell.family == "needs_human" else label

        header.update_content(
            version=__version__,
            project=project_name,
            run_number=_run_sequence_number(snapshot),
            title=shell.run.task,
            branch=branch,
            status=header_status,
            status_color=status_color,
        )
        from loopforge.cli.agent_plan import project_agent_plan
        selected_plan = project_agent_plan(snapshot.run.agent.structured_events)
        sidebar.update_content(
            status=label,
            status_color=status_color,
            progress=progress,
            uptime=uptime,
            tokens=tokens,
            steps=shell.stages,
            current_stage=shell.run.current_stage,
            project=project_name,
            branch=branch,
            pack=pack,
            adapter=adapter,
            selected_stage=snapshot.run.reading.stage_id or snapshot.run.agent.stage_id or shell.run.current_stage,
            view=snapshot.run.reading.view, metrics=snapshot.run.metrics,
            problems=shell.blockers[:5],
            agent_plan=selected_plan,
            plan_stage=snapshot.run.agent.stage_id,
            plan_scope=f"{snapshot.selected_run_id}:{snapshot.run.agent.stage_id}:{snapshot.run.agent.session_id}",
        )
        self._render_run_reading_controls(snapshot)
        compact_context.update(
            separator.join((label, progress, project_name, branch, adapter))
        )
        self._render_run_activity(snapshot)

        required_action = self._available_run_action(snapshot)
        busy = self._run_operation_busy(snapshot)
        stage_title = next((stage.title for stage in shell.stages
                            if stage.id == shell.run.current_stage), shell.run.current_stage)
        action_dock.update_action(required_action, blocked=shell.family == "blocked" and not busy,
                                  approval=shell.family == "needs_human", stage=stage_title)
        command_bar.display = True

    def _run_operation_busy(self, snapshot: UiSnapshot) -> bool:
        return bool(self._refreshing_after_operation
                    or (self._operation is not None and not self._operation.finished)
                    or (snapshot.operation.state == "loading" and not snapshot.operation.finished))

    def _available_run_action(self, snapshot: UiSnapshot) -> ActionDescriptor | None:
        shell = snapshot.run.shell
        if (not shell or not shell.run or self._run_operation_busy(snapshot)
                or shell.family not in {"ready", "needs_human", "blocked"}):
            return None
        action = shell.run.next_action
        return action if action and getattr(action, "available", True) else None

    def _render_run_reading_controls(self, snapshot: UiSnapshot) -> None:
        reading = snapshot.run.reading
        view = reading.view
        self.query_one("#run-dashboard").set_class(view == "Changes", "changes-view")
        agent = snapshot.run.agent
        shell = snapshot.run.shell
        stage = reading.stage_id or agent.stage_id or (shell.run.current_stage if shell and shell.run else "")
        sessions = tuple(x for x in snapshot.run.sessions if x.get("stage_id") == stage)
        selected_session = reading.session_id or agent.session_id
        latest = str(sessions[-1].get("session_id") or "") if sessions else ""
        is_historical = bool(stage != (shell.run.current_stage if shell and shell.run else stage)
                             or (selected_session and latest and selected_session != latest))
        self.query_one("#run-selection-stage", Static).update(
            f"{stage.title()} · " + ("selected history" if is_historical else "latest retained"))
        options = tuple((str(x["label"]), str(x["session_id"])) for x in sessions)
        picker = self.query_one("#run-session-select", Select)
        signature = stage, options
        self._syncing_session_select = True
        try:
            if signature != self._session_options_signature:
                picker.set_options(options)
                self._session_options_signature = signature
            selected = reading.session_id or agent.session_id
            if options:
                valid = {value for _, value in options}
                chosen = selected if selected in valid else options[-1][1]
                if picker.value != chosen:
                    picker.value = chosen
            elif picker.value is not Select.NULL:
                picker.value = Select.NULL
        finally:
            self._syncing_session_select = False
        for mode in ("Focused", "All", "Raw"):
            self.query_one("#run-mode-" + mode.lower(), Button).set_class(reading.mode == mode, "selected")
        self.query_one("#run-reading-controls").display = view == "Live"
        self.query_one("#run-changes-controls").display = view == "Changes"
        for name in ("attempt", "cumulative"):
            self.query_one("#run-diff-" + name, Button).set_class(
                (name == "cumulative") == reading.cumulative, "selected")
        feed = self.query_one("#run-activity-feed", RunActivityFeed)
        documents = self.query_one("#run-document-view", RunDocumentView)
        explorer = self.query_one("#run-changes-explorer", RunChangesExplorer)
        feed.display = view == "Live"
        documents.display = view in {"Context", "Evidences"}
        explorer.display = view == "Changes"
        if view == "Live":
            return
        if view == "Changes":
            selected_session = reading.session_id or agent.session_id
            explorer.update_changes(
                (snapshot.selected_run_id, stage, selected_session, reading.cumulative),
                snapshot.run.changes, cumulative=reading.cumulative,
                session_label=next(
                    (str(session.get("label") or "") for session in sessions
                     if session.get("session_id") == selected_session),
                    "",
                ),
            )
            return
        sections: list[tuple[str, str, str, bool]] = []
        markdown_keys: set[str] = set()
        previews: dict[str, tuple[str, str]] = {}
        if view == "Context":
            context = snapshot.run.context
            if context is not None:
                for part in context.sections:
                    markdown_keys.add(part.id)
                    sections.append((part.id, part.title,
                                    (f"Source: {part.source} · {part.authority}\n" if part.source else "") + part.content,
                                    part.expanded))
                if context.raw_prompt:
                    note = "Display is bounded / redacted when required; original source retained locally."
                    sections.append(("raw", "Raw Prompt · " + str(context.capture_state), note + "\n" + context.raw_prompt, False))
                if context.message:
                    sections.insert(0, ("context-note", "Capture information", context.message, True))
            if not sections:
                sections.append(("empty", "Context", "No captured context for this execution.", True))
        else:
            evidence = snapshot.run.evidences
            if evidence is not None:
                for section in evidence.sections:
                    sections.append((section.key, section.title, section.body, section.expanded))
                    for record in section.records:
                        sections.append((record.key, "  " + record.title, record.body, False))
                        if record.preview:
                            previews[record.key] = (record.preview, record.language)
            if not sections:
                sections.append(("no-evidence", "Evidences", "No retained evidence for this selection.", True))
        documents.update_sections((snapshot.selected_run_id, stage, agent.session_id, view,
                                   reading.cumulative), tuple(sections),
                                  markdown_keys=frozenset(markdown_keys), previews=previews)

    def _render_run_activity(self, snapshot: UiSnapshot) -> None:
        activity = self.query_one("#run-activity-feed", RunActivityFeed)
        task = task_summary(snapshot)
        self.query_one("#run-task-summary", Static).display = task is not None
        self.query_one("#run-agent-output-panel").display = task is None
        self.query_one("#run-attempt-heading").display = task is None
        if task is not None:
            self.query_one("#run-task-summary", Static).update(task)
            self.query_one("#run-reading-controls").display = False
            self.query_one("#run-selection").display = False
        else:
            self.query_one("#run-selection").display = True
        reading = snapshot.run.reading
        agent = snapshot.run.agent
        scope = (_snapshot_run_identity(snapshot), agent.stage_id, agent.session_id, reading.mode)
        if scope != self._run_scope:
            self._run_scope = scope
            self._run_follow_tail = reading.following
            if not reading.following:
                self.call_after_refresh(lambda: activity.scroll_to(y=reading.scroll_y, animate=False))
        owns_operation = (self._operation_run_identity == _snapshot_run_identity(snapshot)
                          and not reading.stage_id and not reading.session_id)
        live = owns_operation and snapshot.operation.state == "loading" and not snapshot.operation.finished
        raw_mode = reading.mode == "Raw"
        entries = None
        body = _run_activity_text(snapshot, include_operation_events=owns_operation)
        if raw_mode:
            raw = agent.raw_output
            title = f"Raw source: {agent.raw_source or 'unavailable'} · bounded capture"
            from loopforge.cli.textual_app.run_presenter import TranscriptEntry
            entries = (TranscriptEntry("raw", "info", title,
                                      raw or "No raw source captured for this execution."),)
            body = Text(title + "\n" + (raw or "No raw source captured."))
        elif agent.structured_events:
            entries = tuple(entry for entry in project_events(
                agent.structured_events, mode=reading.mode,
                session_closed=agent.session_closed,
                verified_changes=snapshot.run.changes,
            ) if entry.kind != "plan")
            body = Text("\n".join(e.title + "\n" + e.body for e in entries))
        activity.update_content(
            heading=_run_attempt_heading(snapshot), system_prompt="",
            agent_output=body, implementation_contract=agent.implementation_contract,
            adapter=agent.adapter or str(getattr(self.shell, "selected_adapter", "default")),
            active=live and not agent.session_closed, scope=scope, entries=entries)
        result = self.query_one("#run-execution-result")
        receipt = self.query_one("#run-result-text", Static)
        facts = execution_result(snapshot, active=live)
        result.display = facts is not None
        if facts is not None:
            receipt.update(facts)
        event_count = agent.event_count
        if reading.following:
            self._seen_events[scope] = event_count
        unseen = max(0, event_count - self._seen_events.get(scope, event_count))
        follow = self.query_one("#run-follow", Button)
        follow.label = ("Following live" if reading.following else
                        f"↓ {unseen} new events · Follow live" if unseen else "↓ Follow live")
        if (reading.following and self._run_follow_tail and reading.view == "Live"
                and (agent.session_id or owns_operation)):
            self.call_after_refresh(self._follow_run_activity_tail)
        self.query_one("#run-command-bar", RunCommandBar).update_hint(
            self._operation_status(snapshot)
            if owns_operation and snapshot.operation.state != "empty" else "")

    @on(Collapsible.Expanded)
    def _on_tool_expanded(self, event: Collapsible.Expanded) -> None:
        if isinstance(event.collapsible, (RunToolEntry, RunDelegationEntry)):
            self._suspend_run_follow()

    def _suspend_run_follow(self) -> None:
        if self._screen != "run":
            return
        self._run_follow_tail = False
        feed = self.query_one("#run-activity-feed", RunActivityFeed)
        self.store.save_reading_position(scroll_y=feed.scroll_y, following=False)
        self.store.invalidate("run-reading-position")
        self.store.flush()

    def action_run_follow(self) -> None:
        if self._screen != "run":
            return
        self._run_follow_tail = True
        self.store.select_reading(view="Live", stage_id="", session_id="",
                                  following=True, scroll_y=0)
        self._follow_run_activity_tail()

    def action_run_detail(self) -> None:
        if self._screen != "run":
            return
        focus = self.focused
        element = focus
        while element is not None and not isinstance(element, (RunToolEntry, RunDetailEntry, RunDelegationEntry, RunDocumentView)):
            element = element.parent
        if element is None:
            return
        if isinstance(element, (RunDetailEntry, RunDocumentView)):
            self.query_one("#run-document-view", RunDocumentView).open_selected()
            return
        self._suspend_run_follow()
        if isinstance(element, (RunToolEntry, RunDelegationEntry)):
            self.push_screen(RunDetailScreen(element.entry.title, element.entry.body))
        else:
            self.push_screen(RunDetailScreen(str(element.title), element.body))

    def action_run_supervision(self) -> None:
        if self._screen == "run":
            self.push_screen(RunSupervisionScreen(self._snapshot), self._on_supervision_selected)

    def _on_supervision_selected(self, choice: tuple[str, str] | None) -> None:
        if choice:
            self._change_run_reading(**{choice[0]: choice[1]})

    def action_run_required_action(self) -> None:
        if self._screen == "run" and len(self.screen_stack) == 1:
            action = self._available_run_action(self._snapshot)
            if action is not None:
                self.request_action(action)

    def _change_run_reading(self, **changes: object) -> None:
        if self._screen != "run":
            return
        feed = self.query_one("#run-activity-feed", RunActivityFeed)
        if "stage_id" in changes:
            changes["session_id"] = ""
        changes.setdefault("following", False)
        changes.setdefault("scroll_y", 0.0)
        self._run_follow_tail = False
        self.store.select_reading(**changes)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        name = event.button.id or ""
        if self._screen != "run":
            return
        if name.startswith("run-view-"):
            self._change_run_reading(view=name.removeprefix("run-view-").title())
        elif name.startswith("run-mode-"):
            self._change_run_reading(mode=name.removeprefix("run-mode-").title())
        elif name == "run-follow":
            self.action_run_follow()
        elif name == "run-compact-tabs":
            self.action_run_supervision()
        elif name == "run-diff-attempt":
            self._change_run_reading(cumulative=False)
        elif name == "run-diff-cumulative":
            self._change_run_reading(cumulative=True)
        elif name == "run-problems":
            self._change_run_reading(view="Evidences")

    def on_run_document_view_open_requested(self, event: RunDocumentView.OpenRequested) -> None:
        event.stop()
        self.push_screen(RunDetailScreen(event.title, event.body))

    def on_select_changed(self, event: Select.Changed) -> None:
        if (self._screen == "run" and event.select.id == "run-session-select"
                and not self._syncing_session_select and event.value is not Select.NULL):
            selected = str(event.value)
            if selected != self._snapshot.run.agent.session_id:
                self._change_run_reading(session_id=selected)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if (self._screen == "run" and event.option_list.id == "run-context-steps"
                and event.option.id):
            self._change_run_reading(stage_id=event.option.id)

    def on_run_activity_feed_reading_moved(self, event: RunActivityFeed.ReadingMoved) -> None:
        if self._screen == "run":
            self._suspend_run_follow()

    def _follow_run_activity_tail(self) -> None:
        if self._run_follow_tail:
            self.query_one("#run-activity-feed", RunActivityFeed).scroll_end(
                animate=False, force=True, x_axis=False
            )

    def _render_operation_panel(self, snapshot: UiSnapshot) -> None:
        """Render factual operation state while preserving literal adapter output."""

        try:
            panel = self.query_one("#operation-panel", Container)
            status = self.query_one("#operation-status", Static)
            log = self.query_one("#operation-log", Static)
        except NoMatches:
            return
        operation = snapshot.operation
        panel.display = operation.state != "empty"
        if operation.state == "empty":
            return
        status.update(self._operation_status(snapshot))
        log.update(_operation_log(operation.events))
        # The bounded log must always leave the most recent adapter event visible.
        log.scroll_end(animate=False, x_axis=False)

    def _refresh_operation_status(self) -> None:
        """Advance the spinner and elapsed time without repainting the screen."""

        if self._snapshot.operation.state == "empty":
            return
        if self._screen == "run":
            try:
                self.query_one("#run-command-bar", RunCommandBar).update_hint(
                    self._operation_status(self._snapshot)
                )
            except NoMatches:
                pass
            return
        try:
            self.query_one("#operation-status", Static).update(self._operation_status(self._snapshot))
        except NoMatches:
            return

    def _operation_status(self, snapshot: UiSnapshot) -> str:
        operation = snapshot.operation
        running = operation.state == "loading" and not operation.finished
        spinner = "|/-\\" if _ascii_only() else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        marker = (
            spinner[self._operation_spinner_phase % len(spinner)]
            if running
            else _operation_marker(operation.state)
        )
        progress = operation.events[-1] if operation.events else None
        separator = run_glyph(" · ", " - ")
        suffix = (
            f"{separator}{progress.current}/{progress.total}"
            if progress is not None and progress.current is not None and progress.total is not None
            else ""
        )
        elapsed = self._operation.elapsed_seconds() if running and self._operation is not None else operation.elapsed_seconds
        state = "Running" if running else operation.state.replace("_", " ").title()
        return separator.join(
            (f"{marker} {state}", operation.label, self._operation_run_label, _format_elapsed(elapsed))
        ) + suffix

    def _apply_shell_theme(self) -> None:
        """Keep the TUI palette aligned with the shell's persisted theme."""

        theme = textual_theme_name(str(getattr(self.shell, "theme", "default")))
        if self.theme != theme:
            self.theme = theme

    def _adapter_diagnostics(self) -> dict[str, str]:
        """Report executable availability without probing adapters or changing config.

        The first invocation probes ``PATH`` via :func:`shutil.which`; every
        subsequent call reuses the cached result so the render path never
        performs filesystem I/O.
        """

        if self._adapter_diagnostic_cache is not None:
            return self._adapter_diagnostic_cache
        diagnostics: dict[str, str] = {}
        for adapter in SUPPORTED_ADAPTERS:
            command = AGENT_COMMANDS.get(adapter)
            if command is None:
                diagnostics[adapter] = "fixture adapter; configure its command through /adapter"
            elif shutil.which(command):
                diagnostics[adapter] = f"{command} available on PATH"
            else:
                diagnostics[adapter] = f"{command} not found on PATH; install it before running"
        self._adapter_diagnostic_cache = diagnostics
        return diagnostics

    def _screen_layout(
        self, snapshot: UiSnapshot
    ) -> tuple[str, str, tuple[object, ...], Callable[[object], str] | None, str, str]:
        if self._screen == "home":
            projects = self._filtered_projects()
            recent = tuple(snapshot.home.runs[:5])
            recent_lines = [_run_line(row) for row in recent] or ["No recent runs."]
            before = "Projects" if projects else "Projects\nNo registered projects."
            after = "Recent runs\n" + "\n".join(recent_lines)
            return "LoopForge", before, projects, _project_line, after, "Enter open · Ctrl+P projects · n new run · Ctrl+K actions"
        if self._screen == "project":
            project = snapshot.project.project or self.shell.project_dir
            runs = self._filtered_runs()
            before = f"{project.name} · {snapshot.project.branch} · {len(snapshot.project.runs)} runs\n\nRuns"
            if not runs:
                before += "\nNo runs yet. Press n to create one."
            after = ""
            if snapshot.project.blockers:
                after = "\n\nProject health\n" + "\n".join(f"× {item}" for item in snapshot.project.blockers)
            return project.name, before, runs, _run_line, after, "Enter open · / filter · n new · a archive · Esc projects"
        if self._screen == "evidence":
            if self._evidence_preview:
                return "Evidence", self._evidence_page_text(), (), None, "", "Esc list · c copy · x export · PgUp/PgDn navigate"
            items = self._visible_evidence()
            before = "Evidence" if items else "Evidence\nNo evidence available."
            return "Evidence", before, items, _evidence_line, "", "Enter open · / search · c copy · x export · Esc run"
        raise ValueError(f"No legacy layout for screen: {self._screen}")

    def _filtered_projects(self) -> tuple[object, ...]:
        return _filter_rows(self._snapshot.home.projects, self._filter)

    def _filtered_runs(self) -> tuple[object, ...]:
        return _filter_rows(self._snapshot.project.runs, self._filter)

    def _visible_evidence(self) -> tuple[EvidenceItem, ...]:
        return tuple(self._snapshot.evidence.items)  # StateStore publishes only indexed items.

    def _state_label(self, snapshot: UiSnapshot) -> str:
        state = getattr(snapshot, self._screen).state
        if self._screen == "run" and snapshot.project.project is not None:
            return f"{snapshot.project.project.name} · {state} · revision {snapshot.revision}"
        return f"{state} · revision {snapshot.revision}"

    def _set_width_class(self, width: int) -> None:
        from loopforge.cli.terminal_capabilities import width_class_for

        self.remove_class("width-60", "width-80", "width-120", "width-160")
        self.add_class(width_class_for(width))
        # Unlike global responsive widths, Changes can stay two-pane at 60 cols.
        self.set_class(width < 52, "changes-ultra-narrow")

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


def _project_line(row: object) -> str:
    value = dict(row) if hasattr(row, "items") else {}
    return f"{value.get('attention', 'ready')}  {value.get('name', 'unknown')} · {value.get('run_count', 0)} runs"


def _run_line(row: object) -> str:
    value = dict(row) if hasattr(row, "items") else {}
    return f"{value.get('attention', value.get('status', 'ready'))}  {value.get('task') or value.get('run_id', 'Untitled run')}"


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


def _clip(value: object, width: int) -> str:
    text = str(value or "")
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def _home_marker(attention: object) -> tuple[str, str]:
    return {
        "needs_human": ("◆", "#FFB869"),
        "blocked": ("×", "#FFB4AB"),
        "running": ("●", "#D0BCFF"),
        "complete": ("✓", "#A8E6B0"),
        "ready": ("•", "#C7C6C6"),
        "waiting": ("○", "#C7C6C6"),
        "archived": ("–", "#958EA0"),
    }.get(str(attention or ""), ("", "#C7C6C6"))


def _home_project_line(row: object, *, width: int) -> Text:
    value = dict(row) if hasattr(row, "items") else {}
    marker, marker_color = _home_marker(value.get("attention"))
    prefix = f"{marker} " if marker else "  "
    count = f"{int(value.get('run_count') or 0)} runs"
    name_width = max(8, width - len(prefix) - len(count) - 1)
    name = _clip(value.get("name") or "unknown", name_width)
    line = f"{prefix}{name:<{name_width}} {count}"
    text = Text(line)
    if marker:
        text.stylize(marker_color, 0, 1)
    return text


def _home_run_line(row: object, *, aggregate: bool, width: int) -> Text:
    value = dict(row) if hasattr(row, "items") else {}
    marker, marker_color = _home_marker(value.get("attention"))
    prefix = f"{marker} " if marker else "  "
    leading = (
        str(value.get("project") or "unknown")
        if aggregate
        else str(value.get("status") or value.get("attention") or "ready")
        .replace("_", " ")
        .title()
    )
    age = _relative_age(value.get("updated_at") or value.get("created_at"))
    usable = max(12, width - len(prefix) - len(age) - 2)
    leading_width = min(18, max(10, usable // 3))
    task_width = max(1, usable - leading_width - 1)
    leading = _clip(leading, leading_width)
    task = _clip(value.get("task") or value.get("run_id") or "Untitled run", task_width)
    line = f"{prefix}{leading:<{leading_width}} {task:<{task_width}}  {age}"
    text = Text(line)
    if marker:
        text.stylize(marker_color, 0, 1)
    return text


def _relative_age(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
    except ValueError:
        return "—"
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _evidence_line(item: object) -> str:
    return f"{getattr(item, 'label', 'File')}  {getattr(item, 'relative_path', '')}"


def _operation_result(operation: OperationController, value: object, cancelled: bool) -> SimpleNamespace:
    exit_code = getattr(value, "exit_code", 0)
    show_cancelled = operation.cancelled and operation.is_cancellable
    ok = not show_cancelled and exit_code == 0
    return SimpleNamespace(
        ok=ok,
        run_id=getattr(value, "run_id", None),
        context_changed=bool(getattr(value, "context_changed", False)),
        should_exit=bool(getattr(value, "should_exit", False)),
        message=(
            "Operation cancelled."
            if show_cancelled
            else str(getattr(value, "message", "Action completed." if ok else "Action was blocked."))
        ),
    )


def _snapshot_run_label(snapshot: UiSnapshot) -> str:
    shell = snapshot.run.shell
    if shell is not None and shell.run is not None:
        return shell.run.short_id
    if snapshot.selected_run_id:
        return snapshot.selected_run_id[:16]
    return "current run"


def _run_sequence_number(snapshot: UiSnapshot) -> int | None:
    """Return the stable chronological run ordinal shown in the header."""

    shell = snapshot.run.shell
    if shell is None or shell.run is None:
        return None
    rows = sorted(
        snapshot.project.runs,
        key=lambda row: (
            str(row.get("created_at") or ""),
            str(row.get("run_id") or row.get("id") or ""),
        ),
    )
    for index, row in enumerate(rows, start=1):
        if str(row.get("run_id") or row.get("id") or "") == shell.run.id:
            return index
    return len(rows) + 1


def _snapshot_run_identity(snapshot: UiSnapshot) -> tuple[str, str] | None:
    shell = snapshot.run.shell
    if shell is None or shell.run is None:
        return None
    return str(snapshot.selected_project), shell.run.id


def _operation_log(events: Iterable[object], *, limit: int = 8) -> str:
    """Return the literal, multiline-safe tail in receipt order."""

    rows: list[str] = []
    for event in tuple(events)[-limit:]:
        kind = str(getattr(event, "kind", "activity")).replace("_", " ")
        message = str(getattr(event, "message", "Working…")).strip()
        lines = message.splitlines() or ["Working…"]
        rows.append(f"{_event_marker(kind)} {kind}: {lines[0]}")
        rows.extend(f"  {line}" for line in lines[1:])
    return "\n".join(rows) if rows else "Waiting for the first update…"


def _operation_marker(state: str) -> str:
    return {
        "ready": run_glyph("✓", "+"),
        "failed": run_glyph("×", "x"),
        "blocked": run_glyph("×", "x"),
    }.get(state, run_glyph("•", "*"))


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remaining = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{remaining:02}"
