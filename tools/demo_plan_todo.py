"""Deterministic, read-only Textual visual test of native Plan / TODO in Workflow.

From the LoopForge repository root:
    PYTHONPATH=src .venv/bin/python tools/demo_plan_todo.py

Only synthetic in-memory events. No adapter invocation, filesystem writes, or network.
The sidebar contains five workflow stages and five nested agent TODOs.
Left/right folds/unfolds the plan while focused on the workflow list.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.presentation import StageView
from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.app import _snapshot_run_identity

if __package__:
    from .demo_tool_call import demonstration_snapshot
else:
    from demo_tool_call import demonstration_snapshot


ITEMS = (
    {"text": "Inspect authentication flow", "status": "completed"},
    {"text": "Define validation rules", "status": "completed"},
    {"text": "Update token handling", "status": "completed"},
    {"text": "Run authentication tests", "status": "in_progress"},
    {"text": "Review failure paths", "status": "pending"},
)


def plan_snapshot(app, *, items=ITEMS, session_id="demo/implementation/session-01"):
    """Build a valid run snapshot without relying on real harness or workspace."""
    original = demonstration_snapshot(app, final=True)
    stages = (
        StageView("research", "Research", "agent", "done", "completed", "✓", "Research", "read_only"),
        StageView("planning", "Planning", "agent", "done", "completed", "✓", "Planning", "read_only"),
        StageView("implementation", "Implementation", "agent", "active", "running", "›", "Implementation", "write"),
        StageView("verification", "Verification", "agent", "pending", "pending", "○", "Verification", "read_only"),
        StageView("review", "Review", "agent", "pending", "pending", "○", "Review", "read_only"),
    )
    run = replace(original.run.shell.run, id="agent-plan-demo", short_id="agent-plan-demo",
                  task="Visual test — Agent TODO in Workflow", current_stage="implementation")
    project = replace(original.run.shell.project, name="Agent Plan Demo")
    shell = replace(original.run.shell, project=project, run=run, stages=stages)
    events = (
        {"kind": "message", "title": "Agent", "body": "Updating authentication validation.",
         "native_id": "message-1", "order": 0},
        {"kind": "plan", "title": "Plan", "native_id": "plan-1", "plan_items": list(items),
         "order": 1},
        {"kind": "tool", "title": "Shell", "call_id": "auth-tests",
         "body": "$ pytest tests/test_auth.py", "status": "running",
         "order": 2},
    )
    agent = replace(original.run.agent, stage_id="implementation",
                    session_id=session_id, session_dir=session_id,
                    structured_events=events, event_count=len(events))
    sessions = ({"stage_id": "implementation", "session_id": session_id,
                 "label": "Session 01"},)
    return replace(original, selected_run_id=run.id,
                   project=replace(original.project, shell=shell),
                   run=replace(original.run, shell=shell, agent=agent, sessions=sessions))


class AgentPlanDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                         load_on_mount=False)

    def on_mount(self):
        super().on_mount()
        self._screen = "run"
        snapshot = plan_snapshot(self)
        self._operation_run_identity = _snapshot_run_identity(snapshot)
        self._snapshot = snapshot  # Preserve this fixture for F6 supervision.
        self._render_snapshot(snapshot)

    def _suspend_run_follow(self):
        # This test fixture must not write real run-reading state.
        self._run_follow_tail = False


if __name__ == "__main__":
    AgentPlanDemo().run()
