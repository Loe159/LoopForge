"""Pilot coverage for the phase-7 Textual foundation."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


@unittest.skipUnless(
    importlib.util.find_spec("textual") is not None,
    "Textual is an installed runtime dependency",
)
class TextualFoundationTests(unittest.IsolatedAsyncioTestCase):
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
            self.assertEqual(app._screen, "evidence")
            app.request_action(action)
            await pilot.pause(0.1)
            await pilot.press("escape")
            self.assertIsNone(app._operation)
