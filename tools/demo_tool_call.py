"""Interactive visual fixture for the Run / Live Tool Call component.

Run from the repository checkout:
    .venv/bin/python tools/demo_tool_call.py

All data is synthetic and in-memory: no adapter, Git mutation or network call.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.models import OperationSnapshot, RunAgentSnapshot, RunSnapshot
from loopforge.cli.presentation import ProjectSummary, RunSummary, ShellSnapshot, StageView
from loopforge.cli.textual_app import LoopForgeApp


def demonstration_snapshot(app, *, final: bool):
    project = ProjectSummary("Tool Call UI Demo", Path.cwd(), True, "supervised", "default")
    run = RunSummary("tool-call-demo", "tool-call-demo", "Visual test — Tool Call hybrid",
                     "running", "running", "research", "engine", False, None)
    stages = (StageView("research", "Research repository", "agent", "active",
                        "running", "●", "Research", "read_only"),)
    shell = ShellSnapshot(project, run, stages, (), (), "ready", "running")
    long_output = "\n".join(f"Log line {i:03}: validating synthetic output" for i in range(1, 100))
    events = [
        {"kind": "message", "title": "Agent", "body": "Inspecting the project configuration.",
         "order": 0},
        {"kind": "tool", "title": "Shell", "call_id": "demo-json", "category": "command",
         "status": "completed", "order": 1,
         "body": '  $ cat pack.json\n  Output\n    {\n      "name": "python",\n      "version": 2,\n      "extends": "generic-code"\n    }'},
        {"kind": "tool", "title": "Read", "call_id": "demo-read", "category": "read",
         "status": "completed", "order": 2,
         "body": 'Input: {"file_path": "pyproject.toml"}\nResult: package configuration found'},
        {"kind": "tool", "title": "Shell", "call_id": "demo-error", "category": "command",
         "status": "failed", "order": 3,
         "body": "  $ cat missing-file.json\n  Error: No such file or directory"},
        {"kind": "tool", "title": "Shell", "call_id": "demo-long", "category": "command",
         "status": "completed", "order": 4,
         "body": "  $ print-test-log\n  Output\n" + long_output},
        {"kind": "tool", "title": "Shell", "call_id": "demo-pending", "category": "command",
         "status": "completed" if final else "running", "order": 5,
         "body": "  $ python -m unittest\n  Output\n    Ran 12 tests — OK" if final
                 else "  $ python -m unittest"},
        {"kind": "tool", "title": "Shell", "call_id": "demo-unknown", "category": "command",
         "status": "unknown", "order": 6, "body": "  $ check-unavailable-result"},
    ]
    if final:
        events.append({"kind": "message", "title": "Agent",
                       "body": "Synthetic checks finished. No real commands were executed.",
                       "order": 7})
    agent = RunAgentSnapshot(
        adapter="codex", stage_id="research", session_id="demo/research/session-01",
        session_dir="demo/research/session-01", structured_events=tuple(events),
        event_count=len(events), session_closed=False,
    )
    return replace(
        app.snapshot,
        selected_run_id="tool-call-demo",
        project=replace(app.snapshot.project, state="ready", shell=shell, branch="demo"),
        run=RunSnapshot(state="ready", shell=shell, agent=agent,
                        sessions=({"stage_id": "research", "session_id": agent.session_id,
                                   "label": "Session 01"},)),
        operation=OperationSnapshot(state="empty" if final else "loading"),
    )


class ToolCallDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                         load_on_mount=False)
        self._demo_final = False

    def on_mount(self):
        super().on_mount()
        self._screen = "run"
        from loopforge.cli.textual_app.app import _snapshot_run_identity
        snapshot = demonstration_snapshot(self, final=False)
        self._operation_run_identity = _snapshot_run_identity(snapshot)
        self._render_snapshot(snapshot)
        self.set_timer(5.0, self.finish_demo)

    def _suspend_run_follow(self):
        # Synthetic in-memory snapshots are not backed by a persisted run.
        # Never flush reading preferences into the real project's StateStore:
        # that would replace this demo with an empty/loading project snapshot.
        self._run_follow_tail = False

    def finish_demo(self):
        self._demo_final = True
        self._render_snapshot(demonstration_snapshot(self, final=True))


if __name__ == "__main__":
    ToolCallDemo().run()
