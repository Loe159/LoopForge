"""Synthetic, read-only preview of Run / Live Sub-agent / Delegation variant A.

From the repository root:
    PYTHONPATH=src .venv/bin/python tools/demo_sub_agent.py

No real harnesses, network calls, workspace writes, or workflow mutations.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.app import _snapshot_run_identity

if __package__:
    from .demo_tool_call import demonstration_snapshot
else:
    from demo_tool_call import demonstration_snapshot


class SubAgentDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(
            SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
            load_on_mount=False,
        )

    def _suspend_run_follow(self):
        # Synthetic readings must not update a persisted real run.
        self._run_follow_tail = False

    def on_mount(self):
        super().on_mount()
        self._screen = "run"
        snapshot = demonstration_snapshot(self, final=False)
        events = (
            {"kind": "message", "native_id": "parent-message-1", "title": "Agent",
             "body": "Reviewing authentication changes. Delegating a security review.", "order": 0},
            {"kind": "delegation", "native_id": "agent-1", "call_id": "spawn-1",
             "title": "Security review", "status": "running",
             "body": "Review permission checks and identify security regressions.", "order": 1},
            {"kind": "tool", "call_id": "child-read-a", "parent_id": "agent-1",
             "title": "Read", "category": "read", "body": "src/auth.py",
             "status": "completed", "order": 2},
            {"kind": "tool", "call_id": "child-read-b", "parent_id": "agent-1",
             "title": "Read", "category": "read", "body": "tests/test_auth.py",
             "status": "completed", "order": 3},
            {"kind": "tool", "call_id": "child-tests", "parent_id": "agent-1",
             "title": "Shell", "body": "$ pytest tests/test_auth.py",
             "status": "running", "order": 4},
            {"kind": "message", "native_id": "child-message", "parent_id": "agent-1",
             "title": "Agent", "body": "Inspecting access-control edge cases...", "order": 5},
            {"kind": "message", "native_id": "parent-message-2", "title": "Agent",
             "body": "Continuing implementation while the review is running.", "order": 6},
            {"kind": "delegation", "native_id": "unlinked", "title": "spawn_agent",
             "status": "unknown", "body": "An observed delegation with no correlated children.", "order": 7},
        )
        agent = replace(snapshot.run.agent, structured_events=events,
                        event_count=len(events), session_closed=False)
        project = replace(snapshot.run.shell.project, name="Delegation Demo")
        run = replace(snapshot.run.shell.run, id="sub-agent-demo",
                      short_id="sub-agent-demo", task="Visual test — Sub-agent A")
        shell = replace(snapshot.run.shell, project=project, run=run)
        snap = replace(snapshot, selected_run_id="sub-agent-demo",
                       project=replace(snapshot.project, shell=shell),
                       run=replace(snapshot.run, shell=shell, agent=agent))
        self._operation_run_identity = _snapshot_run_identity(snap)
        self._render_snapshot(snap)


if __name__ == "__main__":
    SubAgentDemo().run()
