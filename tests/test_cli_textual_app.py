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
        self.assertEqual(app._home_focus, "runs")
        shell = app.snapshot.run.shell
        current_id = str(shell.run.id) if shell and shell.run else ""
        for _ in range(app._home_run_list().item_count):
            item = app._home_run_list().selected_item
            row = dict(item) if item is not None and hasattr(item, "items") else {}
            if not current_id or str(row.get("run_id") or "") == current_id:
                break
            await pilot.press("down")
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
                    await pilot.pause()
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
        from loopforge.cli.actions import ActionDescriptor
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.textual_app import LoopForgeApp
        from textual.widgets import Input

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell, load_on_mount=False)
            async with app.run_test() as pilot:
                await pilot.press("/")
                await pilot.pause()
                command_input = app.query_one("#home-command-input", Input)
                self.assertTrue(command_input.has_focus)
                self.assertEqual(command_input.value, "/")

                status_result = app._dispatch_slash_command("/status")
                self.assertEqual(status_result.exit_code, 0)
                self.assertIn("Current loop", status_result.message)
                self.assertEqual(shell.output.getvalue(), "")

                with mock.patch.object(
                    shell,
                    "cmd_continue",
                    return_value=SimpleNamespace(exit_code=0, should_exit=False),
                ) as continue_run:
                    result = app._dispatch_slash_command("/continue --confirm")

                self.assertEqual(result.exit_code, 0)
                self.assertEqual(
                    continue_run.call_args.kwargs["default_execution_mode"],
                    "auto",
                )

                action = ActionDescriptor(
                    "continue",
                    "Continue run",
                    "Start the next harness step.",
                    "low",
                    False,
                    True,
                    "/continue",
                    "continue",
                )
                with mock.patch.object(
                    shell,
                    "execute_guided_action",
                    return_value=SimpleNamespace(exit_code=0, should_exit=False),
                ) as execute_guided, mock.patch.object(
                    app,
                    "_run_shell_operation",
                    side_effect=lambda _label, runner: runner(None, mock.Mock()),
                ):
                    app._execute_action(action)

                self.assertEqual(
                    execute_guided.call_args.kwargs["implementation_mode"],
                    "auto",
                )

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
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

                    await pilot.pause()
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

    async def test_structured_error_includes_code_and_remediation(self) -> None:
        """S3.2: a failed operation surfaces structured error info, not just str(error)."""
        from loopforge.cli.operations import OperationController
        from loopforge.cli.state_store import _operation_snapshot

        operation = OperationController("Test op")

        def runner(emit, cancelled):
            raise FileNotFoundError("run.json not found")

        operation.start(runner)
        operation._thread.join(timeout=5)
        snapshot = _operation_snapshot(operation, operation.history)
        self.assertEqual(snapshot.state, "failed")
        self.assertEqual(snapshot.error_code, "FileNotFoundError")
        self.assertIsNotNone(snapshot.error_remediation)
        self.assertIn("missing", snapshot.error_remediation.lower())
        self.assertTrue(snapshot.error_recoverable)

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
        from loopforge.cli.textual_app.widgets import ScreenList
        from textual.widgets import Footer, Header

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
                    self.assertFalse(app.query_one(Header).display)
                    self.assertFalse(app.query_one(Footer).display)
                    self.assertEqual(str(app.query_one("#home-product-name").render()), "LoopForge")
                    project_list = app.query_one("#home-project-list", ScreenList)
                    run_list = app.query_one("#home-run-list", ScreenList)
                    self.assertEqual(dict(project_list.selected_item)["name"], "All projects")
                    self.assertGreaterEqual(run_list.item_count, 1)
                    labels = " ".join(
                        str(app.query_one(f"#home-metric-{field}-label").render())
                        for field in ("primary", "secondary", "tertiary", "quaternary")
                    )
                    for label in ("Projects", "Active runs", "Need attention", "Default adapter"):
                        self.assertIn(label, labels)
                    self.assertEqual(str(app.query_one("#home-hotkeys-left").render()), "")
                    await pilot.press("ctrl+n")
                    self.assertEqual(
                        len(app.screen_stack),
                        1,
                        "All projects must not expose or execute New Run.",
                    )

                    await pilot.press("down")
                    self.assertEqual(
                        dict(project_list.selected_item)["name"],
                        project.name,
                    )
                    self.assertIn("New Run", str(app.query_one("#home-hotkeys-left").render()))
                    await pilot.pause(LoopForgeApp.HOME_DETAILS_DELAY + 0.1)
                    self.assertEqual(
                        str(app.query_one("#home-metric-primary-label").render()),
                        "Project",
                    )
                    await pilot.press("enter")
                    self.assertEqual(app._home_focus, "runs")
                    await pilot.press("left")
                    self.assertEqual(app._home_focus, "projects")
                    self.assertEqual(dict(project_list.selected_item)["name"], project.name)
                    await pilot.press("left")
                    self.assertEqual(dict(project_list.selected_item)["name"], "All projects")
                    await pilot.press("right")
                    self.assertEqual(app._home_focus, "runs")

    async def test_home_lists_show_scrollbars_only_when_content_overflows(self) -> None:
        from loopforge.cli.models import HomeSnapshot
        from loopforge.cli.textual_app import LoopForgeApp

        projects = tuple(
            {
                "project_id": f"project-{index}",
                "name": f"project-{index}",
                "path": f"C:/work/project-{index}",
                "run_count": 1,
                "attention": "ready",
            }
            for index in range(40)
        )
        runs = tuple(
            {
                "run_id": f"run-{index}",
                "project": f"project-{index}",
                "project_path": f"C:/work/project-{index}",
                "task": f"Task {index}",
                "attention": "ready",
            }
            for index in range(40)
        )
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        app._snapshot = replace(
            app.snapshot,
            home=HomeSnapshot("ready", projects, (), runs),
        )

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self.assertTrue(app._home_project_list().show_vertical_scrollbar)
            self.assertTrue(app._home_run_list().show_vertical_scrollbar)

            app._snapshot = replace(
                app.snapshot,
                home=HomeSnapshot("ready", projects[:1], (), runs[:1]),
            )
            app._render_snapshot(app._snapshot)
            await pilot.pause()
            self.assertFalse(app._home_project_list().show_vertical_scrollbar)
            self.assertFalse(app._home_run_list().show_vertical_scrollbar)

    async def test_home_project_navigation_debounces_detail_rendering(self) -> None:
        from loopforge.cli.models import HomeSnapshot
        from loopforge.cli.textual_app import LoopForgeApp

        projects = tuple(
            {
                "project_id": f"project-{index}",
                "name": f"project-{index}",
                "path": f"C:/work/project-{index}",
                "run_count": 1,
                "attention": "ready",
                "default_adapter": "codex",
            }
            for index in range(40)
        )
        runs = tuple(
            {
                "run_id": f"run-{index}",
                "project_id": f"project-{index}",
                "project": f"project-{index}",
                "project_path": f"C:/work/project-{index}",
                "task": f"Task {index}",
                "attention": "ready",
            }
            for index in range(40)
        )
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        app._snapshot = replace(
            app.snapshot,
            home=HomeSnapshot("ready", projects, (), runs),
        )

        async with app.run_test(size=(80, 24)) as pilot:
            project_list = app._home_project_list()
            run_list = app._home_run_list()
            with (
                mock.patch.object(project_list, "populate", wraps=project_list.populate) as project_populate,
                mock.patch.object(run_list, "populate", wraps=run_list.populate) as run_populate,
            ):
                for _ in range(12):
                    app.action_move_down()

                self.assertEqual(dict(project_list.selected_item)["name"], "project-11")
                self.assertEqual(project_populate.call_count, 0)
                self.assertEqual(run_populate.call_count, 0)
                self.assertEqual(run_list.item_count, 40)

                await pilot.pause(LoopForgeApp.HOME_DETAILS_DELAY + 0.1)

                self.assertEqual(project_populate.call_count, 0)
                self.assertEqual(run_populate.call_count, 1)
                self.assertEqual(run_list.item_count, 1)
                self.assertEqual(dict(run_list.selected_item)["project"], "project-11")

                app.action_move_right()
                self.assertEqual(app._home_focus, "runs")
                self.assertEqual(
                    run_populate.call_count,
                    1,
                    "Focusing synchronized run details must not rebuild them.",
                )
                app.action_move_left()
                self.assertEqual(app._home_focus, "projects")

                app.action_move_down()
                app.action_open_selected()
                self.assertEqual(app._home_focus, "runs")
                self.assertEqual(run_populate.call_count, 2)
                self.assertEqual(dict(run_list.selected_item)["project"], "project-12")
                await pilot.pause(LoopForgeApp.HOME_DETAILS_DELAY + 0.1)
                self.assertEqual(
                    run_populate.call_count,
                    2,
                    "An immediate Enter refresh must cancel the pending debounce.",
                )

    async def test_home_command_input_ignores_plain_text_and_dispatches_slash_commands(self) -> None:
        from textual.widgets import Input

        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            command_input = app.query_one("#home-command-input", Input)
            self.assertEqual(command_input.placeholder, "› Type / for commands")
            await pilot.press("slash")
            self.assertIs(app.focused, command_input)
            command_input.value = "plain text"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(command_input.value, "plain text")

            with mock.patch.object(app, "_run_slash_command") as dispatch:
                command_input.value = "/status"
                self.assertIs(app.focused, command_input)
                await pilot.press("enter")
                await pilot.pause()
                dispatch.assert_called_once_with("/status")
                self.assertEqual(command_input.value, "")

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

    async def test_run_screen_renders_activity_context_and_required_action(self) -> None:
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
                self._seed_project_with_run(project, loopforge_home, "Characterization pipeline task")
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test(size=(80, 24)) as pilot:
                    action = await self.open_current_run_with_pilot(app, pilot)
                    self.assertTrue(app.query_one("#run-dashboard").display)
                    self.assertFalse(app.query_one("#main-content").display)

                    heading = str(app.query_one("#run-attempt-heading").render())
                    prompt = str(app.query_one("#run-system-prompt").render())
                    output = app.query_one("#run-agent-output").transcript.plain
                    contract = str(app.query_one("#run-implementation-contract").render())
                    self.assertIn("Validate task", heading)
                    self.assertIn("System prompt will appear", prompt)
                    self.assertIn("Agent messages", output)
                    self.assertEqual(contract, "")
                    self.assertFalse(app.query_one("#run-implementation-panel").display)

                    app._snapshot = replace(
                        app.snapshot,
                        run=replace(
                            app.snapshot.run,
                            agent=replace(
                                app.snapshot.run.agent,
                                implementation_contract='{\n  "status": "completed"\n}',
                            ),
                        ),
                    )
                    app._render_run_activity(app.snapshot)
                    self.assertTrue(app.query_one("#run-implementation-panel").display)
                    self.assertIn(
                        '"status": "completed"',
                        str(app.query_one("#run-implementation-contract").render()),
                    )

                    metrics = str(app.query_one("#run-context-metrics").render())
                    self.assertIn("Status", metrics)
                    self.assertIn("Progress", metrics)
                    self.assertIn("Uptime", metrics)
                    self.assertIn("Tokens", metrics)

                    steps = str(app.query_one("#run-context-steps").render())
                    self.assertIn("Validate task", steps)
                    self.assertIn("Research repository", steps)
                    self.assertIn("Plan implementation", steps)

                    action_dock = app.query_one("#run-required-action")
                    self.assertTrue(action_dock.display)
                    self.assertIn("REQUIRED ACTION", str(app.query_one("#run-action-title").render()))
                    self.assertIn(action.label, str(app.query_one("#run-action-controls").render()))
                    self.assertFalse(app.query_one("#run-command-bar").display)

                    await pilot.resize_terminal(60, 24)
                    await pilot.pause()
                    self.assertFalse(app.query_one("#run-context").display)
                    compact_tabs = app.query_one("#run-compact-tabs")
                    self.assertTrue(compact_tabs.display)
                    self.assertIn("Live", str(compact_tabs.render()))
                    self.assertIn("Changes unavailable", str(compact_tabs.render()))
                    self.assertIn("Evidences unavailable", str(compact_tabs.render()))

    async def test_run_screen_shows_project_adapter_and_run_identity(self) -> None:
        """The fixed run context keeps project, adapter, and run identity visible."""
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
                    brand = str(app.query_one("#run-header-brand").render())
                    header = str(app.query_one("#run-header-identity").render())
                    branch = str(app.query_one("#run-header-branch").render())
                    configuration = str(app.query_one("#run-context-configuration").render())
                    self.assertRegex(brand, r"LoopForge\nv\d")
                    self.assertIn(project.name, header)
                    self.assertIn("Run #1", header)
                    self.assertIn("Identity task", header)
                    self.assertIn("git:", branch)
                    self.assertIn(project.name, configuration)
                    self.assertIn("Adapter", configuration)
                    self.assertIn(shell.selected_adapter, configuration)

    async def test_run_activity_streams_harness_events_and_scrolls(self) -> None:
        from loopforge.cli.interactive import InteractiveShell
        from loopforge.cli.operations import OperationController
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
                self._seed_project_with_run(project, loopforge_home, "Live activity task")
                shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                app = LoopForgeApp(shell)
                async with app.run_test(size=(80, 24)) as pilot:
                    await self.open_current_run_with_pilot(app, pilot)
                    app._snapshot = replace(
                        app.snapshot,
                        run=replace(
                            app.snapshot.run,
                            attempts=(
                                {
                                    "number": 1,
                                    "status": "completed",
                                    "summary": "persisted-private-summary-marker",
                                },
                            ),
                        ),
                    )
                    app._render_run_activity(app.snapshot)
                    recorded = str(app.query_one("#run-attempt-heading").render())
                    self.assertIn("Attempt 01", recorded)
                    self.assertNotIn(
                        "persisted-private-summary-marker",
                        app.query_one("#run-agent-output").transcript.plain,
                    )

                    operation = OperationController("Implementation")
                    for index in range(39):
                        operation.emit(
                            {
                                "kind": "tool_started",
                                "message": f"observable harness update {index}",
                            }
                        )
                    operation.emit(
                        {
                            "kind": "adapter_output",
                            "message": (
                                "adapter stdout: Reasoning\n"
                                "  Inspect configuration state and current tests."
                            ),
                        }
                    )
                    operation.emit(
                        {
                            "kind": "adapter_output",
                            "message": (
                                "adapter stdout: Tool call (in_progress)\n"
                                "  $ python -m unittest"
                            ),
                        }
                    )
                    operation.emit(
                        {
                            "kind": "completed",
                            "message": "completion-secret-marker",
                        }
                    )
                    app._notice = "stale-private-notice-marker"
                    app.begin_operation(operation)
                    self.assertEqual(app._notice, "")
                    await wait_for_condition(
                        pilot,
                        lambda: "Inspect configuration state"
                        in app.query_one("#run-agent-output").transcript.plain,
                        "the live Activity event stream",
                    )
                    rendered = app.query_one("#run-agent-output").transcript.plain
                    self.assertNotIn("completion-secret-marker", rendered)
                    self.assertIn("Reasoning", rendered)
                    self.assertIn("Inspect configuration state and current tests.", rendered)
                    self.assertIn("Tool call (in_progress)", rendered)
                    self.assertIn("$ python -m unittest", rendered)
                    self.assertEqual(app._notice, "")

                    feed = app.query_one("#run-activity-feed")
                    await wait_for_condition(
                        pilot,
                        lambda: feed.scroll_y == feed.max_scroll_y,
                        "Activity to follow the newest harness event",
                    )
                    self.assertGreater(feed.max_scroll_y, 0)
                    self.assertEqual(feed.scroll_y, feed.max_scroll_y)
                    before = feed.scroll_y
                    await pilot.press("up")
                    await pilot.pause()
                    self.assertLess(feed.scroll_y, before)
                    off_tail = feed.scroll_y

                    operation.emit(
                        {
                            "kind": "adapter_output",
                            "message": (
                                "adapter stdout: Tool call (completed, exit 0)\n"
                                "  $ pytest --quiet\n"
                                "  Output\n"
                                "    12 passed"
                            ),
                        }
                    )
                    app._poll_operation()
                    await wait_for_condition(
                        pilot,
                        lambda: "12 passed"
                        in app.query_one("#run-agent-output").transcript.plain,
                        "an off-tail Activity update",
                    )
                    self.assertEqual(feed.scroll_y, off_tail)

                    for _ in range(80):
                        if app._run_follow_tail:
                            break
                        await pilot.press("down")
                    self.assertTrue(app._run_follow_tail)
                    operation.emit(
                        {
                            "kind": "adapter_output",
                            "message": "adapter stdout: Agent message\n  Final update",
                        }
                    )
                    app._poll_operation()
                    await wait_for_condition(
                        pilot,
                        lambda: "Final update"
                        in app.query_one("#run-agent-output").transcript.plain,
                        "the resumed tail update",
                    )
                    self.assertEqual(feed.scroll_y, feed.max_scroll_y)

                    # App-level Enter bindings must yield to the focused tool.
                    tool = app.query_one("RunToolEntry")
                    tool.query_one("CollapsibleTitle").focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertFalse(tool.collapsed)
                    self.assertFalse(app._run_follow_tail)
                    operation.emit({
                        "kind": "adapter_output",
                        "message": "adapter stdout: Tool call (completed, exit 0)\n  $ python -m unittest\n  All passed",
                    })
                    app._poll_operation()
                    await wait_for_condition(pilot, lambda: tool.entry.status == "completed",
                                             "the expanded tool to finish in place")
                    self.assertIs(tool, app.query_one("RunToolEntry"))
                    self.assertFalse(tool.collapsed)

                    app._snapshot = replace(
                        app.snapshot,
                        selected_project=project.parent / "another-project",
                    )
                    app._render_run_activity(app.snapshot)
                    self.assertNotIn(
                        "Inspect configuration state",
                        app.query_one("#run-agent-output").transcript.plain,
                    )

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
            for label in ("Theme:", "Adapter:", "Git:", "Snapshot:", "Adapter diagnostics"):
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
