"""Agent TODO contract and sidebar regression tests."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

from loopforge.adapters.event_store import normalize_event
from loopforge.cli.agent_plan import project_agent_plan


class AgentPlanContractTests(unittest.TestCase):
    def test_codex_todo_structured_and_bounded(self):
        source = {"type": "item.completed", "item": {"type": "todo_list", "id": "p1", "items": [
            {"text": "Inspect flow", "completed": True},
            {"text": "Run tests", "completed": False},
            {"text": "Pending unknown"},
            {"text": "\x1b[31mUnsafe\x1b[0m", "status": "in_progress"},
        ]}}
        event, = normalize_event(source)
        plan = project_agent_plan((event,))
        self.assertEqual(plan.count, 4)
        self.assertEqual(plan.completed, 1)
        self.assertEqual([item.status for item in plan.items],
                         ["completed", "pending", "unknown", "in_progress"])
        self.assertNotIn("\x1b", "".join(item.text for item in plan.items))

    def test_plan_uses_latest_structured_snapshot_not_free_text(self):
        self.assertFalse(project_agent_plan(({"kind": "message", "body": "[x] task"},)).items)
        first, = normalize_event({"type": "item.completed", "item": {"type": "todo_list", "id": "plan", "items": [{"text": "A", "completed": False}]}})
        second, = normalize_event({"type": "item.completed", "item": {"type": "todo_list", "id": "plan", "items": [{"text": "A", "completed": True}]}})
        plan = project_agent_plan((first, second))
        self.assertEqual(plan.completed, 1)
        self.assertEqual(plan.count, 1)


class AgentPlanTuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_todos_do_not_create_selectable_stages(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import RunWorkflowList
        from loopforge.cli.agent_plan import AgentPlan, AgentTodo
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme="dark"), load_on_mount=False)
        async with app.run_test(size=(160, 36)) as pilot:
            from tests.test_run_live_tui import synthetic_run
            snapshot = synthetic_run(app)
            app._screen = "run"
            app._render_snapshot(snapshot)
            await pilot.pause()
            sidebar = app.query_one("#run-context")
            plan = AgentPlan((AgentTodo("Inspect flow", "completed"),
                              AgentTodo("Run tests", "in_progress")))
            content = dict(sidebar._last_content, agent_plan=plan,
                           plan_stage="research", plan_scope="r1/research/s1")
            sidebar.update_content(**content)
            workflow = app.query_one(RunWorkflowList)
            self.assertEqual(len(workflow.options), 1)
            self.assertIn("Inspect flow", workflow.options[0].prompt.plain)
            self.assertIn("1/2", workflow.options[0].prompt.plain)
            workflow.focus()
            await pilot.press("left")
            await pilot.pause()
            self.assertNotIn("Inspect flow", workflow.options[0].prompt.plain)
            await pilot.press("right")
            await pilot.pause()
            self.assertIn("Inspect flow", workflow.options[0].prompt.plain)
