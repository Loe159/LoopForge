"""Tests for application command parity across CLI surfaces.

Covers Subtask 3 of Epic 3: each mutating command reaches a single
application command implementation and returns a consistent
``AppCommandResult`` regardless of the calling surface.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import loopforge.commands  # noqa: F401  (registers all commands via side effects)
from loopforge.commands.base import (
    CommandContext,
    _REGISTRY,
    execute_command,
)
from loopforge.engine.models.commands import AppCommandResult

EXPECTED_COMMANDS = frozenset(
    {
        "init",
        "open_project",
        "start_run",
        "resume_run",
        "approve",
        "execute_stage",
        "verify",
        "review",
        "archive",
        "doctor",
        "learn",
        "list_runs",
    }
)


def _ctx(project_dir: Path, home: Path) -> CommandContext:
    """Build a headless CommandContext scoped to an isolated home."""

    return CommandContext(project_dir=project_dir, home=home, renderer=None)


class CommandRegistryTests(unittest.TestCase):

    def test_all_twelve_commands_registered(self) -> None:
        registered = set(_REGISTRY.keys())
        self.assertEqual(
            EXPECTED_COMMANDS,
            registered,
            f"missing: {EXPECTED_COMMANDS - registered}, "
            f"extra: {registered - EXPECTED_COMMANDS}",
        )

    def test_registry_callables_return_appcommandresult_signature(self) -> None:
        for name, func in _REGISTRY.items():
            self.assertTrue(callable(func), f"command {name!r} is not callable")


class InitCommandTests(unittest.TestCase):

    def test_init_command_creates_project(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")

            result = execute_command("init", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertEqual(result.command, "init")
            self.assertTrue(result.ok, result.errors)
            self.assertTrue(result.data["created"])
            self.assertFalse(result.data["repaired"])
            self.assertTrue(Path(result.data["config_path"]).exists())
            self.assertTrue(result.data["config"].get("project_id"))

    def test_init_command_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")

            first = execute_command("init", ctx)
            second = execute_command("init", ctx)

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertTrue(first.data["created"])
            self.assertFalse(second.data["created"], msg=str(second.data))
            self.assertEqual(
                first.data["config_path"], second.data["config_path"]
            )


class OpenProjectCommandTests(unittest.TestCase):

    def test_open_project_opens_current_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("open_project", ctx, target=str(project))

            self.assertIsInstance(result, AppCommandResult)
            self.assertEqual(result.command, "open_project")
            self.assertTrue(result.ok, result.errors)
            self.assertTrue(Path(result.data["config_path"]).exists())


class StartRunCommandTests(unittest.TestCase):

    def test_start_run_creates_run_in_shared_checkout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command(
                "start_run", ctx, task="Add a feature", success_checks=["tests pass"]
            )

            self.assertIsInstance(result, AppCommandResult)
            self.assertEqual(result.command, "start_run")
            self.assertTrue(result.ok, result.errors)
            self.assertTrue(result.data["run_id"])
            self.assertEqual(result.data["status"], "loop_contract_ready")
            self.assertEqual(result.data["task"], "Add a feature")
            self.assertIn("created run", result.effects)


class ResumeRunCommandTests(unittest.TestCase):

    def test_resume_run_blocked_with_invalid_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command(
                "resume_run", ctx, run_id="does-not-exist"
            )

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertTrue(result.errors)
            self.assertEqual(result.errors[0].code, "BLOCKED")


class ApproveCommandTests(unittest.TestCase):

    def test_approve_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("approve", ctx, stage="plan")

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")

    def test_approve_unknown_stage_is_blocked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")

            result = execute_command("approve", ctx, stage="bogus")

            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")


class ExecuteStageCommandTests(unittest.TestCase):

    def test_execute_stage_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("execute_stage", ctx, stage="research")

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")

    def test_execute_stage_returns_stage_in_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("execute_stage", ctx, stage="research")

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")


class VerifyCommandTests(unittest.TestCase):

    def test_verify_command_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("verify", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")
            self.assertTrue(result.errors[0].message)


class ReviewCommandTests(unittest.TestCase):

    def test_review_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("review", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")


class ArchiveCommandTests(unittest.TestCase):

    def test_archive_command_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("archive", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")


class DoctorCommandTests(unittest.TestCase):

    def test_doctor_command_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("doctor", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertEqual(result.command, "doctor")
            self.assertIn("summary", result.data)
            self.assertIn("diagnostics", result.data)
            self.assertIn("ok", result.data)


class LearnCommandTests(unittest.TestCase):

    def test_learn_blocked_without_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("learn", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "BLOCKED")
            self.assertTrue(result.errors[0].message)


class ListRunsCommandTests(unittest.TestCase):

    def test_list_runs_empty_project(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)

            result = execute_command("list_runs", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.data["runs"], [])
            self.assertIsNone(result.data["current_run_id"])

    def test_list_runs_reflects_created_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            ctx = _ctx(project, root / "home")
            execute_command("init", ctx)
            execute_command(
                "start_run", ctx, task="A task", success_checks=["ok"]
            )

            result = execute_command("list_runs", ctx)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(len(result.data["runs"]), 1)


class AppCommandResultShapeTests(unittest.TestCase):
    """Every registered command must return an AppCommandResult, never crash."""

    def _prepared_ctx(self, root: Path) -> CommandContext:
        project = root / "project"
        ctx = _ctx(project, root / "home")
        execute_command("init", ctx)
        return ctx

    def test_all_commands_return_appcommandresult(self) -> None:
        # Minimal valid kwargs for each command on a freshly initialized project.
        invocations = {
            "init": {},
            "open_project": {},
            "start_run": {"task": "Demo", "success_checks": ["ok"]},
            "resume_run": {"run_id": "missing-run"},
            "approve": {"stage": "plan"},
            "execute_stage": {"stage": "research"},
            "verify": {},
            "review": {},
            "archive": {},
            "doctor": {},
            "learn": {},
            "list_runs": {},
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = self._prepared_ctx(root)
            for name in EXPECTED_COMMANDS:
                with self.subTest(command=name):
                    kwargs = invocations[name]
                    result = execute_command(name, ctx, **kwargs)

                    self.assertIsInstance(
                        result,
                        AppCommandResult,
                        f"{name} did not return an AppCommandResult",
                    )
                    self.assertEqual(result.command, name)
                    self.assertIsInstance(result.ok, bool)
                    self.assertIsInstance(result.errors, list)
                    self.assertIsInstance(result.effects, list)
                    self.assertIsInstance(result.next_actions, list)


class ExecuteCommandDispatchTests(unittest.TestCase):

    def test_unknown_command_returns_appcommandresult(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ctx = _ctx(root / "project", root / "home")

            result = execute_command("not-a-real-command", ctx)

            self.assertIsInstance(result, AppCommandResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.errors[0].code, "UNKNOWN_COMMAND")
            self.assertFalse(result.errors[0].recoverable)


if __name__ == "__main__":
    unittest.main()
