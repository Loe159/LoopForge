"""Focused tests for the modular CLI facade."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from loopforge import cli
from loopforge.cli.app import LoopForgeCli
from loopforge.cli.errors import CliError, CliRuntimeError, CliUsageError
from loopforge.cli.models import CliOptions, GitHubIssueRef, IssueReadResult, ReportIssueResult, RunIntake
from loopforge.cli.parser import CliParserBuilder, LoopForgeArgumentParser
from loopforge.cli.workflow import (
    ContinueCommandHandler,
    LearnCommandHandler,
    RunCommandHandler,
    VerifyCommandHandler,
)


class CliStructureTests(unittest.TestCase):
    def test_cli_facade_reexports_models_and_errors(self) -> None:
        self.assertIs(cli.CliOptions, CliOptions)
        self.assertIs(cli.GitHubIssueRef, GitHubIssueRef)
        self.assertIs(cli.RunIntake, RunIntake)
        self.assertIs(cli.IssueReadResult, IssueReadResult)
        self.assertIs(cli.ReportIssueResult, ReportIssueResult)
        self.assertIs(cli.CliError, CliError)
        self.assertIs(cli.CliUsageError, CliUsageError)
        self.assertIs(cli.CliRuntimeError, CliRuntimeError)
        self.assertIs(cli.LoopForgeArgumentParser, LoopForgeArgumentParser)

    def test_build_parser_is_a_compatibility_wrapper(self) -> None:
        parser = object()
        builder = mock.Mock()
        builder.build.return_value = parser

        with mock.patch("loopforge.cli.CliParserBuilder", return_value=builder):
            self.assertIs(cli.build_parser(), parser)

        builder.build.assert_called_once_with()

    def test_main_delegates_to_injected_cli_application(self) -> None:
        application = mock.Mock()
        application.run.return_value = 17

        with mock.patch(
            "loopforge.cli.app.LoopForgeCli",
            return_value=application,
        ) as cli_type:
            self.assertEqual(cli.main(["status"]), 17)

        cli_type.assert_called_once_with(cli)
        application.run.assert_called_once_with(["status"])

    def test_dispatch_stops_at_first_handler_that_accepts_command(self) -> None:
        skipped = mock.Mock()
        skipped.handle.return_value = None
        selected = mock.Mock()
        selected.handle.return_value = 7
        untouched = mock.Mock()
        app = LoopForgeCli(mock.Mock(), handlers=[skipped, selected, untouched])
        args = mock.Mock(command="status")
        context = mock.Mock()

        self.assertEqual(app._dispatch(args, context), 7)

        skipped.handle.assert_called_once_with(args, context)
        selected.handle.assert_called_once_with(args, context)
        untouched.handle.assert_not_called()

    def test_github_client_keeps_the_facade_lookup_seam(self) -> None:
        with mock.patch(
            "loopforge.cli.github_repo_from_remote",
            return_value=("acme", "app"),
        ):
            reference, reason = cli.resolve_github_issue_ref(Path("."), "17")

        self.assertEqual(reason, "")
        self.assertIsNotNone(reference)
        assert reference is not None
        self.assertEqual(reference.owner, "acme")
        self.assertEqual(reference.number, 17)
        self.assertEqual(reference.url, "https://github.com/acme/app/issues/17")

    def test_workflow_commands_have_separate_handlers(self) -> None:
        self.assertEqual(RunCommandHandler.commands, frozenset({"run"}))
        self.assertEqual(ContinueCommandHandler.commands, frozenset({"continue"}))
        self.assertEqual(VerifyCommandHandler.commands, frozenset({"verify"}))
        self.assertEqual(LearnCommandHandler.commands, frozenset({"learn"}))

    def test_parser_builder_preserves_commands_topics_and_options(self) -> None:
        parser = CliParserBuilder().build()

        self.assertIsInstance(parser, LoopForgeArgumentParser)
        self.assertEqual(
            set(cli.parser_topics(parser)),
            {
                (),
                ("init",),
                ("report",),
                ("run",),
                ("status",),
                ("guide",),
                ("dashboard",),
                ("doctor",),
                ("pack",),
                ("pack", "list"),
                ("pack", "detect"),
                ("metrics",),
                ("metrics", "record"),
                ("metrics", "summarize"),
                ("continue",),
                ("verify",),
                ("learn",),
                ("shell",),
                ("interactive",),
                ("projects",),
                ("open",),
                ("runs",),
                ("version",),
                ("help",),
                ("completion",),
            },
        )
        args = parser.parse_args(
            [
                "run",
                "17",
                "--task",
                "Refactor CLI",
                "--success-check",
                "tests pass",
                "--skill",
                "tests",
                "--allow-tool",
                "pytest",
                "--max-attempts",
                "4",
                "--timeout",
                "900",
                "--rubric",
                "Clear",
                "--format",
                "json",
            ]
        )
        self.assertEqual(args.command, "run")
        self.assertEqual(args.issue_source, "17")
        self.assertEqual(args.task, "Refactor CLI")
        self.assertEqual(args.success_check, ["tests pass"])
        self.assertEqual(args.skill, ["tests"])
        self.assertEqual(args.allow_tool, ["pytest"])
        self.assertEqual(args.max_attempts, 4)
        self.assertEqual(args.timeout, 900)
        self.assertEqual(args.rubric, "Clear")
        self.assertEqual(args.format, "json")

    def test_report_parser_and_sanitized_preview_do_not_use_project_remote(self) -> None:
        parser = CliParserBuilder().build()
        args = parser.parse_args(
            [
                "report",
                "--kind",
                "optimization",
                "--title",
                "Speed up customer-project",
                "--description",
                "customer-project token=super-secret is slow",
                "--include-context",
                "--screen",
                "run",
            ]
        )
        self.assertEqual(args.kind, "optimization")
        self.assertTrue(args.include_context)

        status = mock.Mock(initialized=True, run={"status": "verification_failed", "current_stage": "verify"})
        with mock.patch("loopforge.cli.current_status", return_value=status):
            preview = cli.build_project_report(
                Path("customer-project"),
                kind=args.kind,
                title=args.title,
                description=args.description,
                include_context=args.include_context,
                screen=args.screen,
            )

        self.assertTrue(preview.ok)
        self.assertEqual(preview.repository, "Loe159/LoopForge")
        self.assertIn("screen: run", preview.body)
        self.assertNotIn("customer-project", preview.title + preview.body)
        self.assertNotIn("super-secret", preview.body)

    def test_report_submission_uses_the_loopforge_repository(self) -> None:
        preview = ReportIssueResult(
            ok=True,
            repository="Loe159/LoopForge",
            title="[Bug] Status fails",
            body="report body\n",
        )
        completed = mock.Mock(returncode=0, stdout="https://github.com/Loe159/LoopForge/issues/99\n", stderr="")
        with (
            mock.patch("loopforge.cli.shutil.which", return_value="gh"),
            mock.patch("loopforge.cli.subprocess.run", return_value=completed) as run,
        ):
            result = cli.create_project_report(preview)

        self.assertTrue(result.ok)
        self.assertTrue(result.submitted)
        command = run.call_args.args[0]
        self.assertEqual(command[0:3], ["gh", "issue", "create"])
        self.assertEqual(command[command.index("--repo") + 1], "Loe159/LoopForge")

    def test_parser_errors_keep_the_public_usage_error(self) -> None:
        parser = CliParserBuilder().build()

        with self.assertRaises(CliUsageError) as raised:
            parser.parse_args(["metrics", "record", "--input-tokens", "-1"])

        self.assertEqual(raised.exception.code, "LF_USAGE")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertIn("value must be non-negative", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
