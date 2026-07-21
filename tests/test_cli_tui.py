"""Contracts for the Textual full-screen LoopForge interface."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from loopforge.engine import run_streaming_process
from loopforge.cli.interactive import InteractiveShell, run_interactive
from loopforge.cli.operations import ForegroundOperation
from loopforge.cli.tui import run_fullscreen_console


class CliTuiTests(unittest.TestCase):
    def test_headless_shell_does_not_construct_fullscreen_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_textual_app = sys.modules.pop("loopforge.cli.textual_app", None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_interactive(Path(temp_dir), command="/status"), 0)
        self.assertNotIn("loopforge.cli.textual_app", sys.modules)
        if previous_textual_app is not None:
            sys.modules["loopforge.cli.textual_app"] = previous_textual_app

    def test_fullscreen_console_starts_the_textual_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shell = InteractiveShell(Path(temp_dir), output=io.StringIO())
            with mock.patch("loopforge.cli.textual_app.LoopForgeApp") as app_type:
                self.assertEqual(run_fullscreen_console(shell), 0)
        app_type.assert_called_once_with(shell)
        app_type.return_value.run.assert_called_once_with()

    def test_fullscreen_console_is_the_interactive_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shell = InteractiveShell(Path(temp_dir), output=io.StringIO())
            with (
                mock.patch("loopforge.cli.tui.run_fullscreen_console", return_value=0) as console,
                mock.patch("prompt_toolkit.PromptSession") as session_type,
            ):
                self.assertEqual(shell.run_prompt(), 0)
                console.assert_called_once_with(shell)

                shell.renderer_mode = "plain"
                session_type.return_value.prompt.side_effect = EOFError
                self.assertEqual(shell.run_prompt(), 0)
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

    def test_tui_operation_streams_adapter_output_only_as_events(self) -> None:
        operation = ForegroundOperation("Implementation")

        def runner(emit, cancel_event):  # type: ignore[no-untyped-def]
            result = run_streaming_process(
                [sys.executable, "-c", "import sys; print('adapter stdout'); print('adapter stderr', file=sys.stderr)"],
                Path.cwd(),
                10,
                output_callback=emit,
                cancel_event=cancel_event,
            )
            return type("Result", (), {"ok": result["returncode"] == 0, "message": "Adapter finished."})()

        terminal_stdout = io.StringIO()
        terminal_stderr = io.StringIO()
        with contextlib.redirect_stdout(terminal_stdout), contextlib.redirect_stderr(terminal_stderr):
            operation.start(runner)
            operation._thread.join(timeout=5)  # type: ignore[attr-defined]

        self.assertTrue(operation.finished)
        self.assertEqual(terminal_stdout.getvalue(), "")
        self.assertEqual(terminal_stderr.getvalue(), "")
        events = operation.collect_events()
        adapter_messages = [event.message for event in events if event.kind == "adapter_output"]
        self.assertTrue(any("adapter stdout" in message for message in adapter_messages))
        self.assertTrue(any("adapter stderr" in message for message in adapter_messages))


if __name__ == "__main__":
    unittest.main()
