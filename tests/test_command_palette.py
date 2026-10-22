"""Contract and Textual Pilot coverage for the compact Command Palette."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.actions import ActionDescriptor


@unittest.skipUnless(
    importlib.util.find_spec("textual") is not None,
    "Textual is an installed runtime dependency",
)
class CommandPaletteTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def action(action_id: str, *, available: bool = True) -> ActionDescriptor:
        return ActionDescriptor(
            id=action_id,
            label="Approve plan" if action_id == "approve-plan" else "Unavailable task",
            description="Review the plan before continuing",
            risk="review",
            requires_confirmation=True,
            available=available,
            command_fallback="/approve" if action_id == "approve-plan" else "/run",
            executor_key="approve-plan" if available else "command",
        )

    async def test_hides_unavailable_actions_and_groups_known_commands(self) -> None:
        from loopforge.cli.textual_app.command_palette import build_palette_entries

        rows = build_palette_entries(
            (self.action("approve-plan"), self.action("create-run", available=False)),
            {
                "actions": "List guided actions available for the current state.",
                "status": "Show current LoopForge loop state.",
                "diff": "Show current Git working tree status and diff summary.",
            },
            has_run=True,
        )
        self.assertEqual(rows[0].category, "NEXT ACTION")
        self.assertEqual(rows[0].action.id, "approve-plan")
        self.assertNotIn("Unavailable task", [row.label for row in rows])
        self.assertIn("COMMANDS", {row.category for row in rows})
        self.assertEqual(next(row.category for row in rows if row.command == "/diff"),
                         "INSPECTION")
        self.assertEqual(len(rows), len({row.command or row.action.id for row in rows}))

    async def test_search_uses_labels_commands_and_descriptions(self) -> None:
        from loopforge.cli.textual_app.command_palette import (
            PaletteEntry, command_match_score,
        )
        entry = PaletteEntry("INSPECTION", "Show diff",
                             "Inspect Git changes", command="/diff")
        for query in ("diff", "/diff", "git", "changes", "show"):
            with self.subTest(query=query):
                self.assertGreater(command_match_score(entry, query), 0)
        self.assertEqual(command_match_score(entry, "adapter"), 0)
        self.assertGreater(command_match_score(entry, "/diff"),
                           command_match_score(entry, "changes"))

    async def test_all_projects_never_offers_new_run(self) -> None:
        from loopforge.cli.textual_app.command_palette import build_palette_entries

        rows = build_palette_entries(
            (self.action("create-run"),),
            {"run": "Create a new run", "new": "Create a new run",
             "status": "Show status"},
            has_project=False,
        )
        self.assertNotIn("/run", [row.command for row in rows])
        self.assertNotIn("/new", [row.command for row in rows])
        self.assertNotIn("create-run", [row.action.id for row in rows if row.action])

    async def test_keyboard_search_empty_and_escape_across_terminal_sizes(self) -> None:
        from textual.widgets import Input

        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.command_palette import LoopForgeCommandPalette

        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            app = LoopForgeApp(SimpleNamespace(project_dir=project), load_on_mount=False)
            async with app.run_test(size=(80, 24)) as pilot:
                for width in (48, 52, 60, 80, 100, 120, 160):
                    await pilot.resize_terminal(width, 24)
                    await pilot.press("ctrl+k")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, LoopForgeCommandPalette)
                    palette = app.screen
                    self.assertIsInstance(palette.query_one("#lf-palette-search"), Input)
                    self.assertGreater(len(palette._matching), 0)
                    search = palette.query_one("#lf-palette-search", Input)
                    search.value = "nomatchingcommandxyzz"
                    await pilot.pause()
                    self.assertEqual(palette._matching, [])
                    await pilot.press("enter")
                    self.assertIs(app.screen, palette, "Empty searches must not dispatch")
                    search.value = "/status"
                    await pilot.pause()
                    self.assertGreater(len(palette._matching), 0)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertNotIsInstance(app.screen, LoopForgeCommandPalette)

    async def test_arrow_keys_change_selection_without_moving_search_focus(self) -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import Input, Static

        from loopforge.cli.textual_app.command_palette import (
            LoopForgeCommandPalette, PaletteEntry,
        )

        class Host(App[None]):
            def compose(self) -> ComposeResult:
                yield Static("Host")
            def on_mount(self) -> None:
                self.push_screen(LoopForgeCommandPalette((
                    PaletteEntry("COMMANDS", "Show status", "Current state", "/status"),
                    PaletteEntry("INSPECTION", "Show diff", "Git changes", "/diff"),
                )))

        app = Host()
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause()
            palette = app.screen
            self.assertIsInstance(palette, LoopForgeCommandPalette)
            search = palette.query_one("#lf-palette-search", Input)
            self.assertTrue(search.has_focus)
            previous = palette._current
            await pilot.press("down")
            await pilot.pause()
            self.assertNotEqual(previous, palette._current)
            self.assertTrue(search.has_focus)
            await pilot.press("up")
            self.assertEqual(previous, palette._current)
