"""Prompt-toolkit full-screen navigation for the interactive LoopForge shell.

This module deliberately owns only the screen layout and keyboard navigation.
Workflow transitions stay in :mod:`loopforge.engine` and are executed through
``InteractiveShell.execute_guided_action``.  It is never imported by scripted
``shell --command`` or ``shell --script`` calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import TYPE_CHECKING, Any

from loopforge.cli.presentation import (
    FAMILY_PRESENTATION,
    ShellSnapshot,
    family_presentation,
    shell_snapshot,
)
from loopforge.engine import (
    current_guidance,
    current_status,
    list_registered_projects,
    list_runs,
    resume_run,
)

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


SCREENS = ("home", "project", "run", "evidence", "settings")


@dataclass
class ConsoleState:
    """Small, UI-local state; persisted workflow state remains engine-owned."""

    screen: str = "home"
    selected_index: int = 0
    selected_project: Path | None = None
    selected_run_id: str | None = None
    filter_text: str = ""
    notice: str = ""


def _clip(value: object, width: int = 68) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


class LoopForgeConsole:
    """A keyboard-first, full-screen view over the existing shell facade."""

    def __init__(self, shell: "InteractiveShell") -> None:
        self.shell = shell
        self.state = ConsoleState(selected_project=shell.project_dir)
        self._application: Any = None
        self._body_window: Any = None
        self._dialog_container: Any = None
        self._last_interrupt = False

    def run(self) -> int:
        """Create and run the prompt-toolkit application only for TTY sessions."""

        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl

        self._body_window = Window(
            FormattedTextControl(self._body_fragments),
            wrap_lines=True,
            always_hide_cursor=True,
        )
        root = HSplit(
            [
                Window(FormattedTextControl(self._header_fragments), height=1),
                Window(height=1, char="─"),
                self._body_window,
                Window(height=1, char="─"),
                Window(FormattedTextControl(self._footer_fragments), height=1),
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

        return Style.from_dict(
            {
                "brand": "bold cyan",
                "secondary": "italic",
                "selected": "reverse bold",
                "ready": "cyan",
                "running": "ansibrightcyan",
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
            self.state.screen = "evidence"
            self.state.selected_index = 0
            self._refresh()

        @bindings.add("c-c")
        def _interrupt(event: Any) -> None:
            if self._dialog_container is not None:
                self._close_dialog()
                return
            if self._last_interrupt:
                event.app.exit()
                return
            self._last_interrupt = True
            self.state.notice = "Press Ctrl+C again to exit."
            self._refresh()

        return bindings

    def _header_fragments(self) -> list[tuple[str, str]]:
        project = self._project_path()
        snapshot = self._snapshot(project)
        title = snapshot.project.name
        branch = self._branch_label(project)
        run = snapshot.run.short_id if snapshot.run else "no run"
        return [("class:brand", f" LoopForge · {title}"), ("", f"  {branch}  {run}")]

    def _footer_fragments(self) -> list[tuple[str, str]]:
        footer = {
            "home": "Enter open  ↑↓ select  Ctrl+P projects  Ctrl+K actions  ? help",
            "project": "Enter run  n new  / filter  Esc projects  Ctrl+K actions",
            "run": "Enter primary action  e evidence  Esc runs  Ctrl+K actions  ? help",
            "evidence": "↑↓ select  Enter open  Esc run  Ctrl+K actions",
            "settings": "Tab screen  Esc back  Ctrl+K actions  ? help",
        }[self.state.screen]
        notice = f"  {self.state.notice}" if self.state.notice else ""
        return [("class:secondary", footer + notice)]

    def _body_fragments(self) -> list[tuple[str, str]]:
        self._last_interrupt = False
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
        parts: list[tuple[str, str]] = [("", f"{len(records)} projects · {attention} need attention\n\n")]
        if not records:
            return parts + [("class:attention", "◆ No registered project\n"), ("", "Open the current Git repository to register it.")]
        parts.append(("class:secondary", "Projects\n"))
        for index, record in enumerate(records):
            family = str(record.get("attention") or "ready")
            label, marker, role = family_presentation(family)
            prefix = "› " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else f"class:{role}"
            name = _clip(record.get("name") or Path(str(record.get("path") or "")).name, 26)
            details = f"{record.get('run_count', 0)} runs · {label}"
            parts.append((style, f"{prefix}{marker} {name:<28} {details}\n"))
        selected = records[min(self.state.selected_index, len(records) - 1)]
        parts.extend(
            [
                ("\n", ""),
                ("class:secondary", "Selected\n"),
                ("", f"{selected.get('path')}\n"),
                ("", f"{selected.get('branch') or 'no Git branch'} · last activity {selected.get('last_activity') or 'unknown'}"),
            ]
        )
        return parts

    def _project_fragments(self) -> list[tuple[str, str]]:
        project = self._project_path()
        result = list_runs(project)
        snapshot = self._snapshot(project)
        parts: list[tuple[str, str]] = [("class:brand", f"{snapshot.project.name}\n")]
        parts.append(("class:secondary", f"{project} · {snapshot.project.profile or 'default'} · {snapshot.project.pack or 'no pack'}\n\n"))
        if result.blockers:
            return parts + [("class:attention", "◆ Project setup required\n"), ("", result.blockers[0])]
        parts.append(("class:secondary", "Runs\n"))
        runs = self._filtered_runs(result.runs)
        if not runs:
            return parts + [("", "No runs. Press n, then choose Create run in the action palette.")]
        for index, run in enumerate(runs):
            family = self._run_family(run)
            label, marker, role = family_presentation(family)
            prefix = "› " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else f"class:{role}"
            task = _clip(run.get("task") or "Untitled run", 48)
            parts.append((style, f"{prefix}{marker} {task:<50} {label}\n"))
        return parts

    def _run_fragments(self) -> list[tuple[str, str]]:
        snapshot = self._snapshot(self._project_path())
        if snapshot.run is None:
            return [("class:attention", "◆ No selected run\n"), ("", "Create a run from the action palette.")]
        label, marker, role = family_presentation(snapshot.family)
        parts: list[tuple[str, str]] = [
            ("class:brand", f"{snapshot.run.task or 'Untitled run'}  "),
            (f"class:{role}", f"{marker} {label}\n"),
            ("class:secondary", f"{snapshot.run.short_id} · {snapshot.run.current_stage} · {snapshot.run.actor}\n\n"),
        ]
        for stage in snapshot.stages:
            style = f"class:{FAMILY_PRESENTATION[stage.family][2]}"
            parts.append((style, f"{stage.marker} {stage.title}"))
            parts.append(("class:secondary", f"  {stage.actor} · {stage.label}\n"))
        if snapshot.blockers:
            parts.extend([( "\n", ""), ("class:danger", "Blocked\n"), ("", _clip(snapshot.blockers[0]))])
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
        return parts

    def _evidence_fragments(self) -> list[tuple[str, str]]:
        status = current_status(self._project_path())
        if status.run_dir is None:
            return [("class:attention", "◆ No evidence yet\n"), ("", "This stage has not started.")]
        artifacts = status.run_dir / "artifacts"
        paths = sorted(path for path in artifacts.rglob("*") if path.is_file()) if artifacts.exists() else []
        parts: list[tuple[str, str]] = [("class:secondary", "Evidence\n")]
        for index, path in enumerate(paths[:20]):
            prefix = "› " if index == self.state.selected_index else "  "
            style = "class:selected" if index == self.state.selected_index else ""
            parts.append((style, f"{prefix}{path.relative_to(status.run_dir)}\n"))
        if not paths:
            parts.append(("", "This stage has not produced evidence."))
        return parts

    def _settings_fragments(self) -> list[tuple[str, str]]:
        return [
            ("class:secondary", "Settings\n\n"),
            ("", f"Adapter     {self.shell.selected_adapter}\n"),
            ("", f"Theme       {self.shell.theme}\n"),
            ("", f"Keymap      {self.shell.editing_mode}\n"),
            ("", "These are session settings. Workflow permissions are shown with the selected stage."),
        ]

    def _projects(self) -> list[dict[str, Any]]:
        records = list(list_registered_projects().projects)
        current = self.shell.project_dir.resolve()
        if not any(Path(str(record.get("path") or "")).resolve() == current for record in records):
            status = current_status(current)
            records.insert(
                0,
                {
                    "name": current.name,
                    "path": str(current),
                    "initialized": status.initialized,
                    "run_count": len(list_runs(current).runs),
                    "attention": self._snapshot(current).family,
                    "branch": self._branch_label(current),
                    "last_activity": "current session",
                },
            )
        if self.state.filter_text:
            needle = self.state.filter_text.casefold()
            records = [record for record in records if needle in str(record).casefold()]
        self.state.selected_index = min(self.state.selected_index, max(len(records) - 1, 0))
        return records

    def _snapshot(self, project: Path) -> ShellSnapshot:
        return shell_snapshot(current_status(project), current_guidance(project))

    def _project_path(self) -> Path:
        return (self.state.selected_project or self.shell.project_dir).resolve()

    @staticmethod
    def _branch_label(project: Path) -> str:
        try:
            import subprocess

            result = subprocess.run(["git", "branch", "--show-current"], cwd=project, capture_output=True, text=True, check=False, timeout=3)
            return result.stdout.strip() or "no Git branch"
        except OSError:
            return "no Git branch"

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
            "project": len(self._filtered_runs(list_runs(self._project_path()).runs)),
            "evidence": len(self._evidence_paths()),
        }
        count = counts.get(self.state.screen, 0)
        if count:
            self.state.selected_index = (self.state.selected_index + change) % count
        self._refresh()

    def _open_selected(self) -> None:
        if self.state.screen == "home":
            records = self._projects()
            if records:
                self.state.selected_project = Path(str(records[self.state.selected_index]["path"])).resolve()
                # The shell is a session object, so changing its project is a
                # navigation choice, not a workflow-state mutation. Guided
                # actions below now target the project visible on screen.
                self.shell.project_dir = self.state.selected_project
                self.state.selected_index = 0
                self.state.screen = "project"
        elif self.state.screen == "project":
            runs = self._filtered_runs(list_runs(self._project_path()).runs)
            if runs:
                self.state.selected_run_id = str(runs[self.state.selected_index].get("run_id") or "")
                result = resume_run(self._project_path(), self.state.selected_run_id)
                if not result.ok:
                    self.state.notice = result.message
                    self._refresh()
                    return
                self.state.selected_index = 0
                self.state.screen = "run"
        elif self.state.screen == "run":
            snapshot = self._snapshot(self._project_path())
            if snapshot.run and snapshot.run.next_action:
                self._confirm_action(snapshot.run.next_action)
        elif self.state.screen == "evidence":
            paths = self._evidence_paths()
            if paths:
                self.state.notice = str(paths[self.state.selected_index].name)
        self._refresh()

    def _back(self) -> None:
        back = {"home": "home", "project": "home", "run": "project", "evidence": "run", "settings": "run"}
        self.state.screen = back[self.state.screen]
        self.state.selected_index = 0
        self._refresh()

    def _cycle_screen(self) -> None:
        index = SCREENS.index(self.state.screen)
        self.state.screen = SCREENS[(index + 1) % len(SCREENS)]
        self.state.selected_index = 0
        self._refresh()

    def _evidence_paths(self) -> list[Path]:
        status = current_status(self._project_path())
        artifacts = status.run_dir / "artifacts" if status.run_dir else None
        return sorted(path for path in artifacts.rglob("*") if path.is_file()) if artifacts and artifacts.exists() else []

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
        self._show_dialog(
            f"{action.label}?",
            [
                "You approve the evidence and workflow transition shown on this screen.",
                f"Why: {action.description}",
                "Permissions follow the selected pack and stage.",
            ],
            [("Approve", lambda: self._execute_action(action)), ("Evidence", self._open_evidence), ("Cancel", self._close_dialog)],
        )

    def _execute_action(self, action: Any) -> None:
        if action.executor_key == "collect-task":
            self._close_dialog()
            self._show_new_run_dialog()
            return
        self._close_dialog()
        result = self.shell.execute_guided_action(action)
        self.state.notice = "Action completed." if result.exit_code == 0 else "Action was blocked; inspect evidence."
        self.state.screen = "run"
        self._refresh()

    def _open_evidence(self) -> None:
        self._close_dialog()
        self.state.screen = "evidence"
        self.state.selected_index = 0
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

        field = TextArea(text=self.state.filter_text, multiline=False)

        def apply() -> None:
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
        if self._application is not None:
            self._application.invalidate()
