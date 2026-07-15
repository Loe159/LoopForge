"""Prompt-toolkit full-screen navigation for the interactive LoopForge shell.

This module deliberately owns only the screen layout and keyboard navigation.
Workflow transitions stay in :mod:`loopforge.engine` and are executed through
``InteractiveShell.execute_guided_action``.  It is never imported by scripted
``shell --command`` or ``shell --script`` calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from math import ceil
import os
import shutil
import shlex
import sys
from threading import Timer
from time import perf_counter
from typing import TYPE_CHECKING, Any

from loopforge.cli.presentation import (
    FAMILY_PRESENTATION,
    ShellSnapshot,
    family_presentation,
    shell_snapshot_from_status,
)
from loopforge.cli.operations import ForegroundOperation, OperationEvent
from loopforge.cli.evidence import ApprovalSummary, EvidenceItem, approval_summary, evidence_items, preview_evidence
from loopforge.engine import (
    continue_run,
    current_status,
    execute_readonly_stage,
    list_registered_projects,
    list_runs_from_status,
    resume_run,
    verify_run,
)

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


SCREENS = ("home", "project", "run", "evidence", "settings")


@dataclass
class DebugTiming:
    """Bounded local timing samples for diagnosing one interactive session."""

    count: int = 0
    total_ms: float = 0.0
    samples_ms: list[float] | None = None

    def add(self, milliseconds: float) -> None:
        self.count += 1
        self.total_ms += milliseconds
        if self.samples_ms is None:
            self.samples_ms = []
        # Debug output must remain bounded even in a long-running console.
        if len(self.samples_ms) < 256:
            self.samples_ms.append(milliseconds)

    def summary(self) -> dict[str, float | int]:
        samples = sorted(self.samples_ms or [])
        p95_index = max(0, ceil(len(samples) * 0.95) - 1)
        return {
            "count": self.count,
            "total_ms": round(self.total_ms, 3),
            "median_ms": round(samples[len(samples) // 2], 3) if samples else 0.0,
            "p95_ms": round(samples[p95_index], 3) if samples else 0.0,
        }


def format_run_snapshot(snapshot: ShellSnapshot, *, ascii_mode: bool) -> list[tuple[str, str]]:
    """Format a hydrated run snapshot without filesystem or engine access.

    This is the first explicit render-only boundary.  Later phases move the
    remaining screens behind the same contract; the AST performance contract
    protects this function from accidentally acquiring I/O dependencies.
    """

    if snapshot.run is None:
        return [("class:attention", "* No selected run\n" if ascii_mode else "◆ No selected run\n"), ("", "Create a run from the action palette.")]

    label, marker, role = family_presentation(snapshot.family)
    if ascii_mode:
        marker = {"◆": "*", "●": "o", "◉": "@", "○": "o", "×": "x", "✓": "+", "–": "-"}.get(marker, marker)
    separator = "-" if ascii_mode else "·"
    parts: list[tuple[str, str]] = [
        ("class:brand", f"{snapshot.run.task or 'Untitled run'}  {marker} {label}\n"),
        ("class:secondary", f"{snapshot.run.short_id} {separator} {snapshot.run.current_stage} {separator} {snapshot.run.actor}\n\n"),
    ]
    for stage in snapshot.stages:
        stage_marker = stage.marker
        if ascii_mode:
            stage_marker = {"◆": "*", "●": "o", "◉": "@", "○": "o", "×": "x", "✓": "+", "–": "-"}.get(stage_marker, stage_marker)
        parts.append((f"class:{FAMILY_PRESENTATION[stage.family][2]}", f"{stage_marker} {stage.title}"))
        parts.append(("class:secondary", f"  {stage.actor} {separator} {stage.label}\n"))
    return parts


@dataclass
class ConsoleState:
    """Small, UI-local state; persisted workflow state remains engine-owned."""

    screen: str = "home"
    selected_index: int = 0
    selected_project: Path | None = None
    selected_run_id: str | None = None
    filter_text: str = ""
    evidence_query: str = ""
    evidence_preview: bool = False
    notice: str = ""


def _clip(value: object, width: int = 68) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= width:
        return text
    marker = "..." if ascii_ui_enabled() else "…"
    return text[: max(0, width - len(marker))].rstrip() + marker


def ascii_ui_enabled() -> bool:
    """Use ASCII-safe UI glyphs when explicitly requested or required."""

    if os.environ.get("LOOPFORGE_ASCII") is not None:
        return True
    encoding = getattr(sys.stdout, "encoding", None)
    return bool(encoding and encoding.lower() in {"ascii", "us-ascii"})


class LoopForgeConsole:
    """A keyboard-first, full-screen view over the existing shell facade."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell
        self.state = ConsoleState(selected_project=shell.project_dir)
        self._application: Any = None
        self._body_window: Any = None
        self._dialog_container: Any = None
        self._last_interrupt = False
        self._operation: ForegroundOperation | None = None
        self._operation_events: list[OperationEvent] = []
        self._debug_timings: dict[str, DebugTiming] = defaultdict(DebugTiming)
        self._refresh_requested_at: float | None = None
        self._revision = 0
        self._snapshots: dict[Path, ShellSnapshot] = {}
        self._statuses: dict[Path, Any] = {}
        self._runs: dict[Path, list[dict[str, Any]]] = {}
        self._run_blockers: dict[Path, list[str]] = {}
        self._evidence: dict[Path, tuple[EvidenceItem, ...]] = {}
        self._project_records: list[dict[str, Any]] = []
        self._branches: dict[Path, str] = {}
        self._spinner_timer: Timer | None = None
        self._load_revision(shell.project_dir)

    @property
    def debug_timing_enabled(self) -> bool:
        """Timing is opt-in and stays local to the current console process."""

        return os.environ.get("LOOPFORGE_DEBUG") == "1"

    def debug_timing_summary(self) -> dict[str, dict[str, float | int]]:
        """Return local timing data for diagnostics or the benchmark harness."""

        if not self.debug_timing_enabled:
            return {}
        return {name: metric.summary() for name, metric in sorted(self._debug_timings.items())}

    def _timed_render_callback(self, name: str, callback: Any) -> Any:
        """Wrap a prompt-toolkit callback without changing its rendering contract."""

        def timed() -> Any:
            started_at = perf_counter()
            try:
                return callback()
            finally:
                if self.debug_timing_enabled:
                    finished_at = perf_counter()
                    self._debug_timings[f"render.{name}"].add((finished_at - started_at) * 1_000)
                    if self._refresh_requested_at is not None:
                        self._debug_timings["key_to_render"].add(
                            (finished_at - self._refresh_requested_at) * 1_000
                        )
                        self._refresh_requested_at = None

        return timed

    def _terminal_width(self) -> int:
        return max(60, shutil.get_terminal_size(fallback=(80, 24)).columns)

    def _visible_item_limit(self) -> int:
        height = shutil.get_terminal_size(fallback=(80, 24)).lines
        return max(6, min(40, height - 8))

    def _visible_items(self, items: list[Any]) -> list[tuple[int, Any]]:
        """Return a small selection window instead of rendering an unbounded list."""

        if not items:
            return []
        self.state.selected_index = min(self.state.selected_index, len(items) - 1)
        limit = self._visible_item_limit()
        start = max(0, min(self.state.selected_index - limit // 2, len(items) - limit))
        return list(enumerate(items[start : start + limit], start=start))

    def _marker(self, value: str) -> str:
        if not ascii_ui_enabled():
            return value
        return {
            "◆": "*",
            "●": "o",
            "◉": "@",
            "○": "o",
            "×": "x",
            "✓": "+",
            "–": "-",
            "›": ">",
        }.get(value, value)

    def _line(self, value: object) -> str:
        return _clip(value, self._terminal_width())

    def run(self) -> int:
        """Create and run the prompt-toolkit application only for TTY sessions."""

        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        self._body_window = Window(
            FormattedTextControl(self._timed_render_callback("body", self._body_fragments)),
            wrap_lines=True,
            always_hide_cursor=True,
        )
        root = HSplit(
            [
                Window(FormattedTextControl(self._timed_render_callback("header", self._header_fragments)), height=1),
                Window(height=1, char="-" if ascii_ui_enabled() else "─"),
                self._body_window,
                Window(height=1, char="-" if ascii_ui_enabled() else "─"),
                Window(FormattedTextControl(self._timed_render_callback("footer", self._footer_fragments)), height=1),
            ]
        )
        self._application = Application(
            layout=Layout(root),
            key_bindings=self._key_bindings(),
            full_screen=True,
            mouse_support=False,
            style=self._style(),
        )
        self._application.run()
        return 0

    def _style(self) -> Any:
        from prompt_toolkit.styles import Style

        themes = {
            "default": ("bold cyan", "cyan", "ansibrightcyan"),
            "dark": ("bold ansibrightcyan", "ansibrightcyan", "cyan"),
            "light": ("bold blue", "blue", "ansiblue"),
            "mono": ("bold", "", "bold"),
        }
        brand, ready, running = themes.get(self.shell.theme, themes["default"])
        return Style.from_dict(
            {
                "brand": brand,
                "secondary": "italic",
                "selected": "reverse bold",
                "ready": ready,
                "running": running,
                "attention": "yellow",
                "success": "green",
                "danger": "bold red",
                "muted": "",
            }
        )

    def _key_bindings(self) -> Any:
        from prompt_toolkit.key_binding import KeyBindings

        bindings = KeyBindings()

        @bindings.add("up")
        @bindings.add("k")
        def _up(event: Any) -> None:
            self._move(-1)

        @bindings.add("down")
        @bindings.add("j")
        def _down(event: Any) -> None:
            self._move(1)

        @bindings.add("enter")
        def _enter(event: Any) -> None:
            self._open_selected()

        @bindings.add("escape")
        def _escape(event: Any) -> None:
            self._back()

        @bindings.add("tab")
        def _tab(event: Any) -> None:
            self._cycle_screen()

        @bindings.add("c-p")
        def _projects(event: Any) -> None:
            self.state.screen = "home"
            self.state.notice = "Project selector"
            self._refresh()

        @bindings.add("c-k")
        def _palette(event: Any) -> None:
            self._show_action_palette()

        @bindings.add("?")
        def _help(event: Any) -> None:
            self._show_help()

        @bindings.add("/")
        def _filter(event: Any) -> None:
            self._show_filter()

        @bindings.add("n")
        def _new_run(event: Any) -> None:
            self._show_new_run_dialog()

        @bindings.add("e")
        def _evidence(event: Any) -> None:
            self._load_evidence_snapshot(self._project_path())
            self.state.screen = "evidence"
            self.state.selected_index = 0
            self.state.evidence_preview = False
            self._refresh()

        @bindings.add("o")
        def _open_evidence(event: Any) -> None:
            self._open_selected_evidence()

        @bindings.add("c")
        def _copy_evidence(event: Any) -> None:
            self._copy_selected_evidence()

        @bindings.add("x")
        def _export_evidence(event: Any) -> None:
            self._export_selected_evidence()

        @bindings.add("c-c")
        def _interrupt(event: Any) -> None:
            if self._operation is not None and not self._operation.finished:
                self._operation.cancel()
                self.state.notice = "Cancelling foreground operation…"
                self._refresh()
                return
            if self._dialog_container is not None:
                self._close_dialog()
                return
            if self._last_interrupt:
                event.app.exit()
                return
            self._last_interrupt = True
            self.state.notice = "Press Ctrl+C again to exit."
            self._refresh()

        @bindings.add("l")
        def _toggle_live_output(event: Any) -> None:
            if self._operation is not None:
                self._show_live_output()

        return bindings

    def _header_fragments(self) -> list[tuple[str, str]]:
        project = self._project_path()
        snapshot = self._snapshot(project)
        title = snapshot.project.name
        branch = self._branch_label(project)
        run = snapshot.run.short_id if snapshot.run else "no run"
        if self.shell.statusline == "off":
            return [("class:brand", " LoopForge")]
        suffix = f"  {branch}" if self.shell.statusline == "compact" else f"  {branch}  {run}"
        prefix = f" LoopForge {'-' if ascii_ui_enabled() else '·'} {title}"
        return [("class:brand", self._line(prefix + suffix))]

    def _footer_fragments(self) -> list[tuple[str, str]]:
        footer = {
            "home": "Enter open  ↑↓ select  Ctrl+P projects  Ctrl+K actions  ? help",
            "project": "Enter run  n new  / filter  Esc projects  Ctrl+K actions",
            "run": "Enter primary action  e evidence  Esc runs  Ctrl+K actions  ? help",
            "evidence": "↑↓ select  Enter preview  o open  c copy  x export  / search  Esc run",
            "settings": "Tab screen  Esc back  Ctrl+K actions  ? help",
        }[self.state.screen]
        if self._operation is not None and not self._operation.finished:
            footer = "Ctrl+C cancel  l live output"
        elif self._operation is not None and self._operation.finished:
            footer = "Enter close receipt  e evidence  l live output"
        notice = f"  {self.state.notice}" if self.state.notice else ""
        return [("class:secondary", self._line(footer + notice))]

    def _body_fragments(self) -> list[tuple[str, str]]:
        self._last_interrupt = False
        self._collect_operation_events()
        if self.state.screen == "home":
            return self._home_fragments()
        if self.state.screen == "project":
            return self._project_fragments()
        if self.state.screen == "run":
            return self._run_fragments()
        if self.state.screen == "evidence":
            return self._evidence_fragments()
        return self._settings_fragments()

    def _home_fragments(self) -> list[tuple[str, str]]:
        records = self._projects()
        attention = sum(1 for record in records if record.get("attention") in {"needs_human", "blocked"})
        separator = " - " if ascii_ui_enabled() else " · "
        parts: list[tuple[str, str]] = [("", self._line(f"{len(records)} projects{separator}{attention} need attention") + "\n\n")]
        if not records:
            return parts + [("class:attention", f"{self._marker('◆')} No registered project\n"), ("", "Open the current Git repository to register it.")]
        parts.append(("class:secondary", "Projects\n"))
        for index, record in self._visible_items(records):
            family = str(record.get("attention") or "ready")
            label, marker, role = family_presentation(family)
            prefix = f"{self._marker('›')} " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else f"class:{role}"
            width = self._terminal_width()
            name = _clip(record.get("name") or Path(str(record.get("path") or "")).name, max(16, width - 32))
            details = f"{record.get('run_count', 0)} runs{separator}{label}"
            line = f"{prefix}{self._marker(marker)} {name}"
            if width >= 80:
                line += f"  {details}"
            parts.append((style, self._line(line) + "\n"))
        selected = records[min(self.state.selected_index, len(records) - 1)]
        parts.extend(
            [
                ("\n", ""),
                ("class:secondary", "Selected\n"),
                ("", self._line(selected.get("path")) + "\n"),
                ("", self._line(f"{selected.get('branch') or 'no Git branch'}{separator}last activity {selected.get('last_activity') or 'unknown'}")),
            ]
        )
        return parts

    def _project_fragments(self) -> list[tuple[str, str]]:
        project = self._project_path()
        runs = self._cached_runs(project)
        blockers = self._run_blockers.get(project, [])
        snapshot = self._snapshot(project)
        separator = " - " if ascii_ui_enabled() else " · "
        parts: list[tuple[str, str]] = [("class:brand", self._line(snapshot.project.name) + "\n")]
        parts.append(("class:secondary", self._line(f"{project}{separator}{snapshot.project.profile or 'default'}{separator}{snapshot.project.pack or 'no pack'}") + "\n\n"))
        if blockers:
            return parts + [("class:attention", f"{self._marker('◆')} Project setup required\n"), ("", self._line(blockers[0]))]
        parts.append(("class:secondary", "Runs\n"))
        runs = self._filtered_runs(runs)
        if not runs:
            return parts + [("", "No runs. Press n, then choose Create run in the action palette.")]
        for index, run in self._visible_items(runs):
            family = self._run_family(run)
            label, marker, role = family_presentation(family)
            prefix = f"{self._marker('›')} " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else f"class:{role}"
            width = self._terminal_width()
            task = _clip(run.get("task") or "Untitled run", max(18, width - 24))
            line = f"{prefix}{self._marker(marker)} {task}"
            if width >= 80:
                line += f"  {label}"
            parts.append((style, self._line(line) + "\n"))
        return parts

    def _run_fragments(self) -> list[tuple[str, str]]:
        snapshot = self._snapshot(self._project_path())
        parts = [(style, self._line(fragment.rstrip("\n")) + ("\n" if fragment.endswith("\n") else "")) for style, fragment in format_run_snapshot(snapshot, ascii_mode=ascii_ui_enabled())]
        if snapshot.run is None:
            return parts
        if snapshot.blockers:
            parts.extend([( "\n", ""), ("class:danger", "Blocked\n"), ("", self._line(snapshot.blockers[0]))])
            if snapshot.run.next_action is not None:
                action = snapshot.run.next_action
                parts.extend(
                    [
                        ("\n", ""),
                        ("class:secondary", "Recovery\n"),
                        ("class:ready", action.label + "\n"),
                        ("", action.description + "\n"),
                        ("class:secondary", "Press e to inspect the recorded check or log evidence."),
                    ]
                )
        elif snapshot.run.next_action is not None:
            action = snapshot.run.next_action
            parts.extend(
                [
                    ("\n", ""),
                    ("class:secondary", "Next action\n"),
                    ("class:ready", action.label + "\n"),
                    ("", action.description),
                ]
            )
        parts.extend(self._operation_fragments())
        return parts

    def _evidence_fragments(self) -> list[tuple[str, str]]:
        items = self._evidence_items()
        if not items:
            return [("class:attention", f"{self._marker('◆')} No evidence yet\n"), ("", "This stage has not started.")]
        selected = self._selected_evidence_item(items)
        if selected is not None and self.state.evidence_preview:
            return [
                ("class:secondary", self._line(f"Evidence preview {'-' if ascii_ui_enabled() else '·'} {selected.label}") + "\n"),
                ("class:secondary", selected.relative_path + "\n\n"),
                ("", preview_evidence(selected, query=self.state.evidence_query)),
            ]
        separator = " - " if ascii_ui_enabled() else " · "
        query = f"{separator}search: {self.state.evidence_query}" if self.state.evidence_query else ""
        parts: list[tuple[str, str]] = [("class:secondary", self._line(f"Evidence{separator}{len(items)} items{query}") + "\n")]
        for index, item in self._visible_items(list(items)):
            prefix = f"{self._marker('›')} " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else ""
            parts.append((style, self._line(f"{prefix}[{item.label}] {item.relative_path}") + "\n"))
        return parts

    def _settings_fragments(self) -> list[tuple[str, str]]:
        return [
            ("class:secondary", "Settings\n\n"),
            ("", f"Adapter     {self.shell.selected_adapter}\n"),
            ("", f"Theme       {self.shell.theme}\n"),
            ("", f"Statusline  {self.shell.statusline}\n"),
            ("", f"Keymap      {self.shell.editing_mode}\n"),
            ("", "Theme, statusline, and keymap are saved for this user. Workflow settings remain project-scoped."),
        ]

    def _projects(self) -> list[dict[str, Any]]:
        """Return the current revision's project rows without reloading storage."""

        records = list(self._project_records)
        if self.state.filter_text:
            needle = self.state.filter_text.casefold()
            records = [record for record in records if needle in str(record).casefold()]
        self.state.selected_index = min(self.state.selected_index, max(len(records) - 1, 0))
        return records

    def _snapshot(self, project: Path) -> ShellSnapshot:
        project = project.resolve()
        snapshot = self._snapshots.get(project)
        if snapshot is None:
            raise RuntimeError("TUI snapshot was not loaded for the selected project")
        return snapshot

    def _project_path(self) -> Path:
        return (self.state.selected_project or self.shell.project_dir).resolve()

    @staticmethod
    def _read_branch_label(project: Path) -> str:
        try:
            import subprocess

            result = subprocess.run(["git", "branch", "--show-current"], cwd=project, capture_output=True, text=True, check=False, timeout=3)
            return result.stdout.strip() or "no Git branch"
        except OSError:
            return "no Git branch"

    def _branch_label(self, project: Path) -> str:
        return self._branches.get(project.resolve(), "no Git branch")

    def _load_revision(self, project: Path) -> None:
        """Publish one coherent UI revision before prompt-toolkit renders it.

        Every potentially blocking read is deliberately concentrated here. UI
        callbacks only consume these immutable-ish values until the next
        explicit invalidation point.
        """

        project = project.resolve()
        status = current_status(project)
        snapshot = shell_snapshot_from_status(status)
        runs_result = list_runs_from_status(status)
        records = list(list_registered_projects().projects)
        if not any(Path(str(record.get("path") or "")).resolve() == project for record in records):
            records.insert(
                0,
                {
                    "name": project.name,
                    "path": str(project),
                    "initialized": status.initialized,
                    "run_count": len(runs_result.runs),
                    "attention": snapshot.family,
                    "branch": self._read_branch_label(project),
                    "last_activity": "current session",
                },
            )
        self._revision += 1
        self._statuses = {project: status}
        self._snapshots = {project: snapshot}
        self._runs = {project: list(runs_result.runs)}
        self._run_blockers = {project: list(runs_result.blockers)}
        self._evidence = {}
        self._project_records = records
        self._branches = {project: str(next((record.get("branch") for record in records if Path(str(record.get("path") or "")).resolve() == project), "") or self._read_branch_label(project))}

    def _load_evidence_snapshot(self, project: Path) -> None:
        """Load evidence once when its screen is entered, never from rendering."""

        project = project.resolve()
        if project not in self._evidence:
            self._evidence[project] = evidence_items(self._statuses[project].run_dir)

    def _cached_runs(self, project: Path) -> list[dict[str, Any]]:
        return self._runs.get(project.resolve(), [])

    def _cached_evidence_items(self) -> tuple[EvidenceItem, ...]:
        items = self._evidence.get(self._project_path(), ())
        needle = self.state.evidence_query.strip().casefold()
        if not needle:
            return items
        return tuple(
            item for item in items
            if needle in f"{item.label} {item.relative_path}\n{item.searchable_text}".casefold()
        )

    def _filtered_runs(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.state.filter_text:
            return runs
        needle = self.state.filter_text.casefold()
        return [run for run in runs if needle in str(run).casefold()]

    @staticmethod
    def _run_family(run: dict[str, Any]) -> str:
        status = str(run.get("status") or "")
        if run.get("archived"):
            return "archived"
        if "blocked" in status or "failed" in status:
            return "blocked"
        if "approval" in status or "draft" in status:
            return "needs_human"
        if status in {"verified", "complete", "completed"}:
            return "complete"
        return "ready"

    def _move(self, change: int) -> None:
        counts = {
            "home": len(self._projects()),
            "project": len(self._filtered_runs(self._cached_runs(self._project_path()))),
            "evidence": len(self._cached_evidence_items()),
        }
        count = counts.get(self.state.screen, 0)
        if count:
            self.state.selected_index = (self.state.selected_index + change) % count
        self._refresh()

    def _open_selected(self) -> None:
        if self._operation is not None:
            if self._operation.finished:
                self._stop_spinner_timer()
                self._operation = None
                self._operation_events.clear()
                self._load_revision(self._project_path())
                self.state.notice = "Operation receipt closed."
                self._refresh()
            return
        if self.state.screen == "home":
            records = self._projects()
            if records:
                self.state.selected_project = Path(str(records[self.state.selected_index]["path"])).resolve()
                # The shell is a session object, so changing its project is a
                # navigation choice, not a workflow-state mutation. Guided
                # actions below now target the project visible on screen.
                self.shell.project_dir = self.state.selected_project
                self._load_revision(self.state.selected_project)
                self.state.selected_index = 0
                self.state.screen = "project"
        elif self.state.screen == "project":
            runs = self._filtered_runs(self._cached_runs(self._project_path()))
            if runs:
                self.state.selected_run_id = str(runs[self.state.selected_index].get("run_id") or "")
                result = resume_run(self._project_path(), self.state.selected_run_id)
                if not result.ok:
                    self.state.notice = result.message
                    self._refresh()
                    return
                self._load_revision(self._project_path())
                self.state.selected_index = 0
                self.state.screen = "run"
        elif self.state.screen == "run":
            snapshot = self._snapshot(self._project_path())
            if snapshot.run and snapshot.run.next_action:
                self._confirm_action(snapshot.run.next_action)
        elif self.state.screen == "evidence":
            self._open_selected_evidence()
        self._refresh()

    def _back(self) -> None:
        if self.state.screen == "evidence" and self.state.evidence_preview:
            self.state.evidence_preview = False
            self._refresh()
            return
        back = {"home": "home", "project": "home", "run": "project", "evidence": "run", "settings": "run"}
        self.state.screen = back[self.state.screen]
        self.state.selected_index = 0
        self._refresh()

    def _cycle_screen(self) -> None:
        index = SCREENS.index(self.state.screen)
        self.state.screen = SCREENS[(index + 1) % len(SCREENS)]
        if self.state.screen == "evidence":
            self._load_evidence_snapshot(self._project_path())
        self.state.selected_index = 0
        self._refresh()

    def _evidence_items(self) -> tuple[EvidenceItem, ...]:
        return self._cached_evidence_items()

    def _selected_evidence_item(self, items: tuple[EvidenceItem, ...] | None = None) -> EvidenceItem | None:
        items = self._evidence_items() if items is None else items
        if not items:
            return None
        self.state.selected_index = min(self.state.selected_index, len(items) - 1)
        return items[self.state.selected_index]

    def _open_selected_evidence(self) -> None:
        if self.state.screen != "evidence":
            return
        item = self._selected_evidence_item()
        if item is None:
            self.state.notice = "No evidence is available."
        else:
            self.state.evidence_preview = True
            self.state.notice = f"Opened {item.relative_path}"
        self._refresh()

    def _copy_selected_evidence(self) -> None:
        item = self._selected_evidence_item()
        if item is None:
            self.state.notice = "No evidence is available to copy."
        elif self.shell.copy_to_clipboard(preview_evidence(item)):
            self.state.notice = f"Copied {item.relative_path}"
        else:
            path = self._export_evidence_item(item)
            self.state.notice = f"Clipboard unavailable; exported {path}" if path else "Clipboard unavailable; export failed."
        self._refresh()

    def _export_selected_evidence(self) -> None:
        item = self._selected_evidence_item()
        if item is None:
            self.state.notice = "No evidence is available to export."
        else:
            path = self._export_evidence_item(item)
            self.state.notice = f"Exported {path}" if path else "Evidence export failed."
        self._refresh()

    def _export_evidence_item(self, item: EvidenceItem) -> Path | None:
        status = self._statuses[self._project_path()]
        if status.run_dir is None:
            return None
        destination = status.run_dir / "artifacts" / "exports" / f"{item.path.stem}-evidence{item.path.suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == item.path.resolve():
            destination = destination.with_name(destination.stem + "-copy" + destination.suffix)
        try:
            shutil.copyfile(item.path, destination)
        except OSError:
            return None
        return destination.relative_to(status.run_dir)

    def _show_action_palette(self) -> None:
        from prompt_toolkit.layout.containers import HSplit
        from prompt_toolkit.widgets import Button, Dialog, Label, RadioList

        snapshot = self._snapshot(self._project_path())
        actions = list(snapshot.actions)
        if not actions:
            self.state.notice = "No action is available for this state."
            self._refresh()
            return
        selector = RadioList(values=[(action.id, action.label) for action in actions])

        def selected_action() -> Any:
            return next(action for action in actions if action.id == selector.current_value)

        self._dialog_container = Dialog(
            title="Actions",
            body=HSplit([Label(text="Actions available for this run:"), selector]),
            buttons=[
                Button("Run", handler=lambda: self._confirm_action(selected_action())),
                Button("Cancel", handler=self._close_dialog),
            ],
        )
        self._attach_dialog()

    def _confirm_action(self, action: Any) -> None:
        if not action.requires_confirmation:
            self._close_dialog()
            self._execute_action(action)
            return
        approval = self._approval_summary(action)
        lines = list(approval.lines) if approval is not None else [
            "You approve the evidence and workflow transition shown on this screen.",
            f"Why: {action.description}",
        ]
        lines.append("Permissions follow the selected pack and stage.")
        self._show_dialog(
            approval.title if approval is not None else f"{action.label}?",
            lines,
            [("Approve", lambda: self._execute_action(action)), ("Evidence", self._open_evidence), ("Cancel", self._close_dialog)],
        )

    def _approval_summary(self, action: Any) -> ApprovalSummary | None:
        stages = {"approve-plan": "plan", "approve-review": "review"}
        stage = stages.get(action.id)
        if stage is None:
            return None
        status = self._statuses[self._project_path()]
        return approval_summary(status.run_dir, status.run, stage)

    def _execute_action(self, action: Any) -> None:
        if action.executor_key == "collect-task":
            self._close_dialog()
            self._show_new_run_dialog()
            return
        self._close_dialog()
        if action.executor_key in {"continue", "verify", "run-readonly-stage"}:
            self._start_live_action(action)
            return
        result = self.shell.execute_guided_action(action)
        self._load_revision(self._project_path())
        self.state.notice = "Action completed." if result.exit_code == 0 else "Action was blocked; inspect evidence."
        self.state.screen = "run"
        self._refresh()

    def _start_live_action(self, action: Any) -> None:
        """Run an engine transition in a worker and keep the TUI responsive."""

        if self._operation is not None and not self._operation.finished:
            self.state.notice = "A foreground operation is already running."
            self._refresh()
            return
        operation = ForegroundOperation(action.label)
        self._operation = operation
        self._operation_events = []
        project = self._project_path()

        def runner(emit: Any, cancel_event: Any) -> Any:
            if action.executor_key == "continue":
                return continue_run(
                    project,
                    adapter=self.shell.selected_adapter,
                    adapter_args=self.shell.selected_adapter_args,
                    confirmed=True,
                    operation_callback=emit,
                    cancel_event=cancel_event,
                )
            if action.executor_key == "verify":
                return verify_run(
                    project,
                    confirmed=True,
                    operation_callback=emit,
                    cancel_event=cancel_event,
                )
            stage = next(
                (
                    item.id
                    for item in self._snapshot(project).stages
                    if item.family not in {"complete", "waiting"}
                ),
                "",
            )
            if not stage:
                return execute_readonly_stage(
                    project,
                    stage="research",
                    adapter=self.shell.selected_adapter,
                    adapter_args=self.shell.selected_adapter_args,
                    operation_callback=emit,
                    cancel_event=cancel_event,
                )
            emit({"kind": "stage_started", "message": f"Running read-only {stage}."})
            return execute_readonly_stage(
                project,
                stage=stage,
                adapter=self.shell.selected_adapter,
                adapter_args=self.shell.selected_adapter_args,
                operation_callback=emit,
                cancel_event=cancel_event,
            )

        operation.start(runner)
        self._start_spinner_timer()
        self.state.screen = "run"
        self.state.notice = ""
        self._refresh()

    def _collect_operation_events(self) -> None:
        if self._operation is None:
            return
        self._operation_events.extend(self._operation.drain_events())
        self._operation_events = self._operation_events[-40:]
        if self._operation.finished and not self.state.notice:
            if self._operation.error is not None:
                self.state.notice = "Operation failed; inspect live output."
            elif bool(getattr(self._operation.result, "ok", False)):
                self.state.notice = "Operation completed."
            else:
                self.state.notice = "Operation is blocked; inspect evidence."

    def _start_spinner_timer(self) -> None:
        """Invalidate only the operation panel while a foreground task is active."""

        if self._spinner_timer is not None:
            return

        def tick() -> None:
            operation = self._operation
            if operation is None or operation.finished:
                self._spinner_timer = None
                self._collect_operation_events()
                self._refresh()
                return
            self._collect_operation_events()
            self._refresh()
            self._spinner_timer = Timer(0.125, tick)
            self._spinner_timer.daemon = True
            self._spinner_timer.start()

        self._spinner_timer = Timer(0.125, tick)
        self._spinner_timer.daemon = True
        self._spinner_timer.start()

    def _stop_spinner_timer(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.cancel()
            self._spinner_timer = None

    def _operation_fragments(self) -> list[tuple[str, str]]:
        operation = self._operation
        if operation is None or (operation.elapsed_seconds() < 0.25 and not operation.finished):
            return []
        elapsed = f"{operation.elapsed_seconds():.1f}s"
        latest = self._operation_events[-1] if self._operation_events else None
        if not operation.finished:
            spinner = ("|/-\\" if ascii_ui_enabled() else "◐◓◑◒")[int(operation.elapsed_seconds() * 8) % 4]
            message = latest.message if latest is not None else "Preparing operation…"
            progress = ""
            if latest is not None and latest.current is not None and latest.total is not None:
                progress = f" {latest.current}/{latest.total}"
            return [
                ("\n", ""),
                ("class:running", self._line(f"{spinner} {operation.label} {'-' if ascii_ui_enabled() else '·'} {elapsed}{progress}") + "\n"),
                ("class:secondary", self._line(message)),
            ]
        latest_message = latest.message if latest is not None else operation.label
        ok = operation.error is None and bool(getattr(operation.result, "ok", False))
        role = "success" if ok else "danger"
        marker = self._marker("✓" if ok else "×")
        return [
            ("\n", ""),
            (f"class:{role}", self._line(f"{marker} {latest_message} {'-' if ascii_ui_enabled() else '·'} {elapsed}") + "\n"),
            ("class:secondary", "Enter closes this receipt · l shows activity"),
        ]

    def _show_live_output(self) -> None:
        if self._operation is None:
            return
        lines = [event.message for event in self._operation_events[-12:]] or ["No output yet."]
        self._show_dialog("Live operation output", lines, [("Close", self._close_dialog)])

    def _open_evidence(self) -> None:
        self._close_dialog()
        self._load_evidence_snapshot(self._project_path())
        self.state.screen = "evidence"
        self.state.selected_index = 0
        self.state.evidence_preview = False
        self._refresh()

    def _show_help(self) -> None:
        self._show_dialog(
            "Keyboard shortcuts",
            ["↑/↓ or j/k select", "Enter opens or runs the primary action", "Esc goes back", "Ctrl+P projects", "Ctrl+K actions", "/ filters", "Ctrl+C cancels a dialog, then exits"],
            [("Close", self._close_dialog)],
        )

    def _show_new_run_dialog(self) -> None:
        from prompt_toolkit.layout.containers import HSplit
        from prompt_toolkit.widgets import Button, Dialog, Label, TextArea

        field = TextArea(multiline=False, prompt="Task: ")

        def create() -> None:
            task = field.text.strip()
            if not task:
                self.state.notice = "A task is required to create a run."
                self._refresh()
                return
            self._close_dialog()
            result = self.shell.cmd_run(f"--task {shlex.quote(task)}")
            self._load_revision(self._project_path())
            self.state.notice = "Run created." if result.exit_code == 0 else "Run creation was blocked."
            self.state.screen = "run" if result.exit_code == 0 else self.state.screen
            self._refresh()

        self._dialog_container = Dialog(
            title="Create run",
            body=HSplit([Label(text="Describe the task to start the supervised workflow."), field]),
            buttons=[Button("Create", handler=create), Button("Cancel", handler=self._close_dialog)],
        )
        self._attach_dialog()

    def _show_filter(self) -> None:
        from prompt_toolkit.layout.containers import HSplit
        from prompt_toolkit.widgets import Button, Dialog, TextArea

        is_evidence = self.state.screen == "evidence"
        field = TextArea(text=self.state.evidence_query if is_evidence else self.state.filter_text, multiline=False)

        def apply() -> None:
            if is_evidence:
                self.state.evidence_query = field.text.strip()
                self.state.evidence_preview = False
            else:
                self.state.filter_text = field.text.strip()
            self.state.selected_index = 0
            self._close_dialog()
            self._refresh()

        self._dialog_container = Dialog(
            title="Filter",
            body=HSplit([field]),
            buttons=[Button("Apply", handler=apply), Button("Clear", handler=lambda: self._clear_filter()), Button("Cancel", handler=self._close_dialog)],
        )
        self._attach_dialog()

    def _clear_filter(self) -> None:
        if self.state.screen == "evidence":
            self.state.evidence_query = ""
            self.state.evidence_preview = False
        else:
            self.state.filter_text = ""
        self.state.selected_index = 0
        self._close_dialog()
        self._refresh()

    def _show_dialog(self, title: str, lines: list[str], buttons: list[tuple[str, Any]]) -> None:
        from prompt_toolkit.layout.containers import HSplit
        from prompt_toolkit.widgets import Button, Dialog, Label

        self._dialog_container = Dialog(
            title=title,
            body=HSplit([Label(text=line) for line in lines]),
            buttons=[Button(label, handler=handler) for label, handler in buttons],
        )
        self._attach_dialog()

    def _attach_dialog(self) -> None:
        from prompt_toolkit.layout.containers import Float, FloatContainer

        assert self._application is not None
        root = self._application.layout.container
        if isinstance(root, FloatContainer):
            root.floats[:] = [Float(content=self._dialog_container)]
        else:
            self._application.layout.container = FloatContainer(content=root, floats=[Float(content=self._dialog_container)])
        self._application.layout.focus(self._dialog_container)
        self._refresh()

    def _close_dialog(self) -> None:
        if self._dialog_container is None:
            return
        from prompt_toolkit.layout.containers import FloatContainer

        if self._application is not None and isinstance(self._application.layout.container, FloatContainer):
            self._application.layout.container.floats.clear()
        self._dialog_container = None
        if self._application is not None and self._body_window is not None:
            self._application.layout.focus(self._body_window)
        self._refresh()

    def _refresh(self) -> None:
        if self.debug_timing_enabled:
            self._refresh_requested_at = perf_counter()
        if self._application is not None:
            self._application.invalidate()
