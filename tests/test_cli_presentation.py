"""Phase-1 shared presentation and action contracts."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from loopforge.cli.actions import action_descriptors, primary_action
from loopforge.cli.models import UiSnapshot
from loopforge.cli.operations import OperationController
from loopforge.cli.presentation import shell_snapshot, shell_snapshot_from_status, state_family, workflow_progress
from loopforge.cli.state_store import StateStore
from loopforge.engine import GuidedAction, GuidanceResult, StatusResult, current_guidance, current_status, guidance_from_status


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

    def test_current_guidance_is_a_single_status_compatibility_wrapper(self) -> None:
        project = Path("/workspace/LoopForge")
        status = current_status(project)
        with (
            mock.patch("loopforge.engine.current_status", return_value=status) as status_read,
            mock.patch("loopforge.engine.guidance_from_status", wraps=guidance_from_status) as from_status,
        ):
            current_guidance(project)

        status_read.assert_called_once_with(project)
        from_status.assert_called_once_with(status)

    def test_snapshot_from_status_does_not_reload_status(self) -> None:
        status = current_status(Path("/workspace/LoopForge"))
        with mock.patch("loopforge.engine.current_status") as status_read:
            shell_snapshot_from_status(status)

        status_read.assert_not_called()

    def test_state_store_publishes_immutable_snapshots_only_for_current_navigation(self) -> None:
        project = Path("/workspace/LoopForge")
        other_project = Path("/workspace/Other")
        status = current_status(project)
        runs = SimpleNamespace(runs=[], blockers=[])
        projects = SimpleNamespace(projects=[])
        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: runs,
            projects_loader=lambda: projects,
            branch_loader=lambda _: "main",
        )
        published: list[UiSnapshot] = []
        store.subscribe(published.append)

        first = store.refresh()
        again = store.refresh()

        self.assertEqual(first.revision, again.revision)
        self.assertEqual(len(published), 1)
        with self.assertRaises(TypeError):
            first.home.projects[0]["name"] = "mutated"  # type: ignore[index]

        late_load = store.begin_load()
        store.select_project(other_project)
        after_navigation = store.snapshot
        discarded = store.publish_loaded(late_load, status, runs, projects)

        self.assertEqual(discarded.selected_project, other_project)
        self.assertEqual(discarded.revision, after_navigation.revision)

    def test_state_store_coalesces_operation_events_until_the_ui_turn_flushes(self) -> None:
        project = Path("/workspace/LoopForge")
        status = current_status(project)
        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
            projects_loader=lambda: SimpleNamespace(projects=[]),
            branch_loader=lambda _: "main",
        )
        store.refresh()
        published: list[UiSnapshot] = []
        store.subscribe(published.append)
        operation = OperationController("Refresh")
        store.set_operation(operation)
        operation.emit({"kind": "activity", "message": "First"})
        operation.emit({"kind": "activity", "message": "Second"})

        store.record_operation_events(operation)

        self.assertEqual(len(published), 1)
        snapshot = store.flush()
        self.assertEqual(len(published), 2)
        self.assertEqual([event.message for event in snapshot.operation.events], ["First", "Second"])

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
