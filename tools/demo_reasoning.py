"""Visual fixture for Run / Live Reasoning variant A.

    PYTHONPATH=src .venv/bin/python tools/demo_reasoning.py

Synthetic observations only: no harness calls, persistence or Git changes.
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


class ReasoningDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                         load_on_mount=False)

    def _suspend_run_follow(self):
        # This is not a persisted run; keep reading state local.
        self._run_follow_tail = False

    def on_mount(self):
        super().on_mount()
        self._screen = "run"
        snapshot = demonstration_snapshot(self, final=True)
        events = (
            {"kind": "message", "title": "Agent", "native_id": "demo-agent-1",
             "body": "I'll inspect the existing tests before changing the implementation.",
             "order": 0},
            {"kind": "reasoning", "title": "Reasoning", "native_id": "demo-reason-1",
             "body": "Check the action routing against the actual engine action.\n"
                     "Only this text was exposed by the demonstration harness.",
             "order": 1},
            {"kind": "tool", "title": "Shell", "call_id": "demo-test",
             "status": "completed", "category": "command",
             "body": "  $ pytest tests/test_cli_textual_app.py\n  Output\n    12 passed",
             "order": 2},
            {"kind": "message", "title": "Agent", "native_id": "demo-agent-2",
             "body": "The previous test did not cover the real action routing.",
             "order": 3},
            {"kind": "reasoning", "title": "Reasoning", "native_id": "demo-reason-2",
             "body": "Add a regression case for the supplied action ID.",
             "order": 4},
        )
        agent = replace(snapshot.run.agent, structured_events=events,
                        event_count=len(events))
        project = replace(snapshot.run.shell.project, name="Reasoning Demo")
        run = replace(snapshot.run.shell.run, id="reasoning-demo",
                      short_id="reasoning-demo", task="Visual test — Reasoning A")
        shell = replace(snapshot.run.shell, project=project, run=run)
        snap = replace(snapshot, selected_run_id="reasoning-demo",
                       project=replace(snapshot.project, shell=shell),
                       run=replace(snapshot.run, shell=shell, agent=agent))
        self._operation_run_identity = _snapshot_run_identity(snap)
        self._render_snapshot(snap)


if __name__ == "__main__":
    ReasoningDemo().run()
