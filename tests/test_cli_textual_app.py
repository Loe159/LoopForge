"""Pilot coverage for the phase-7 Textual foundation."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


async def wait_for_condition(pilot, predicate, description: str) -> None:  # type: ignore[no-untyped-def]
    """Advance Textual frames until a published state is observable."""

    for _ in range(80):
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"Timed out waiting for {description}.")


@unittest.skipUnless(
    importlib.util.find_spec("textual") is not None,
    "Textual is an installed runtime dependency",
)
class TextualFoundationTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_native_theme_tracks_the_shell_preference(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        shell = SimpleNamespace(project_dir=Path.cwd(), theme="light")
        app = LoopForgeApp(shell, load_on_mount=False)
        self.assertEqual(app.theme, "ansi-light")

        shell.theme = "dark"
        app._apply_shell_theme()
        self.assertEqual(app.theme, "ansi-dark")

    async def open_current_run_with_pilot(self, app, pilot):  # type: ignore[no-untyped-def]
        """Reach the selected run using only the public keyboard route."""

        await wait_for_condition(
            pilot,
            lambda: bool(app.snapshot.home.projects),
            "the StateStore home snapshot",
        )
        await pilot.press("enter")
        await wait_for_condition(pilot, lambda: app._screen == "project", "the Project screen")
        await wait_for_condition(
            pilot,
            lambda: bool(app.snapshot.project.runs),
            "the StateStore project runs snapshot",
        )
        await pilot.press("enter")
        await wait_for_condition(pilot, lambda: app._screen == "run", "the Run screen")
        await wait_for_condition(
            pilot,
            lambda: app.snapshot.run.shell is not None and bool(app.available_actions),
            "the StateStore run action snapshot",
        )
        return app.available_actions[0]

    async def test_pilot_navigation_and_responsive_breakpoints(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            app = LoopForgeApp(
                SimpleNamespace(project_dir=project),
                load_on_mount=False,
            )
            async with app.run_test(size=(80, 24)) as pilot:
                # Project navigation starts a worker; the published result is
                # applied only through the immutable StateStore snapshot.
                app.select_project(project)
                await pilot.pause(0.1)
                self.assertEqual(app.snapshot.selected_project, project.resolve())

                for width, css_class in ((60, "width-60"), (80, "width-80"), (120, "width-120"), (160, "width-160")):
                    await pilot.resize_terminal(width, 24)
                    await pilot.pause()
                    self.assertTrue(app.has_class(css_class))

    async def test_pilot_cancels_a_backend_neutral_operation(self) -> None:
        from loopforge.cli.operations import OperationController
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        operation = OperationController("Verify run")
        async with app.run_test() as pilot:
            app.begin_operation(operation)
            await pilot.press("ctrl+c")
            self.assertTrue(operation.cancel_event.is_set())
            self.assertTrue(app.is_running)

    async def test_pilot_shows_live_operation_details(self) -> None:
        from loopforge.cli.operations import OperationController
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        operation = OperationController("Review patch")
        source_run = "run-source-0123456789"
        app._snapshot = replace(app.snapshot, selected_run_id=source_run)
        for index in range(10):
            operation.emit(
                {
                    "kind": "adapter_output",
                    "message": f"[red]event {index}[/]\\nreview stderr: inspecting tests {index}",
                }
            )
        async with app.run_test(size=(60, 24)) as pilot:
            app.begin_operation(operation)
            await pilot.pause(0.25)
            status = str(app.query_one("#operation-status").render())
            log_widget = app.query_one("#operation-log")
            log = str(log_widget.render())
            self.assertIn("Review patch", status)
            self.assertIn(source_run[:16], status)
            self.assertIn("[red]event 9[/]", log)
            self.assertIn("review stderr: inspecting tests 9", log)
            self.assertNotIn("[red]event 0[/]", log)
            self.assertEqual(log_widget.scroll_y, log_widget.max_scroll_y)

            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            self.assertEqual(log_widget.scroll_y, log_widget.max_scroll_y)

            spinner_phase = app._operation_spinner_phase
            app._poll_operation()
            self.assertNotEqual(app._operation_spinner_phase, spinner_phase)

    async def test_pilot_freezes_completed_operation_elapsed_time(self) -> None:
        from loopforge.cli.operations import OperationController
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        operation = OperationController("Verify run", started_at=100.0)
        operation.result = SimpleNamespace(ok=True, message="Verification completed.")
        operation.finished = True
        async with app.run_test() as _pilot:
            with (
                mock.patch("loopforge.cli.operations.monotonic", return_value=105.0),
                mock.patch.object(app, "load_selected_project") as refresh,
            ):
                app.begin_operation(operation)
                app._poll_operation()
                app._snapshot = app.store.flush()
                elapsed = app.snapshot.operation.elapsed_seconds
                spinner_phase = app._operation_spinner_phase
                with mock.patch("loopforge.cli.operations.monotonic", return_value=120.0):
                    app._poll_operation()

            self.assertEqual(app.snapshot.operation.elapsed_seconds, elapsed)
            self.assertEqual(app._operation_spinner_phase, spinner_phase)
            refresh.assert_called_once_with()

    async def test_pilot_exits_the_textual_backend(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertTrue(app._exit, "Application should record _exit=True after Ctrl+C")

    async def test_pilot_navigates_vertical_screens_and_cancels_a_modal(self) -> None:
        from loopforge.cli.actions import ActionDescriptor
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        action = ActionDescriptor(
            "approve-plan",
            "Approve plan",
            "Recorded plan evidence will be approved.",
            "medium",
            True,
            True,
            "/approve-plan",
            "approve-plan",
        )
        async with app.run_test() as pilot:
            app.action_show_settings()
            self.assertEqual(app._screen, "settings")
            await pilot.press("escape")
            self.assertEqual(app._screen, "run")
            app.action_show_evidence()
            self.assertEqual(app._screen, "run")
            app.request_action(action)
            await pilot.pause(0.1)
            await pilot.press("escape")
            self.assertIsNone(app._operation)

    async def test_pilot_selects_kilo_code_adapter_from_settings_and_action(self) -> None:
        from loopforge.cli.actions import ActionDescriptor
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import AdapterSelectionScreen
        from loopforge.engine import current_status, initialize_project

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                initialize_project(project)
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test() as pilot:
                    app.action_show_settings()
                    await pilot.press("enter")
                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, AdapterSelectionScreen),
                        "the adapter picker from Settings",
                    )
                    await pilot.press("down", "down", "enter")
                    await wait_for_condition(
                        pilot,
                        lambda: not isinstance(app.screen, AdapterSelectionScreen),
                        "the adapter picker to close",
                    )
                    self.assertEqual(shell.selected_adapter, "kilo-code")
                    self.assertIn("kilo-code", str(app.query_one("#screen-body").render()))

                    action = ActionDescriptor(
                        "choose-adapter",
                        "Choose a supported adapter",
                        "Select the adapter used for future stages.",
                        "low",
                        False,
                        True,
                        "/adapter",
                        "adapter",
                    )
                    app.request_action(action)
                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, AdapterSelectionScreen),
                        "the adapter picker from a guided action",
                    )
                    await pilot.press("escape")

                self.assertEqual(current_status(project).config["default_adapter"], "kilo-code")
                restarted = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                self.assertEqual(restarted.selected_adapter, "kilo-code")

    async def test_pilot_opens_slash_command_entry_and_uses_shell_dispatch(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import TextEntryScreen

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell, load_on_mount=False)
            async with app.run_test() as pilot:
                await pilot.press("/")
                await pilot.pause()
                self.assertIsInstance(app.screen, TextEntryScreen)

                result = app._dispatch_slash_command("/status")
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Current loop", result.message)
                self.assertEqual(shell.output.getvalue(), "")

    async def test_pilot_slash_filters_runs_from_project(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import TextEntryScreen

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test() as pilot:
            app._screen = "project"
            await pilot.press("/")
            await pilot.pause()
            self.assertIsInstance(app.screen, TextEntryScreen)
            self.assertEqual(app.screen.title_text, "Filter")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._filter, "")

    async def test_pilot_slash_filters_evidence(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import TextEntryScreen

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test() as pilot:
            app._screen = "evidence"
            await pilot.press("/")
            await pilot.pause()
            self.assertIsInstance(app.screen, TextEntryScreen)
            self.assertEqual(app.screen.title_text, "Filter")

    async def test_pilot_evidence_shortcut_does_not_navigate_from_home(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.pause()
            self.assertEqual(app._screen, "home")
            self.assertEqual(app._notice, "Open a run to view its evidence.")
            app._screen = "run"
            await pilot.press("e")
            await pilot.pause()
            self.assertEqual(app._screen, "run")
            self.assertEqual(app._notice, "Open a run to view its evidence.")

    async def test_pilot_completes_existing_task_contract_from_current_guidance(self) -> None:
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import TextEntryScreen
        from loopforge.engine import current_guidance, current_status

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=LoopForge Tests", "-c", "user.email=loopforge@example.invalid", "commit", "-m", "initial"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(main(["run", "--task", "Complete this task contract"]), 0)
                finally:
                    os.chdir(previous_cwd)

                before = current_status(project)
                self.assertIsNotNone(before.run)
                assert before.run is not None
                run_id = before.run["run_id"]
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                published = []
                unsubscribe = app.store.subscribe(published.append)
                async with app.run_test() as pilot:
                    action = await self.open_current_run_with_pilot(app, pilot)
                    self.assertEqual(action.id, "complete-task")
                    self.assertEqual(
                        current_guidance(project).recommended_actions[0].id,
                        "complete-task",
                    )

                    await pilot.press("enter")
                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, TextEntryScreen),
                        "the task-contract modal",
                    )
                    self.assertNotEqual(app.screen.title_text, "Create run")
                    self.assertIn("Complete", app.screen.title_text)
                    await pilot.press(*"objectiveproofexists")
                    await pilot.press("enter")
                    await wait_for_condition(
                        pilot,
                        lambda: app._operation is not None and app._operation.finished,
                        "task-contract completion",
                    )
                    await wait_for_condition(
                        pilot,
                        lambda: bool(app.available_actions) and app.available_actions[0].id == "approve-task",
                        "the refreshed task-approval action",
                    )
                unsubscribe()

                terminal_action_ids = []
                for snapshot in published:
                    shell_snapshot = snapshot.run.shell
                    if (
                        snapshot.operation.finished
                        and shell_snapshot is not None
                        and shell_snapshot.run is not None
                        and shell_snapshot.run.next_action is not None
                    ):
                        terminal_action_ids.append(shell_snapshot.run.next_action.id)
                self.assertEqual(terminal_action_ids, ["approve-task"])

                status = current_status(project)
                self.assertIsNotNone(status.run)
                assert status.run is not None
                self.assertEqual(status.run["run_id"], run_id)
                self.assertEqual(status.run["task_validation"]["status"], "valid")
                self.assertEqual(
                    current_guidance(project).recommended_actions[0].id,
                    "approve-task",
                )

    async def test_pilot_approves_initial_task_after_confirmation(self) -> None:
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import ConfirmationScreen
        from loopforge.engine import current_guidance, current_status

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=LoopForge Tests", "-c", "user.email=loopforge@example.invalid", "commit", "-m", "initial"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(
                            main(["run", "--task", "Approve this task", "--success-check", "Proof exists"]),
                            0,
                        )
                finally:
                    os.chdir(previous_cwd)

                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test() as pilot:
                    action = await self.open_current_run_with_pilot(app, pilot)
                    self.assertEqual(action.id, "approve-task")
                    self.assertEqual(
                        current_guidance(project).recommended_actions[0].id,
                        "approve-task",
                    )
                    await pilot.press("enter")
                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, ConfirmationScreen),
                        "the task approval confirmation",
                    )
                    await pilot.press("enter")
                    await wait_for_condition(
                        pilot,
                        lambda: app._operation is not None and app._operation.finished,
                        "task approval completion",
                    )

                status = current_status(project)
                self.assertEqual(status.run["human_gates"]["initial_task_approval"]["status"], "approved")
                self.assertEqual(current_guidance(project).recommended_actions[0].id, "run-research")

    async def test_archive_targets_highlighted_run_not_current(self) -> None:
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.engine import current_status

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=LoopForge Tests", "-c", "user.email=loopforge@example.invalid", "commit", "-m", "initial"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(main(["run", "--task", "First run"]), 0)
                        self.assertEqual(main(["run", "--task", "Second run"]), 0)
                finally:
                    os.chdir(previous_cwd)

                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test() as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: len(app.snapshot.project.runs) >= 2, "project runs")
                    app._screen = "project"
                    self.assertGreaterEqual(len(app.snapshot.project.runs), 2)
                    status = current_status(project)
                    assert status.config is not None
                    current_id = status.config.get("current_run_id")
                    runs = app._filtered_runs()
                    non_current_index: int | None = None
                    for i, row in enumerate(runs):
                        value = dict(row) if hasattr(row, "items") else {}
                        if str(value.get("run_id") or "") != current_id:
                            non_current_index = i
                            break
                    self.assertIsNotNone(non_current_index, "Expected a non-current run in the list")
                    from loopforge.cli.textual_app.widgets import ScreenList
                    app.query_one("#screen-list", ScreenList).highlighted = non_current_index
                    highlighted_id = app._target_run_id()

                    await pilot.press("a")
                    from loopforge.cli.textual_app.screens import ConfirmationScreen

                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, ConfirmationScreen),
                        "archive confirmation",
                    )
                    self.assertEqual(app.screen.title_text, "Archive run")
                    self.assertIn(highlighted_id[:16], app.screen.lines[0])

    async def test_archive_on_run_screen_targets_opened_run_not_runs_zero(self) -> None:
        """AE6: on the run screen, archive targets the opened run, not runs[0]."""
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import ConfirmationScreen
        from loopforge.engine import current_status

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(main(["run", "--task", "First run"]), 0)
                        self.assertEqual(main(["run", "--task", "Second run"]), 0)
                finally:
                    os.chdir(previous_cwd)

                status = current_status(project)
                assert status.config is not None
                current_id = str(status.config.get("current_run_id") or "")
                self.assertTrue(current_id)

                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test(size=(80, 24)) as pilot:
                    # Navigate to the run screen (opens the current/second run).
                    await self.open_current_run_with_pilot(app, pilot)
                    self.assertEqual(app._screen, "run")
                    # Wait for the snapshot to bind the opened run's identity.
                    await wait_for_condition(
                        pilot,
                        lambda: app._snapshot.selected_run_id is not None,
                        "selected_run_id in the run snapshot",
                    )
                    opened_id = app._target_run_id()
                    self.assertEqual(opened_id, current_id)

                    await pilot.press("a")
                    await wait_for_condition(
                        pilot,
                        lambda: isinstance(app.screen, ConfirmationScreen),
                        "archive confirmation on run screen",
                    )
                    self.assertEqual(app.screen.title_text, "Archive run")
                    self.assertIn(current_id[:16], app.screen.lines[0])

    async def test_cancellation_before_commit_no_effect(self) -> None:
        from loopforge.cli.operations import OperationController
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        operation = OperationController("Cancel-me operation")
        async with app.run_test() as _pilot:
            app.begin_operation(operation)
            self.assertFalse(operation.commit_started)
            self.assertTrue(operation.is_cancellable)
            operation.cancel()
            self.assertTrue(operation.cancelled)
            self.assertTrue(operation.cancel_event.is_set())

    async def test_cancellation_after_commit_reports_real_result(self) -> None:
        from loopforge.cli.operations import OperationController
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.app import _operation_result

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        operation = OperationController("Post-commit cancel")
        async with app.run_test() as _pilot:
            app.begin_operation(operation)
            operation.commit_started = True
            self.assertFalse(operation.is_cancellable)
            operation.cancel()
            self.assertFalse(operation.cancelled)
            result = _operation_result(operation, SimpleNamespace(exit_code=0, message="Committed successfully."), operation.cancel_event.is_set())
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "Committed successfully.")

    # ── S0.1 characterization net: lock screen-body content before S1.1 widgets ──

    @staticmethod
    def _seed_project_with_run(project: Path, loopforge_home: Path, task: str = "Characterization task") -> None:
        """Seed init + run so the TUI has a home/project/run snapshot to render."""
        from loopforge.cli import main

        previous_cwd = Path.cwd()
        os.chdir(project)
        try:
            with redirect_stdout(io.StringIO()):
                assert main(["init"]) == 0
                assert main(["run", "--task", task, "--success-check", "Proof exists"]) == 0
        finally:
            os.chdir(previous_cwd)

    @staticmethod
    def _body_text(app) -> str:
        return str(app.query_one("#screen-body").render())

    @staticmethod
    def _paint(app, screen: str) -> None:
        """Force a render of *screen* without async navigation."""
        app._screen = screen
        app._render_snapshot(app.snapshot)

    async def test_home_screen_body_renders_projects_and_recent_runs(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                self._seed_project_with_run(project, loopforge_home)
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test(size=(80, 24)) as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: bool(app.snapshot.home.projects), "home projects")
                    self._paint(app, "home")
                    self.assertEqual(str(app.query_one("#screen-title").render()), "LoopForge")
                    body = self._body_text(app)
                    self.assertIn("Projects", body)
                    after = str(app.query_one("#screen-after").render())
                    self.assertIn("Recent runs", after)

    async def test_project_screen_body_renders_runs_count(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                self._seed_project_with_run(project, loopforge_home)
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test(size=(80, 24)) as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: bool(app.snapshot.project.runs), "project runs")
                    self._paint(app, "project")
                    body = self._body_text(app)
                    self.assertIn("runs", body)
                    self.assertIn("Runs", body)

    async def test_run_screen_body_renders_pipeline_and_next_action(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                self._seed_project_with_run(project, loopforge_home, "Characterization pipeline task")
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test(size=(80, 24)) as pilot:
                    await self.open_current_run_with_pilot(app, pilot)
                    body = self._body_text(app)
                    self.assertIn("Pipeline", body)
                    self.assertIn("Next action", body)

    async def test_run_screen_shows_project_adapter_and_revision_identity(self) -> None:
        """S1.4: the run screen displays project name, adapter, and revision."""
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                self._seed_project_with_run(project, loopforge_home, "Identity task")
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test(size=(80, 24)) as pilot:
                    await self.open_current_run_with_pilot(app, pilot)
                    body = self._body_text(app)
                    self.assertIn("adapter:", body)
                    self.assertIn("revision", body)
                    state = str(app.query_one("#screen-state").render())
                    self.assertIn("project", state.lower())
                    self.assertIn("revision", state.lower())

    async def test_evidence_screen_body_renders_empty_state(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                self._seed_project_with_run(project, loopforge_home)
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test(size=(80, 24)) as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: bool(app.snapshot.project.runs), "project runs")
                    self._paint(app, "evidence")
                    body = self._body_text(app)
                    self.assertIn("No evidence available.", body)

    async def test_settings_screen_body_renders_values_and_diagnostics(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self._paint(app, "settings")
            self.assertEqual(str(app.query_one("#screen-title").render()), "Settings and diagnostics")
            body = self._body_text(app)
            for label in ("Theme:", "Statusline:", "Keymap:", "Adapter:", "Git:", "Snapshot:", "Adapter diagnostics"):
                self.assertIn(label, body)

    async def test_open_selected_resets_selected_index_to_zero(self) -> None:
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import ScreenList

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                # Seed two runs so action_move_down actually advances past index 0.
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(main(["run", "--task", "First run"]), 0)
                        self.assertEqual(main(["run", "--task", "Second run"]), 0)
                finally:
                    os.chdir(previous_cwd)

                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test(size=(80, 24)) as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: len(app.snapshot.project.runs) >= 2, "two project runs")
                    app._screen = "project"
                    screen_list = app.query_one("#screen-list", ScreenList)
                    self.assertGreaterEqual(screen_list.item_count, 2)
                    app.action_move_down()
                    self.assertGreater(screen_list.highlighted, 0)
                    app.action_open_selected()
                    self.assertEqual(screen_list.highlighted, 0)

    async def test_pilot_selects_third_line_and_verifies_item(self) -> None:
        from loopforge.cli import main
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import ScreenList

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "init"],
                cwd=project, check=True, capture_output=True, text=True,
            )
            loopforge_home = Path(temp_dir) / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                previous_cwd = Path.cwd()
                os.chdir(project)
                try:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["init"]), 0)
                        self.assertEqual(main(["run", "--task", "Alpha run"]), 0)
                        self.assertEqual(main(["run", "--task", "Beta run"]), 0)
                        self.assertEqual(main(["run", "--task", "Gamma run"]), 0)
                finally:
                    os.chdir(previous_cwd)

                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell, load_on_mount=False)
                async with app.run_test(size=(80, 24)) as pilot:
                    app.select_project(project)
                    await wait_for_condition(pilot, lambda: len(app.snapshot.project.runs) >= 3, "three project runs")
                    self._paint(app, "project")
                    screen_list = app.query_one("#screen-list", ScreenList)
                    self.assertGreaterEqual(screen_list.item_count, 3)
                    screen_list.highlighted = 2
                    item = screen_list.selected_item
                    self.assertIsNotNone(item)
                    runs = app._filtered_runs()
                    value = dict(item) if hasattr(item, "items") else {}
                    expected = dict(runs[2]) if hasattr(runs[2], "items") else {}
                    self.assertEqual(str(value.get("run_id")), str(expected.get("run_id")))
                    self.assertTrue(str(value.get("task") or ""))
