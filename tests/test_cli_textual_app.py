"""Pilot coverage for the phase-7 Textual foundation."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
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

    async def test_pilot_exits_the_textual_backend(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd()), load_on_mount=False)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            self.assertFalse(app.is_running)

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
