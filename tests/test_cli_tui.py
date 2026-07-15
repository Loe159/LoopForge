"""Contracts for the phase-3 prompt-toolkit navigation model."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from loopforge.cli import main
from loopforge.cli.interactive import InteractiveShell, run_interactive
from loopforge.cli.operations import ForegroundOperation
from loopforge.cli.tui import LoopForgeConsole, SCREENS, _clip, selected_tui_backend
from loopforge.engine import current_status


class CliTuiTests(unittest.TestCase):
    def test_console_declares_the_five_navigation_screens(self) -> None:
        self.assertEqual(SCREENS, ("home", "project", "run", "evidence", "settings"))

    def test_home_keeps_current_project_visible_before_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))

            text = "".join(fragment for _, fragment in console._home_fragments())

        self.assertIn("project", text)
        self.assertIn("current session", text)

    def test_project_screen_uses_pack_driven_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project = workspace / "project"
            project.mkdir()
            home = workspace / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(home)}),
                _working_directory(project),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Render pipeline"]), 0)

            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            console.state.screen = "run"
            text = "".join(fragment for _, fragment in console._run_fragments())

        self.assertIn("Validate task", text)
        self.assertIn("Next action", text)

    def test_headless_shell_does_not_construct_fullscreen_console(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_textual_app = sys.modules.pop("loopforge.cli.textual_app", None)
            with (
                mock.patch("loopforge.cli.tui.LoopForgeConsole") as console_type,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run_interactive(Path(temp_dir), command="/status"), 0)
        console_type.assert_not_called()
        self.assertNotIn("loopforge.cli.textual_app", sys.modules)
        if previous_textual_app is not None:
            sys.modules["loopforge.cli.textual_app"] = previous_textual_app

    @unittest.skipUnless(
        importlib.util.find_spec("prompt_toolkit") is not None,
        "prompt_toolkit is an optional runtime dependency in this source-tree test mode",
    )
    def test_fullscreen_console_is_the_interactive_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shell = InteractiveShell(Path(temp_dir), output=io.StringIO())
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(Path(temp_dir) / "home")}),
                mock.patch("loopforge.cli.tui.LoopForgeConsole") as console_type,
                mock.patch("prompt_toolkit.PromptSession") as session_type,
            ):
                console_type.return_value.run.return_value = 0
                self.assertEqual(shell.run_prompt(), 0)
                console_type.assert_called_once_with(shell)

                shell.renderer_mode = "plain"
                session_type.return_value.prompt.side_effect = EOFError
                self.assertEqual(shell.run_prompt(), 0)
                console_type.assert_called_once()
                session_type.assert_called_once()

    def test_foreground_operation_bridges_events_and_cancellation(self) -> None:
        operation = ForegroundOperation("Verify run")
        cancelled = threading.Event()

        def runner(emit, cancel_event):  # type: ignore[no-untyped-def]
            emit({"kind": "check_started", "message": "Running unit tests.", "current": 1, "total": 2})
            cancel_event.wait(1)
            cancelled.set()
            return type("Result", (), {"ok": False, "message": "Verification interrupted."})()

        operation.start(runner)
        operation.cancel()
        self.assertTrue(cancelled.wait(1))
        self.assertTrue(operation.finished)
        events = operation.drain_events()
        self.assertTrue(any(event.kind == "check_started" for event in events))
        self.assertTrue(any(event.kind == "cancellation_requested" for event in events))
        self.assertTrue(any(event.kind == "cancelled" for event in events))

    def test_second_ctrl_c_exits_after_the_first_interrupt_redraws(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            application = mock.Mock()

            console._handle_interrupt(application)
            console._body_fragments()
            console._handle_interrupt(application)

        self.assertEqual(console.state.notice, "Press Ctrl+C again to exit.")
        application.exit.assert_called_once_with()

    def test_live_operation_receipt_uses_real_worker_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            operation = ForegroundOperation("Verify run")
            console._operation = operation

            operation.start(
                lambda emit, cancel: type(
                    "Result", (), {"ok": True, "message": "Verification passed."}
                )()
            )
            deadline = threading.Event()
            while not operation.finished:
                deadline.wait(0.01)
            console._collect_operation_events()
            console.state.screen = "run"
            text = "".join(fragment for _, fragment in console._operation_fragments())

        self.assertIn("Verification passed", text)

    def test_settings_explains_user_scoped_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            text = "".join(fragment for _, fragment in console._settings_fragments())

        self.assertIn("Statusline", text)
        self.assertIn("saved for this user", text)

    def test_console_compacts_header_and_footer_at_supported_widths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "a-project-name-that-is-long-enough-to-need-clipping"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            for width in (60, 80, 120, 160):
                with mock.patch(
                    "loopforge.cli.tui.shutil.get_terminal_size",
                    return_value=os.terminal_size((width, 24)),
                ):
                    header = "".join(fragment for _, fragment in console._header_fragments())
                    footer = "".join(fragment for _, fragment in console._footer_fragments())
                self.assertLessEqual(len(header), width)
                self.assertLessEqual(len(footer), width)

    def test_console_renders_a_bounded_window_for_large_run_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            console.state.screen = "project"
            runs = [
                {"run_id": f"run-{index}", "task": f"Task {index}", "status": "ready"}
                for index in range(1_000)
            ]
            console._runs[project.resolve()] = runs
            with (
                mock.patch(
                    "loopforge.cli.tui.shutil.get_terminal_size",
                    return_value=os.terminal_size((80, 24)),
                ),
            ):
                fragments = console._project_fragments()

        rendered_runs = [fragment for _, fragment in fragments if "Task " in fragment]
        self.assertLessEqual(len(rendered_runs), 16)

    def test_cached_snapshot_serves_rendering_and_selection_without_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            with mock.patch("loopforge.cli.tui.current_status", wraps=current_status) as status_read:
                console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
                console._load_revision(project)
                calls_after_refresh = status_read.call_count
                console._header_fragments()
                console._body_fragments()
                console._footer_fragments()
                console._move(1)

        self.assertEqual(status_read.call_count, calls_after_refresh)

    def test_ascii_mode_uses_ascii_markers_and_ellipsis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            console = LoopForgeConsole(InteractiveShell(project, output=io.StringIO()))
            with mock.patch.dict(os.environ, {"LOOPFORGE_ASCII": "1"}):
                self.assertEqual(console._marker("✓"), "+")
                self.assertEqual(_clip("a very long value", 8), "a ver...")

    def test_textual_backend_selector_is_opt_in_and_safe(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(selected_tui_backend(), "legacy")
        with mock.patch.dict(os.environ, {"LOOPFORGE_TUI_BACKEND": "textual"}):
            self.assertEqual(selected_tui_backend(), "textual")
        with mock.patch.dict(os.environ, {"LOOPFORGE_TUI_BACKEND": "unexpected"}):
            self.assertEqual(selected_tui_backend(), "legacy")


class _working_directory:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.previous: Path | None = None

    def __enter__(self) -> None:
        self.previous = Path.cwd()
        os.chdir(self.directory)

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.previous is not None
        os.chdir(self.previous)
