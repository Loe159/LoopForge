"""Read-only visual fixture for the selected Live composition.

PYTHONPATH=src .venv/bin/python tools/demo_live_composition.py --view Context
All data is synthetic. Actions open an explanation, never a real workflow.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.models import OperationSnapshot, RunAgentSnapshot, RunSnapshot
from loopforge.cli.presentation import ProjectSummary, RunSummary, ShellSnapshot, StageView
from loopforge.cli.run_changes import RunChangesSnapshot, RunFileChange
from loopforge.cli.run_context import RunContextSection, RunContextSnapshot
from loopforge.cli.run_evidences import RunEvidenceRecord, RunEvidenceSection, RunEvidencesSnapshot
from loopforge.cli.run_reading import RunReading
from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.app import _snapshot_run_identity
from loopforge.cli.textual_app.screens import RunDetailScreen
from loopforge.cli.textual_app.widgets import RunActivityFeed, RunDocumentView


class LiveCompositionDemo(LoopForgeApp):
    def __init__(self, *, view="Live", state="ready"):
        self.demo_view, self.demo_state = view, state
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"), load_on_mount=False)

    def on_mount(self):
        super().on_mount()
        family = {"approval": "needs_human"}.get(self.demo_state, self.demo_state)
        stage = "plan" if family == "needs_human" else "implementation" if family in {"running", "blocked"} else "verification"
        selected = "plan" if family == "needs_human" else "implementation"
        action = None if family in {"running", "blocked"} else ActionDescriptor(
            "approve-plan" if family == "needs_human" else "verify",
            "Review and approve the implementation plan" if family == "needs_human" else "Generate the patch and run deterministic checks",
            "Review plan.md before implementation." if family == "needs_human" else "The current run is ready for verification.",
            "verification", True, True, "loopforge verify", "verify")
        project = ProjectSummary("AUTH DEMO", Path.cwd(), True, "supervised", "generic-code")
        run = RunSummary("live-composition-demo", "demo", "Synthetic selected Live composition",
                         self.demo_state, family, stage, "engine", False, action)
        stages = tuple(StageView(id, title, "agent", ("pending" if family == "ready" else "active") if id == stage else "complete",
            family if id == stage else "complete", "●" if id == stage else "✓", title, "workspace")
            for id, title in (("research", "Research"), ("plan", "Planning"),
                              ("implementation", "Implementation"), ("verification", "Verification"), ("review", "Review")))
        stages = tuple(replace(s, status="pending", family="waiting", marker="○") if s.id == "review" else s for s in stages)
        shell = ShellSnapshot(project, run, stages, (action,) if action else (), (), self.demo_state, family)
        session = "artifacts/stages/plan" if selected == "plan" else "attempts/attempt-002"
        events = (
            {"kind": "tool", "title": "Shell", "call_id": "test-1", "status": "running" if family == "running" else "completed",
             "body": "$ python -m unittest tests.test_auth\nOutput\nSynthetic test output.", "order": 0},
            {"kind": "message", "title": "Agent", "body": "Expired tokens now return HTTP 401.\n\nAdded **regression coverage** for token expiration.", "order": 1},
            {"kind": "plan", "native_id": "todo", "plan_items": [{"text": text, "status": "in_progress" if family == "running" and i == 2 else "pending" if family == "running" and i == 3 else "completed"} for i, text in
                enumerate(("Inspect token flow", "Add expiry guard", "Run regression tests", "Review edge cases"))], "order": 2},
        )
        agent = RunAgentSnapshot(attempt_number=2 if selected == "implementation" else None,
            adapter="codex", stage_id=selected, session_id=session, session_dir=session,
            session_closed=family != "running", result_ref=session + "/result.json",
            implementation_contract='{"summary": "Synthetic result"}', structured_events=events,
            event_count=len(events), raw_source=session + "/agent-transcript.log",
            raw_output="Synthetic literal transcript. [red] is not Rich markup.")
        context = RunContextSnapshot(sections=(
            RunContextSection("mission", "Mission & Role", "# Implementation\nReject expired tokens and add regression coverage.", source="Captured prompt", authority="declared-in-prompt", expanded=True),
            RunContextSection("instructions", "System Instructions", "Follow the approved scope. Do not publish.", source="Captured role", authority="declared-in-prompt"),
            RunContextSection("documents", "Injected Documents", "# task.md\nReject expired tokens in the API.\n\n## Acceptance\n- Return 401 after expiry.\n- Cover boundary timestamps.", source="Captured prompt", authority="declared-in-prompt"),
            RunContextSection("runner", "Permissions & Security", "Execution mode: terminal\nRunner timeout requested: 600 seconds", source="Prompt injection boundary", authority="runner-recorded"),
        ), raw_prompt="# Literal captured prompt\nSynthetic instructions. [red] is literal.", capture_state="complete")
        record = RunEvidenceRecord("artifact:result", "result.json",
            "Artifact extracted\nSource: LoopForge artifact store\nScope: Implementation · Attempt 02\nAgent content is not verification.",
            '{\n  "summary": "Reject expired tokens",\n  "tests": ["python -m unittest tests.test_auth"]\n}', "json")
        evidences = RunEvidencesSnapshot((
            RunEvidenceSection("deliverables", "Deliverables (1)", "result.json · retained artifact", True, (record,)),
            RunEvidenceSection("contracts", "Output contracts", "Output extracted; no positive contract receipt supplied."),
            RunEvidenceSection("checks", "Tests & verification", "Verification pending · LoopForge workflow"),
            RunEvidenceSection("decisions", "Human decisions", "Review approval pending · human gate"),
        ))
        changes = RunChangesSnapshot(capture_state="complete", source="runner-workspace-snapshots",
            files=(RunFileChange("src/auth.py", "M", additions=5, deletions=1),))
        snapshot = replace(self.snapshot, selected_run_id=run.id,
            project=replace(self.snapshot.project, shell=shell, branch="fix/auth"),
            operation=OperationSnapshot("loading" if family == "running" else "empty"),
            run=RunSnapshot("ready", shell=shell, agent=agent, reading=RunReading(view=self.demo_view),
                attempts=({"number": 2, "status": "blocked" if family == "blocked" else "running" if family == "running" else "completed"},),
                sessions=({"stage_id": selected, "session_id": session, "label": "Attempt 02" if selected == "implementation" else "Session 01"},),
                context=context, evidences=evidences, changes=changes,
                metrics=(("Model", "codex"), ("Time", "04m 12s")), candidate_revision=3))
        self._screen = "run"
        self._operation_run_identity = _snapshot_run_identity(snapshot)
        self._render_snapshot(snapshot)

    def request_action(self, action):
        self.push_screen(RunDetailScreen("Read-only demonstration", action.label + "\n\nNo real workflow is executed by this fixture."))

    def _suspend_run_follow(self):
        self._run_follow_tail = False

    def _change_run_reading(self, **changes):
        reading = replace(self.snapshot.run.reading, **changes, following=False)
        run = replace(self.snapshot.run, reading=reading)
        if changes.get("stage_id") and changes["stage_id"] != run.agent.stage_id:
            run = replace(run, agent=RunAgentSnapshot(stage_id=changes["stage_id"]),
                          context=None, evidences=None, changes=None)
        self._render_snapshot(replace(self.snapshot, run=run))

    def _move(self, delta):
        if self._screen == "run":
            view = self.query_one(RunActivityFeed if self.snapshot.run.reading.view == "Live" else RunDocumentView)
            view.scroll_relative(y=delta, animate=False)
            self._suspend_run_follow()
        else:
            super()._move(delta)

    def action_run_follow(self):
        self._run_follow_tail = True
        self.query_one(RunActivityFeed).scroll_end(animate=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("Live", "Context", "Evidences"), default="Live")
    parser.add_argument("--state", choices=("ready", "approval", "running", "blocked"), default="ready")
    args = parser.parse_args()
    LiveCompositionDemo(view=args.view, state=args.state).run()
