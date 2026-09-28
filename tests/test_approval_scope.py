"""A confirmation remains bound to the run and evidence the human saw."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.evidence import approval_summary
from loopforge.cli.interactive import InteractiveShell
from loopforge.engine import (
    ActionScope,
    approve_initial_task,
    approve_plan,
    create_run,
    current_status,
    initialize_project,
    resume_run,
    write_json_atomic,
)


def _scope(project: Path, stage: str) -> ActionScope:
    status = current_status(project)
    assert status.config is not None and status.run is not None
    summary = approval_summary(status.run_dir, status.run, stage)
    return ActionScope(
        project_id=status.config["project_id"],
        project_path=status.project_dir,
        run_id=status.run["run_id"],
        revision=status.run.get("run_revision", 0),
        snapshot=summary.artifact_sha256,
        config_revision=status.config.get("config_revision", 0),
    )


class ApprovalScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.project.mkdir()
        self.home = root / "home"
        self.environment = mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        subprocess.run(["git", "init"], cwd=self.project, check=True, capture_output=True)
        (self.project / "README.md").write_text("# Project\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=LoopForge Tests", "-c", "user.email=loopforge@example.invalid", "commit", "-m", "initial"],
            cwd=self.project,
            check=True,
            capture_output=True,
        )
        initialize_project(self.project)

    def _prepare_plan(self) -> Path:
        created = create_run(self.project, "Task A", success_checks=["Proof exists"])
        run = dict(created.run)
        run["stage_statuses"]["plan"] = "awaiting_approval"
        run["current_stage"] = "plan_ready"
        write_json_atomic(created.run_json_path, run)
        plan = created.run_dir / "plan.md"
        plan.write_text(
            "---\nartifact_version: 1\nartifact: plan\nissue: 1\nbase_commit: 0000000000000000000000000000000000000000\nstatus: awaiting_approval\n---\n\n"
            "# Overview\n\nBuild A.\n\n# Preconditions\n\nResearch done.\n\n# Implementation Steps\n\n- Change A.\n\n"
            "# Files In Scope\n\n- src/a.py\n\n# Out Of Scope\n\n- Release.\n\n# Verification\n\n- Tests.\n\n"
            "# Stop Conditions\n\n- Wait for approval.\n",
            encoding="utf-8",
        )
        return plan

    def test_modal_scope_for_run_a_cannot_approve_run_b(self) -> None:
        first = create_run(self.project, "Task A", success_checks=["Proof A exists"])
        shown = _scope(self.project, "task")
        second = create_run(self.project, "Task B", success_checks=["Proof B exists"])

        result = approve_initial_task(self.project, expected_scope=shown)

        self.assertFalse(result.ok)
        self.assertIn("confirm again", result.blockers[0])
        self.assertEqual(result.run["run_id"], second.run["run_id"])
        self.assertEqual(current_status(self.project).run["human_gates"]["initial_task_approval"]["status"], "pending")
        self.assertEqual(first.run["run_id"], shown.run_id)

    def test_changed_plan_requires_new_confirmation_through_shared_shell(self) -> None:
        plan = self._prepare_plan()
        shown = _scope(self.project, "plan")
        plan.write_text(plan.read_text(encoding="utf-8").replace("Change A.", "Change B."), encoding="utf-8")
        shell = InteractiveShell(self.project, output=io.StringIO(), error=io.StringIO())
        action = ActionDescriptor("approve-plan", "Approve plan", "Approve recorded plan", "medium", True, True, "/do approve-plan", "approve-plan")

        blocked = shell.execute_guided_action(action, expected_scope=shown)

        self.assertEqual(blocked.exit_code, 1)
        self.assertIn("approval evidence changed", shell.output.getvalue())
        self.assertEqual(current_status(self.project).run["human_gates"]["plan_approval"]["status"], "pending")
        self.assertTrue(approve_plan(self.project, expected_scope=_scope(self.project, "plan")).ok)

    def test_plan_edit_between_validation_and_commit_blocks_approval(self) -> None:
        plan = self._prepare_plan()
        shown = _scope(self.project, "plan")
        original_read = Path.read_bytes
        changed = False

        def edit_after_first_read(path: Path) -> bytes:
            nonlocal changed
            contents = original_read(path)
            if path == plan and not changed:
                changed = True
                plan.write_text(contents.decode("utf-8").replace("Change A.", "Change B."), encoding="utf-8")
            return contents

        with mock.patch.object(Path, "read_bytes", edit_after_first_read):
            blocked = approve_plan(self.project, expected_scope=shown)

        self.assertTrue(changed)
        self.assertFalse(blocked.ok)
        self.assertTrue(any("approval evidence changed" in reason for reason in blocked.blockers))
        self.assertEqual(current_status(self.project).run["human_gates"]["plan_approval"]["status"], "pending")

    def test_switch_away_and_back_still_invalidates_confirmation(self) -> None:
        first = create_run(self.project, "Task A", success_checks=["Proof A exists"])
        shown = _scope(self.project, "task")
        second = create_run(self.project, "Task B", success_checks=["Proof B exists"])
        self.assertTrue(resume_run(self.project, first.run["run_id"]).ok)

        result = approve_initial_task(self.project, expected_scope=shown)

        self.assertFalse(result.ok)
        self.assertIn("context changed", result.blockers[0])
        self.assertEqual(current_status(self.project).run["human_gates"]["initial_task_approval"]["status"], "pending")
        self.assertNotEqual(first.run["run_id"], second.run["run_id"])


@unittest.skipUnless(__import__("importlib").util.find_spec("textual") is not None, "Textual is installed")
class TextualApprovalScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_action_refuses_switch_before_first_status_read(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import ConfirmationScreen

        fixture = ApprovalScopeTests()
        fixture.setUp()
        try:
            first = create_run(fixture.project, "Task A", success_checks=["Proof A exists"])
            second = create_run(fixture.project, "Task B", success_checks=["Proof B exists"])
            self.assertTrue(resume_run(fixture.project, first.run["run_id"]).ok)
            shell = InteractiveShell(fixture.project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell, load_on_mount=False)
            action = ActionDescriptor("approve-task", "Approve task", "Approve recorded task", "medium", True, True, "/do approve-task", "approve-task")
            async with app.run_test() as pilot:
                app.store.refresh(fixture.project)
                await pilot.pause()
                self.assertEqual(app.snapshot.run.shell.run.id, first.run["run_id"])
                actual_status = current_status
                reads = 0

                def switch_on_first_read(project: Path):
                    nonlocal reads
                    reads += 1
                    self.assertTrue(resume_run(project, second.run["run_id"]).ok)
                    return actual_status(project)

                with mock.patch("loopforge.cli.textual_app.app.current_status", side_effect=switch_on_first_read):
                    app.request_action(action)
                    await pilot.pause(0.1)
                self.assertEqual(reads, 1)
                self.assertIn("confirm again", app._notice)
                self.assertNotIsInstance(app.screen, ConfirmationScreen)
            self.assertEqual(current_status(fixture.project).run["human_gates"]["initial_task_approval"]["status"], "pending")
        finally:
            fixture.doCleanups()

    async def test_project_screen_request_does_not_follow_run_switch_during_load(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import ConfirmationScreen

        fixture = ApprovalScopeTests()
        fixture.setUp()
        try:
            first = create_run(fixture.project, "Task A", success_checks=["Proof A exists"])
            second = create_run(fixture.project, "Task B", success_checks=["Proof B exists"])
            self.assertTrue(resume_run(fixture.project, first.run["run_id"]).ok)
            shell = InteractiveShell(fixture.project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell, load_on_mount=False)
            action = ActionDescriptor("approve-task", "Approve task", "Approve recorded task", "medium", True, True, "/do approve-task", "approve-task")
            async with app.run_test() as pilot:
                app.select_project(fixture.project)
                for _ in range(80):
                    if len(app.snapshot.project.runs) >= 2:
                        break
                    await pilot.pause(0.05)
                self.assertGreaterEqual(len(app.snapshot.project.runs), 2)
                app._screen = "project"
                selected_index = next(
                    index for index, row in enumerate(app._filtered_runs())
                    if dict(row).get("run_id") == first.run["run_id"]
                )
                app._screen_list().highlighted = selected_index
                self.assertEqual(app._target_run_id(), first.run["run_id"])
                actual_status = current_status
                reads = 0

                def switch_before_worker_read(project: Path):
                    nonlocal reads
                    reads += 1
                    if reads == 2:
                        self.assertTrue(resume_run(project, second.run["run_id"]).ok)
                    return actual_status(project)

                with mock.patch("loopforge.cli.textual_app.app.current_status", side_effect=switch_before_worker_read):
                    app.request_action(action)
                    for _ in range(80):
                        if "confirm again" in app._notice:
                            break
                        await pilot.pause(0.05)
                self.assertEqual(reads, 2)
                self.assertIn("confirm again", app._notice)
                self.assertNotIsInstance(app.screen, ConfirmationScreen)
            self.assertEqual(current_status(fixture.project).run["human_gates"]["initial_task_approval"]["status"], "pending")
        finally:
            fixture.doCleanups()

    async def test_confirmation_callback_keeps_run_a_after_external_switch(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import ConfirmationScreen

        fixture = ApprovalScopeTests()
        fixture.setUp()
        try:
            first = create_run(fixture.project, "Task A", success_checks=["Proof A exists"])
            second = create_run(fixture.project, "Task B", success_checks=["Proof B exists"])
            self.assertTrue(resume_run(fixture.project, first.run["run_id"]).ok)
            shell = InteractiveShell(fixture.project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell, load_on_mount=False)
            action = ActionDescriptor("approve-task", "Approve task", "Approve recorded task", "medium", True, True, "/do approve-task", "approve-task")
            async with app.run_test() as pilot:
                app.select_project(fixture.project)
                for _ in range(80):
                    if len(app.snapshot.project.runs) >= 2:
                        break
                    await pilot.pause(0.05)
                app._screen = "project"
                selected_index = next(
                    index for index, row in enumerate(app._filtered_runs())
                    if dict(row).get("run_id") == first.run["run_id"]
                )
                app._screen_list().highlighted = selected_index
                app.request_action(action)
                for _ in range(80):
                    if isinstance(app.screen, ConfirmationScreen):
                        break
                    await pilot.pause(0.05)
                self.assertIsInstance(app.screen, ConfirmationScreen)
                self.assertTrue(resume_run(fixture.project, second.run["run_id"]).ok)
                await pilot.click("#confirm-approve")
                for _ in range(80):
                    if app._operation is not None and app._operation.finished:
                        break
                    await pilot.pause(0.05)
                self.assertIsNotNone(app._operation)
                self.assertTrue(app._operation.finished)
            self.assertEqual(current_status(fixture.project).run["human_gates"]["initial_task_approval"]["status"], "pending")
            self.assertFalse(app._operation.result.ok)
            self.assertIn("context changed", app._operation.result.message.lower())
        finally:
            fixture.doCleanups()
