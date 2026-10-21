"""Visual/pilot acceptance for agent TODO lines nested in LoopForge Workflow."""
from __future__ import annotations

from dataclasses import replace
import unittest

from textual.widgets import OptionList

from loopforge.cli.textual_app.screens import RunSupervisionScreen
from loopforge.cli.textual_app.widgets import RunWorkflowList
from tools.demo_plan_todo import AgentPlanDemo, ITEMS, plan_snapshot


class AgentPlanVisualTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_widths_show_native_todos_without_duplicate_live_plan(self):
        for width in (48, 52, 60, 80, 100, 120, 160):
            with self.subTest(columns=width):
                app = AgentPlanDemo()
                async with app.run_test(size=(width, 30)) as pilot:
                    await pilot.pause()
                    # The plan only belongs to the Workflow, not to Live.
                    live_kinds = [item.kind for item in app.query_one(
                        "#run-agent-output")._entries]
                    self.assertNotIn("plan", live_kinds)
                    self.assertTrue(app.query_one("#run-command-bar").display)
                    if not app.query_one("#run-context").display:
                        await pilot.press("f6")
                        await pilot.pause()
                        self.assertIsInstance(app.screen, RunSupervisionScreen)
                    sidebar = app.screen.query_one("#run-view-tabs")
                    steps = app.screen.query_one(RunWorkflowList)
                    self.assertEqual([o.id for o in steps.options],
                                     ["research", "planning", "implementation",
                                      "verification", "review"])
                    self.assertEqual(steps.virtual_size.height, 10)
                    self.assertEqual(steps.highlighted, 2)
                    plan = steps.options[2].prompt.plain
                    self.assertIn("Implementation", plan)
                    self.assertIn("3/5", plan)
                    for todo in ITEMS:
                        self.assertIn(todo["text"], plan)
                    self.assertTrue(sidebar.display)
                    self.assertGreaterEqual(sidebar.region.height, 6)
                    for view in ("live", "context", "changes", "evidences"):
                        button = app.screen.query_one("#run-view-" + view)
                        self.assertLessEqual(button.region.y + button.region.height,
                                             sidebar.region.y + sidebar.region.height)
                    if isinstance(app.screen, RunSupervisionScreen):
                        await pilot.press("escape")
                        await pilot.pause()

    async def test_keyboard_fold_focus_stream_updates_and_unknown_states(self):
        app = AgentPlanDemo()
        async with app.run_test(size=(160, 36)) as pilot:
            await pilot.pause()
            workflow = app.query_one(RunWorkflowList)
            workflow.focus()
            self.assertEqual(workflow.highlighted, 2)
            await pilot.press("left")
            await pilot.pause()
            self.assertNotIn("Inspect", workflow.options[2].prompt.plain)
            self.assertIn("3/5", workflow.options[2].prompt.plain)
            await pilot.press("right")
            await pilot.pause()
            self.assertIn("Inspect authentication flow", workflow.options[2].prompt.plain)

            # Other stage is navigable, and its left/right keys do not change plan.
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(workflow.options[workflow.highlighted].id, "planning")
            await pilot.press("left")
            await pilot.pause()
            self.assertIn("Inspect authentication flow", workflow.options[2].prompt.plain)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(workflow.options[workflow.highlighted].id, "implementation")

            # Streaming updates the same native plan without resetting keyboard focus.
            updated = (*({**item, "status": "completed"} for item in ITEMS),)
            snap = plan_snapshot(app, items=updated)
            app._snapshot = snap
            app._render_snapshot(snap)
            await pilot.pause()
            self.assertEqual(workflow.highlighted, 2)
            self.assertEqual(app.focused, workflow)
            self.assertIn("5/5", workflow.options[2].prompt.plain)

            # An unknown item is shown as unknown; the ratio is not invented.
            unknown = (*ITEMS[:4], {"text": "Unconfirmed activity", "status": "unknown"})
            snap = plan_snapshot(app, items=unknown)
            app._snapshot = snap
            app._render_snapshot(snap)
            await pilot.pause()
            self.assertIn("Unconfirmed activity", workflow.options[2].prompt.plain)
            self.assertNotIn("3/5", workflow.options[2].prompt.plain)

            # Session switch with no retained plan clears all previous TODOs.
            snap = plan_snapshot(app, items=(), session_id="demo/implementation/session-02")
            app._snapshot = snap
            app._render_snapshot(snap)
            await pilot.pause()
            self.assertNotIn("Inspect authentication", workflow.options[2].prompt.plain)
            self.assertEqual(len(workflow.options), 5)

    async def test_click_on_agent_todo_cannot_navigate_a_workflow_stage(self):
        app = AgentPlanDemo()
        async with app.run_test(size=(160, 36)) as pilot:
            await pilot.pause()
            workflow = app.query_one(RunWorkflowList)
            self.assertTrue(workflow.expanded)
            original = app._snapshot.run.reading
            # Third line is the engine stage; lines below it are agent TODOs.
            await pilot.click("#run-context-steps", offset=(8, 3))
            await pilot.pause()
            self.assertEqual(workflow.highlighted, 2)
            self.assertEqual(app._snapshot.run.reading, original)
            self.assertTrue(workflow.expanded)

    async def test_mouse_toggle_uses_chevron_not_engine_navigation(self):
        app = AgentPlanDemo()
        async with app.run_test(size=(160, 36)) as pilot:
            await pilot.pause()
            workflow = app.query_one(RunWorkflowList)
            column = workflow.options[2].prompt.plain.split("\n")[0].index("▾")
            await pilot.click("#run-context-steps", offset=(column, 2))
            await pilot.pause()
            self.assertFalse(workflow.expanded)
            self.assertEqual(app._snapshot.run.reading.stage_id, "")
            self.assertEqual(len(workflow.options), 5)
            column = workflow.options[2].prompt.plain.split("\n")[0].index("▸")
            await pilot.click("#run-context-steps", offset=(column, 2))
            await pilot.pause()
            self.assertTrue(workflow.expanded)
            self.assertIn("Inspect authentication flow", workflow.options[2].prompt.plain)
            self.assertEqual(app._snapshot.run.reading.stage_id, "")

    async def test_short_screen_and_ascii_glyphs(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"LOOPFORGE_ASCII": "1"}):
            app = AgentPlanDemo()
            async with app.run_test(size=(120, 24)) as pilot:
                await pilot.pause()
                step = app.query_one(RunWorkflowList)
                plan = step.options[2].prompt.plain
                self.assertIn("+ Inspect authentication flow", plan)
                self.assertIn("* Run authentication tests", plan)
                self.assertIn("o Review failure paths", plan)
                self.assertTrue(app.query_one("#run-command-bar").display)
                menu = app.query_one("#run-view-tabs")
                self.assertEqual(menu.region.height, 6)
                self.assertGreater(menu.region.y, 0)


if __name__ == "__main__":
    unittest.main()
