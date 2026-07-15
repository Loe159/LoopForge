"""Phase-1 shared presentation and action contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

from loopforge.cli.actions import action_descriptors, primary_action
from loopforge.cli.presentation import shell_snapshot, state_family, workflow_progress
from loopforge.engine import GuidedAction, GuidanceResult, StatusResult


class CliPresentationTests(unittest.TestCase):
    def test_engine_guidance_maps_to_immutable_action_descriptors(self) -> None:
        guidance = self._guidance(
            GuidedAction(
                id="approve-plan",
                label="Review and approve the implementation plan",
                command="loopforge run",
                risk="low",
                requires_confirmation=True,
                why="Implementation requires a human plan approval.",
            )
        )

        actions = action_descriptors(guidance)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].executor_key, "approve-plan")
        self.assertEqual(actions[0].command_fallback, "loopforge run")
        self.assertTrue(actions[0].requires_confirmation)
        self.assertEqual(primary_action(guidance), actions[0])

    def test_snapshot_uses_pack_workflow_for_stage_and_actor(self) -> None:
        project_dir = Path("/workspace/LoopForge")
        workflow = [
            {"id": "task", "title": "Validate task", "actor": {"id": "intake"}},
            {"id": "research", "title": "Research", "actor": {"id": "researcher"}},
            {"id": "plan", "title": "Plan", "actor": {"id": "planner"}},
        ]
        status = StatusResult(
            project_dir=project_dir,
            config_path=project_dir / ".loopforge" / "config.json",
            initialized=True,
            config={"profile": "supervised"},
            run_dir=project_dir / "runs" / "run-1",
            run_json_path=None,
            run={
                "run_id": "run-1234567890",
                "task": "Improve the command view",
                "pack": "generic-code",
                "status": "awaiting_approval",
                "pack_contract": {"workflow": workflow},
                "stage_statuses": {"task": "approved", "research": "complete", "plan": "awaiting_approval"},
            },
            native_artifacts=None,
            legacy_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=None,
            next_step="loopforge run",
            blockers=[],
        )
        guidance = self._guidance(
            GuidedAction(
                id="approve-plan",
                label="Approve plan",
                command="loopforge run",
                risk="low",
                requires_confirmation=True,
                why="The plan waits for approval.",
            ),
            state="plan_awaiting_approval",
        )

        snapshot = shell_snapshot(status, guidance)
        progress, actor, _ = workflow_progress(status.run or {})

        self.assertEqual(snapshot.family, "needs_human")
        self.assertEqual(snapshot.run.short_id, "run-12345678")
        self.assertEqual(snapshot.stages[-1].actor, "human-approver")
        self.assertEqual(snapshot.stages[-1].family, "needs_human")
        self.assertEqual(progress, "3/3 Plan")
        self.assertEqual(actor, "human-approver")

    def test_state_family_keeps_blockers_and_archives_distinct(self) -> None:
        self.assertEqual(state_family("verification_pending"), "ready")
        self.assertEqual(state_family("verification_pending", blocked=True), "blocked")
        self.assertEqual(state_family("draft_publication_ready", archived=True), "archived")

    @staticmethod
    def _guidance(action: GuidedAction, *, state: str = "plan_awaiting_approval") -> GuidanceResult:
        return GuidanceResult(
            project_dir=Path("/workspace/LoopForge"),
            state=state,
            summary="A test guidance state.",
            priority="test",
            diagnostics=[],
            recommended_actions=[action],
            blocked_reasons=[],
            evidence=[],
        )
