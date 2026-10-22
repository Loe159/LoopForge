"""Native intake, operation and task-contract regression coverage."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from textual.widgets import Button, TextArea

from loopforge.cli.interactive import DispatchResult, InteractiveShell
from loopforge.cli.task_intake import TaskContext, load_task_context
from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.task_composer import TaskComposer
from loopforge.engine import ActionScope, complete_task_definition, current_status, initialize_project
from tests import test_cli as cli_fixtures
from tests.test_cli_textual_app import wait_for_condition


@asynccontextmanager
async def composer_case(*, width=120, height=40, profile="supervised", complete=False):
    shell = SimpleNamespace(project_dir=Path.cwd(), theme="dark", output=io.StringIO(),
                            error=io.StringIO(), renderer=None,
                            create_run_from_intake=Mock(return_value=DispatchResult(0, run_id="new-run")),
                            complete_current_task_definition=Mock(return_value=DispatchResult(0)))
    app = LoopForgeApp(shell, load_on_mount=False)
    context = TaskContext(ActionScope("project-demo", Path.cwd(), "old-run" if complete else None,
                                      0, config_revision=0),
                          "AUTH DEMO", profile, "generic-code", "codex",
                          task="Recorded task" if complete else "")
    with patch.object(TaskComposer, "load_context"), patch(
        "loopforge.cli.textual_app.app.load_task_context", return_value=context,
    ), patch.object(app, "_open_run_worker"):
        async with app.run_test(size=(width, height)) as pilot:
            form = TaskComposer(Path.cwd(), complete=complete, run_id=context.scope.run_id)
            app.push_screen(form, app._task_form_closed)
            await pilot.pause()
            form.apply_context(context)
            await pilot.pause()
            yield app, pilot, form, shell, context


class TaskComposerPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_editor_owns_enter_letters_slashes_and_copy(self):
        async with composer_case() as (app, pilot, form, shell, _):
            await pilot.press(*"nashjklef/x", "enter", *"--task='日本語'", "ctrl+c")
            self.assertEqual(form.draft().task, "nashjklef/x\n--task='日本語'")
            self.assertTrue(app.is_running)
            self.assertIs(app.screen, form)
            shell.create_run_from_intake.assert_not_called()
            self.assertFalse(form.query_one("#task-submit", Button).disabled)

    async def test_criteria_add_remove_preserves_multiline_values_and_focus(self):
        async with composer_case() as (_, pilot, form, _, _):
            form.query_one("#task-description", TextArea).load_text("Task")
            form.query_one("#task-add-criterion", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            second = form.query_one("#criterion-value-2", TextArea)
            self.assertIs(form.focused, second)
            second.load_text("Observable\nresult [red]")
            form.query_one("#criterion-remove-1", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(form.draft().success_checks, ("Observable\nresult [red]",))
            self.assertIs(form.focused, second)

    async def test_empty_task_and_conditional_rubric_use_engine_contract(self):
        async with composer_case(profile="autonomous") as (_, pilot, form, _, _):
            submit = form.query_one("#task-submit", Button)
            self.assertTrue(submit.disabled)
            form.query_one("#task-description", TextArea).load_text("Improve the design of settings")
            await pilot.pause()
            self.assertTrue(form.query_one("#task-rubric-group").display)
            self.assertTrue(submit.disabled)
            form.query_one("#task-rubric", TextArea).load_text("Labels readable; keyboard focus visible")
            await pilot.pause()
            self.assertFalse(submit.disabled)  # Criteria may be completed after creation.
            form.query_one("#task-description", TextArea).load_text("Fix an expired token")
            await pilot.pause()
            self.assertFalse(form.query_one("#task-rubric-group").display)

    async def test_dirty_escape_defaults_to_keep_editing_then_discard(self):
        async with composer_case() as (app, pilot, form, _, _):
            await pilot.press(*"Draft", "escape")
            await pilot.pause()
            self.assertEqual(app.focused.id, "confirm-cancel")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIs(app.screen, form)
            self.assertEqual(form.draft().task, "Draft")
            await pilot.press("escape")
            await pilot.pause()
            app.screen.query_one("#confirm-approve", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 1)

    async def test_resize_keeps_footer_and_focus_scrolls_criteria_into_view(self):
        async with composer_case() as (_, pilot, form, _, _):
            for width in (60, 80, 120, 160):
                await pilot.resize_terminal(width, 24)
                await pilot.pause()
                action = form.query_one("#task-submit")
                self.assertGreaterEqual(action.region.y, 0)
                self.assertLessEqual(action.region.bottom, 24)
                self.assertLessEqual(action.region.right, width)
                self.assertEqual(form.query_one("#task-context-details").display, width >= 110)
                criterion = form.query_one("#criterion-value-1", TextArea)
                criterion.focus()
                await pilot.pause()
                self.assertLess(criterion.region.y, action.region.y)
                self.assertGreater(criterion.region.bottom, 0)

    async def test_double_submit_creates_once_and_preserves_literal_intake(self):
        async with composer_case() as (app, pilot, form, shell, _):
            literal = '--task="a"\n/continue; $(never) `never` 日本語 [red]'
            form.query_one("#task-description", TextArea).load_text(literal)
            form.query_one("#criterion-value-1", TextArea).load_text("--result\n'quoted'")
            await pilot.pause()
            await pilot.press("ctrl+enter", "ctrl+enter")
            await wait_for_condition(pilot, lambda: len(app.screen_stack)==1, "created run")
            shell.create_run_from_intake.assert_called_once_with(literal, success_checks=["--result\n'quoted'"], rubric="")
            app._open_run_worker.assert_called_once_with("new-run")

    async def test_changed_context_refuses_mutation_and_keeps_draft(self):
        async with composer_case() as (app, pilot, form, shell, context):
            form.query_one("#task-description", TextArea).load_text("Keep this text")
            await pilot.pause()
            fresh = replace(context, scope=replace(context.scope, config_revision=1))
            with patch("loopforge.cli.textual_app.app.load_task_context", return_value=fresh):
                await pilot.press("ctrl+enter")
                await wait_for_condition(pilot, lambda: not form.busy, "context refusal")
            shell.create_run_from_intake.assert_not_called()
            self.assertEqual(form.draft().task, "Keep this text")
            self.assertTrue(form.query_one("#task-submit", Button).disabled)
            self.assertTrue(form.query_one("#task-recheck").display)

    async def test_worker_failure_retains_draft_and_requires_recheck(self):
        async with composer_case() as (_, pilot, form, shell, _):
            form.query_one("#task-description", TextArea).load_text("Keep on failure")
            shell.create_run_from_intake.side_effect = OSError("disk not writable")
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await wait_for_condition(pilot, lambda: not form.busy, "recoverable failure")
            self.assertEqual(form.draft().task, "Keep on failure")
            self.assertIn("disk not writable", str(form.query_one("#task-feedback").render()))
            self.assertTrue(form.context_changed)

    async def test_retry_after_known_refusal_does_not_stay_busy(self):
        async with composer_case() as (app, pilot, form, shell, _):
            form.query_one("#task-description", TextArea).load_text("Retry this task")
            shell.create_run_from_intake.return_value = DispatchResult(1)
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await wait_for_condition(pilot, lambda: not form.busy, "first refusal")
            self.assertFalse(form.query_one("#task-submit", Button).disabled)
            shell.create_run_from_intake.return_value = DispatchResult(0, run_id="retry-run")
            await pilot.press("ctrl+enter")
            await wait_for_condition(pilot, lambda: len(app.screen_stack)==1, "retry success")
            self.assertEqual(shell.create_run_from_intake.call_count, 2)

    async def test_busy_form_cannot_be_edited_or_left(self):
        async with composer_case() as (app, pilot, form, _, _):
            form.query_one("#task-description", TextArea).load_text("Keep stable")
            await pilot.pause()
            form.busy = True
            form._update_validation()
            await pilot.press(*"extra", "escape", "ctrl+q")
            self.assertEqual(form.draft().task, "Keep stable")
            self.assertIs(app.screen, form)
            self.assertTrue(form.query_one("#task-add-criterion", Button).disabled)

    async def test_saved_missing_rubric_cannot_offer_an_impossible_completion(self):
        async with composer_case(complete=True) as (_, pilot, form, shell, context):
            form.apply_context(replace(context, missing=("subjective rubric",)))
            form.query_one("#criterion-value-1", TextArea).load_text("An observable criterion")
            await pilot.pause()
            self.assertTrue(form.query_one("#task-submit", Button).disabled)
            await pilot.press("ctrl+enter")
            shell.complete_current_task_definition.assert_not_called()

    async def test_completion_keeps_task_readonly_and_uses_existing_operation(self):
        async with composer_case(complete=True) as (app, pilot, form, shell, context):
            self.assertTrue(form.query_one("#task-description", TextArea).read_only)
            form.query_one("#criterion-value-1", TextArea).load_text("A recorded result")
            await pilot.pause()
            await pilot.press("ctrl+enter")
            await wait_for_condition(pilot, lambda: len(app.screen_stack)==1, "completed task")
            shell.complete_current_task_definition.assert_called_once_with(
                "A recorded result", expected_scope=context.scope)
            shell.create_run_from_intake.assert_not_called()
            app._open_run_worker.assert_called_once_with("old-run")


class TaskIntakeIntegrationTests(unittest.TestCase):
    def test_scoped_completion_refuses_a_different_run_without_editing_it(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOOPFORGE_HOME": str(Path(tmp)/"home")}):
            project = Path(tmp)/"project"
            project.mkdir()
            cli_fixtures.CliTests().initialize_git_project(project)
            initialize_project(project)
            shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
            shell.create_run_from_intake("Original task")
            shown = load_task_context(project)
            shell.create_run_from_intake("Another task")
            before = current_status(project)
            task_bytes = (before.run_dir/"task.md").read_bytes()
            result = complete_task_definition(project, success_check="Only for original task", expected_scope=shown.scope)
            self.assertFalse(result.ok)
            self.assertEqual(current_status(project).run, before.run)
            self.assertEqual((before.run_dir/"task.md").read_bytes(), task_bytes)

    def test_slash_and_typed_intake_share_creation_and_preserve_authority(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOOPFORGE_HOME": str(Path(tmp)/"home")}):
            project = Path(tmp)/"project"
            project.mkdir()
            cli_fixtures.CliTests().initialize_git_project(project)
            initialize_project(project)
            shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
            task = '--task "literal"\n日本語 [red] /continue'
            result = shell.create_run_from_intake(task, success_checks=["first\nresult", "second"])
            self.assertEqual(result.exit_code, 0)
            status = current_status(project)
            self.assertEqual(status.run["task"], task)
            self.assertEqual(status.run["success_checks"], ["first\nresult", "second"])
            self.assertEqual(result.run_id, status.run["run_id"])
            self.assertFalse(status.run["approval"]["approved"])
            self.assertEqual(status.run["stage_statuses"]["research"], "pending")
            self.assertEqual(load_task_context(project).success_checks, ("first\nresult", "second"))
            with patch.object(shell, "create_run_from_intake", return_value=DispatchResult(0)) as create:
                self.assertEqual(shell.cmd_run('--task "Other" --success-check "Known result"').exit_code, 0)
                self.assertEqual(create.call_args.args, ("Other",))
                self.assertEqual(create.call_args.kwargs["success_checks"], ["Known result"])


class TaskRouteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_create_opens_task_and_approval_never_starts_research(self):
        from loopforge.cli.textual_app.screens import ConfirmationScreen

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOOPFORGE_HOME": str(Path(tmp)/"home")}):
            project = Path(tmp)/"project"
            project.mkdir()
            cli_fixtures.CliTests().initialize_git_project(project)
            initialize_project(project)
            shell = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
            app = LoopForgeApp(shell)
            async with app.run_test(size=(100,32)) as pilot:
                await wait_for_condition(pilot, lambda: bool(app.snapshot.home.projects), "Home projects")
                # All projects stays ineligible; the individual row owns New run.
                await pilot.press("n")
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("down", "n")
                await wait_for_condition(pilot, lambda: isinstance(app.screen, TaskComposer) and app.screen.context is not None, "New run")
                form = app.screen
                form.query_one("#task-description", TextArea).load_text("Reject expired API tokens")
                form.query_one("#criterion-value-1", TextArea).load_text("Expired tokens return 401")
                await pilot.pause()
                await pilot.press("ctrl+enter")
                await wait_for_condition(pilot, lambda: app._screen=="run" and bool(app.available_actions), "Task review")
                self.assertIn("Expired tokens return 401", str(app.query_one("#run-task-summary").render()))
                self.assertTrue(app.query_one("#run-command-bar").display)
                status = current_status(project)
                self.assertFalse(status.run["approval"]["approved"])
                self.assertEqual(status.run["stage_statuses"]["research"], "pending")
                await pilot.press("ctrl+enter")
                await wait_for_condition(pilot, lambda: isinstance(app.screen, ConfirmationScreen), "Task confirmation")
                await pilot.press("escape")
                self.assertFalse(current_status(project).run["approval"]["approved"])
                await pilot.press("ctrl+enter")
                await wait_for_condition(pilot, lambda: isinstance(app.screen, ConfirmationScreen), "Task confirmation again")
                app.screen.query_one("#confirm-approve", Button).focus()
                await pilot.press("enter")
                await wait_for_condition(pilot, lambda: current_status(project).run["approval"]["approved"], "explicit approval")
                self.assertEqual(current_status(project).run["stage_statuses"]["research"], "pending")
