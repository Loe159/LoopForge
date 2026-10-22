"""Real Textual pilots for the approved global Settings frame."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from textual.containers import VerticalScroll
from textual.widgets import OptionList, Select

from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.screens import TextEntryScreen
from loopforge.cli.textual_app.settings import SETTINGS_SECTIONS, SettingsDashboard


class SettingsNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.environment = mock.patch.dict(os.environ, {
            "LOOPFORGE_HOME": str(Path(self.temp.name) / "home"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def make_app(self) -> LoopForgeApp:
        app = LoopForgeApp(
            SimpleNamespace(project_dir=self.project, theme="dark"), load_on_mount=False,
        )
        app._adapter_diagnostic_cache = {
            key: "availability not checked in test" for key in (
                "codex", "claude-code", "kilo-code", "aider", "opencode",
                "mini-swe-agent", "local-adapter-fixture",
            )
        }
        return app

    async def test_global_entry_needs_no_project_or_run_and_has_no_write_side_effect(self) -> None:
        app = self.make_app()
        before = tuple(Path(self.temp.name).rglob("*"))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s")
            self.assertEqual(app._screen, "settings")
            self.assertEqual(str(app.query_one("#settings-scope").render()), "Global")
            menu = app.query_one("#settings-navigation", OptionList)
            self.assertTrue(menu.has_focus)
            for key, title, _ in SETTINGS_SECTIONS:
                self.assertEqual(app.query_one(SettingsDashboard).section_id, key)
                self.assertEqual(str(app.query_one("#settings-section-title").render()), title)
                await pilot.press("down")
            await pilot.press("escape")
            self.assertEqual(app._screen, "home")
        self.assertEqual(before, tuple(Path(self.temp.name).rglob("*")))

    async def test_enter_right_tab_and_escape_have_separate_focus_ownership(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s", "down", "down", "enter")
            frame = app.query_one(SettingsDashboard)
            self.assertEqual(frame.section_id, "workflow")
            content = app.query_one("#settings-content", VerticalScroll)
            self.assertTrue(content.has_focus)
            await pilot.press("down")
            self.assertEqual(frame.section_id, "workflow")
            await pilot.press("escape")
            self.assertTrue(app.query_one("#settings-navigation").has_focus)
            await pilot.press("right")
            self.assertTrue(content.has_focus)
            await pilot.press("escape", "tab")
            self.assertTrue(content.has_focus)
            await pilot.press("shift+tab")
            self.assertTrue(app.query_one("#settings-navigation").has_focus)
            await pilot.press("escape")
            self.assertEqual(app._screen, "home")

    async def test_mouse_selects_category_and_back_restores_opener(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s")
            await pilot.click("#settings-navigation", offset=(5, 3))
            self.assertEqual(app.query_one(SettingsDashboard).section_id, "autonomy")
            self.assertTrue(app.query_one("#settings-content").has_focus)
            await pilot.click("#settings-back")
            self.assertEqual(app._screen, "home")

    async def test_compact_native_menu_escape_closes_menu_before_settings(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.press("s")
            picker = app.query_one("#settings-section-select", Select)
            self.assertTrue(picker.has_focus)
            await pilot.press("enter")
            self.assertTrue(picker.expanded)
            await pilot.press("escape")
            self.assertFalse(picker.expanded)
            self.assertEqual(app._screen, "settings")
            await pilot.press("enter", "down", "enter", "tab")
            self.assertEqual(app.query_one(SettingsDashboard).section_id, "harnesses")
            self.assertTrue(app.query_one("#settings-content").has_focus)
            await pilot.press("escape")
            self.assertTrue(picker.has_focus)
            await pilot.press("escape")
            self.assertEqual(app._screen, "home")

    async def test_resize_preserves_category_focus_and_keeps_content_and_back_visible(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s", "down", "down", "down")
            frame = app.query_one(SettingsDashboard)
            for width in (48, 52, 60, 80, 99, 100, 120, 160, 60, 120):
                with self.subTest(width=width):
                    await pilot.resize_terminal(width, 24)
                    await pilot.pause()
                    self.assertEqual(frame.section_id, "autonomy")
                    nav_id = "settings-section-select" if width < 100 else "settings-navigation"
                    self.assertTrue(app.query_one(f"#{nav_id}").has_focus)
                    for name in ("settings-content", "settings-back", "settings-hotkeys"):
                        region = app.query_one(f"#{name}").region
                        self.assertGreater(region.width, 0)
                        self.assertGreater(region.height, 0)
                        self.assertGreaterEqual(region.x, 0)
                        self.assertLessEqual(region.right, width)
                        self.assertLessEqual(region.bottom, 24)
                    content = app.query_one("#settings-content")
                    self.assertGreaterEqual(content.size.height, 10)
                    self.assertLessEqual(content.region.bottom, app.query_one("#settings-hotkeys").region.y)
            await pilot.press("right")
            content = app.query_one("#settings-content")
            await pilot.resize_terminal(48, 24)
            await pilot.pause()
            self.assertTrue(content.has_focus)
            self.assertEqual(frame.section_id, "autonomy")

    async def test_snapshot_refresh_does_not_reset_selection_focus_or_scroll(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.press("s", "down", "down", "down", "enter", "end")
            content = app.query_one("#settings-content", VerticalScroll)
            await pilot.pause()
            self.assertGreater(content.scroll_y, 0)
            previous = content.scroll_y
            app._render_snapshot(replace(app.snapshot, revision=app.snapshot.revision + 1))
            await pilot.pause()
            self.assertTrue(content.has_focus)
            self.assertEqual(content.scroll_y, previous)
            self.assertEqual(app.query_one(SettingsDashboard).section_id, "autonomy")

    async def test_each_opener_and_its_context_are_restored(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            for opener in ("home", "project", "run", "evidence"):
                with self.subTest(opener=opener):
                    app._screen = opener
                    app._filter = "kept filter"
                    app._evidence_preview = "kept evidence"
                    app._render_snapshot(app.snapshot)
                    previous_focus = app.focused
                    previous_follow = app._run_follow_tail
                    app.action_show_settings()
                    await pilot.pause()
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(app._screen, opener)
                    self.assertEqual(app._filter, "kept filter")
                    self.assertEqual(app._evidence_preview, "kept evidence")
                    self.assertEqual(app._run_follow_tail, previous_follow)
                    self.assertIs(app.focused, previous_focus)

    async def test_reopening_retains_category_and_background_controls_do_not_run(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s", "down", "down", "escape", "s")
            self.assertEqual(app.query_one(SettingsDashboard).section_id, "workflow")
            with mock.patch.object(app, "action_new_run") as new_run, mock.patch.object(
                app, "show_adapter_selector",
            ) as picker:
                await pilot.press("n", "e", "a", "enter")
                new_run.assert_not_called()
                picker.assert_not_called()
            self.assertEqual(app._screen, "settings")

    async def test_home_project_cursor_and_command_input_focus_survive_round_trip(self) -> None:
        app = self.make_app()
        snapshot = replace(app.snapshot, home=replace(app.snapshot.home, projects=(
            {"name": "Project A", "path": str(self.project), "run_count": 0},
            {"name": "Project B", "path": str(self.project / "second"), "run_count": 0},
        )))
        app._snapshot = snapshot
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("down", "down", "s", "escape")
            self.assertEqual(app._home_project_list().highlighted, 2)
            await pilot.press("slash")
            command = app.query_one("#home-command-input")
            command.value = "/status"
            self.assertIs(app.focused, command)
            app.action_show_settings()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertIs(app.focused, command)
            self.assertEqual(command.value, "/status")

    async def test_child_dialog_consumes_escape_and_snapshot_refresh_is_safe(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("s")
            app.push_screen(TextEntryScreen("Test", "Input"))
            await pilot.pause()
            app._render_snapshot(replace(app.snapshot, revision=2))
            await pilot.press("escape")
            self.assertEqual(app._screen, "settings")
            self.assertEqual(len(app.screen_stack), 1)

    async def test_ascii_hint_and_literal_values_remain_readable(self) -> None:
        app = self.make_app()
        app.shell.theme = "[red]literal[/red]"
        with mock.patch.dict(os.environ, {"LOOPFORGE_ASCII": "1"}):
            async with app.run_test(size=(48, 24)) as pilot:
                await pilot.press("s", "tab")
                hint = str(app.query_one("#settings-hotkeys").render())
                self.assertNotIn("↑", hint)
                self.assertEqual(str(app.query_one("#settings-section-select .down-arrow").render()), "v")
                self.assertIn("[red]literal[/red]", str(app.query_one("#settings-values").render()))


if __name__ == "__main__":
    unittest.main()
