"""Argument parser construction for the LoopForge command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from loopforge.cli.errors import DOCS_URL, CliUsageError
from loopforge.engine import DEFAULT_PROFILE, SUPPORTED_ADAPTERS


class LoopForgeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(
            "LF_USAGE",
            "Invalid command line",
            message,
            fix="Run `loopforge help` or `loopforge help <command>`.",
        )


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def add_format_args(parser: argparse.ArgumentParser, *, csv_format: bool = False) -> None:
    choices = ("text", "json", "csv") if csv_format else ("text", "json")
    parser.add_argument("--format", choices=choices, default="text", help="Output format.")


def add_table_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--columns", help="Comma-separated columns to show.")
    parser.add_argument("--sort", help="Sort rows by a column.")
    parser.add_argument("--filter", help="Only show rows containing this text.")
    parser.add_argument("--no-headers", action="store_true", help="Omit table or CSV headers.")
    parser.add_argument("--no-truncate", action="store_true", help="Do not truncate text columns.")


class CliParserBuilder:
    """Build the public argparse command tree without dispatching commands."""

    def build(self) -> argparse.ArgumentParser:
        parser = LoopForgeArgumentParser(
            prog="loopforge",
            description="LoopForge is a portable agentic workflow engine.",
            epilog=(
                "Workflow: loopforge init -> loopforge run --task \"...\" -> loopforge run cockpit\n"
                "The cockpit advances one stage at a time: task validation, task approval, "
                "read-only research, read-only plan, plan approval, implementation, "
                "deterministic verification, read-only review, review approval, and local "
                "draft publication artifact.\n\n"
                "Global flags: --no-color --no-input --quiet --debug --json --version -V\n"
                "Examples:\n"
                "  loopforge init\n"
                "  loopforge run --task \"Add status output\" --success-check \"tests pass\"\n"
                "  loopforge run\n"
                "  loopforge continue --adapter codex -- -m gpt-5\n"
                "  loopforge status --format json\n"
                f"More: {DOCS_URL}"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics: dict[tuple[str, ...], argparse.ArgumentParser] = {(): parser}
        subcommands = parser.add_subparsers(dest="command")

        init_parser = subcommands.add_parser(
            "init",
            help="Initialize LoopForge metadata for a project.",
            epilog="Example:\n  loopforge init --profile supervised",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("init",)] = init_parser
        init_parser.add_argument(
            "--profile",
            default=DEFAULT_PROFILE,
            choices=("assist", "supervised", "autonomous", "strict"),
            help="Autonomy profile to store in .loopforge/config.json.",
        )
        add_format_args(init_parser)

        run_parser = subcommands.add_parser(
            "run",
            help="Create or resume the LoopForge cockpit for a task.",
            epilog=(
                "`loopforge run` is the cockpit for the staged workflow. With an active run "
                "and no new task/source, it resumes that run and can prompt for at most one "
                "eligible stage: task validation, task approval, read-only research, read-only "
                "plan, plan approval, implementation, deterministic verification, read-only "
                "review, review approval, or a local draft PR publication artifact. GitHub "
                "issue runs require the "
                "`agent:approved` label before creation; manual tasks ask for local approval. "
                "Verification is evidence for review, not publication authority. --no-input "
                "only reports status and never approves, executes, or publishes a stage.\n\n"
                "Examples:\n"
                "  loopforge run --task \"Improve the CLI help\"\n"
                "  loopforge run\n"
                "  loopforge run --task \"Refactor parser\" --success-check \"pytest passes\"\n"
                "  loopforge run --task \"Improve copy\" --rubric \"Clear and accurate\"\n"
                "  loopforge run --task \"Add checks\" --pack python --skill tests"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("run",)] = run_parser
        run_parser.add_argument(
            "issue_source",
            nargs="?",
            help="Optional GitHub issue URL or issue ID inferred from the current git remote.",
        )
        run_parser.add_argument(
            "--task",
            help="Task description for the run.",
        )
        run_parser.add_argument(
            "--pack",
            help="Project pack to use. Defaults to automatic project detection.",
        )
        run_parser.add_argument(
            "--success-check",
            action="append",
            default=[],
            help="Objective check required before an autonomous continuation.",
        )
        run_parser.add_argument(
            "--skill",
            action="append",
            default=[],
            help="Selected LoopForge skill for this run. Can be passed more than once.",
        )
        run_parser.add_argument(
            "--allow-tool",
            action="append",
            default=[],
            help="Allowed tool or command family for this run. Can be passed more than once.",
        )
        run_parser.add_argument(
            "--max-attempts",
            type=int,
            default=3,
            help="Maximum bounded attempts allowed by the loop contract.",
        )
        run_parser.add_argument(
            "--timeout",
            type=int,
            default=1800,
            help="Maximum wall-clock seconds allowed by the loop contract.",
        )
        run_parser.add_argument(
            "--rubric",
            default="",
            help="Subjective quality rubric required before autonomous subjective work.",
        )
        add_format_args(run_parser)

        status_parser = subcommands.add_parser(
            "status",
            help="Show the current LoopForge loop state.",
            epilog="Examples:\n  loopforge status\n  loopforge status --details\n  loopforge status --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("status",)] = status_parser
        status_parser.add_argument(
            "--details",
            action="store_true",
            help="Show detailed paths, profile policy, artifacts, and verification evidence.",
        )
        add_format_args(status_parser)
        guide_parser = subcommands.add_parser(
            "guide",
            help="Explain the current workflow state and recommended next actions.",
            epilog="Examples:\n  loopforge guide\n  loopforge guide --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("guide",)] = guide_parser
        add_format_args(guide_parser)
        dashboard_parser = subcommands.add_parser(
            "dashboard",
            help="Show a read-only local dashboard for LoopForge runs.",
            epilog="Examples:\n  loopforge dashboard\n  loopforge dashboard --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("dashboard",)] = dashboard_parser
        dashboard_parser.add_argument(
            "--details",
            action="store_true",
            help="Show attempt, proposal, and adapter comparison details.",
        )
        add_format_args(dashboard_parser)

        pack_parser = subcommands.add_parser(
            "pack",
            help="List or detect LoopForge project packs.",
            epilog="Examples:\n  loopforge pack list\n  loopforge pack detect --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("pack",)] = pack_parser
        pack_subcommands = pack_parser.add_subparsers(dest="pack_command", required=True)
        pack_list = pack_subcommands.add_parser("list", help="List available project packs.")
        topics[("pack", "list")] = pack_list
        add_format_args(pack_list, csv_format=True)
        add_table_args(pack_list)
        pack_detect = pack_subcommands.add_parser("detect", help="Show the pack selected for this project.")
        topics[("pack", "detect")] = pack_detect
        add_format_args(pack_detect)

        metrics_parser = subcommands.add_parser(
            "metrics",
            help="Record or summarize compact LoopForge run metrics.",
            epilog="Examples:\n  loopforge metrics record --final-disposition complete\n  loopforge metrics summarize --format csv",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("metrics",)] = metrics_parser
        metrics_subcommands = metrics_parser.add_subparsers(
            dest="metrics_command",
            required=True,
        )
        metrics_record = metrics_subcommands.add_parser(
            "record",
            help="Write a compact JSON metrics record for the current or selected run.",
        )
        topics[("metrics", "record")] = metrics_record
        metrics_record.add_argument("--run-id", help="Run id to record. Defaults to current run.")
        metrics_record.add_argument("--model", help="Model id when adapter output did not report one.")
        metrics_record.add_argument("--input-tokens", type=non_negative_int)
        metrics_record.add_argument("--output-tokens", type=non_negative_int)
        metrics_record.add_argument("--total-tokens", type=non_negative_int)
        metrics_record.add_argument("--cost-microunits", type=non_negative_int)
        metrics_record.add_argument("--cost-currency")
        metrics_record.add_argument("--human-corrections", type=non_negative_int)
        metrics_record.add_argument("--final-disposition")
        add_format_args(metrics_record)
        metrics_summarize = metrics_subcommands.add_parser(
            "summarize",
            help="Compare recorded metrics across runs.",
        )
        topics[("metrics", "summarize")] = metrics_summarize
        metrics_summarize.add_argument(
            "--details",
            action="store_true",
            help="Include the per-run table in text output.",
        )
        add_format_args(metrics_summarize, csv_format=True)
        add_table_args(metrics_summarize)

        continue_parser = subcommands.add_parser(
            "continue",
            help="Validate the current loop contract and optionally execute an adapter attempt.",
            epilog=(
                "Examples:\n"
                "  loopforge continue\n"
                "  loopforge continue --adapter codex -- -m gpt-5\n"
                "  loopforge continue --confirm --adapter local-adapter-fixture -- python -c \"print('ok')\""
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("continue",)] = continue_parser
        continue_parser.add_argument(
            "--adapter",
            choices=SUPPORTED_ADAPTERS,
            help="Adapter to use for a bounded Phase 4 attempt.",
        )
        continue_parser.add_argument(
            "--confirm",
            nargs="?",
            const="yes",
            help="Confirm a mutating transition when the strict profile requires it.",
        )
        continue_parser.add_argument(
            "--details",
            action="store_true",
            help="Show run directory and full adapter evidence.",
        )
        continue_parser.add_argument(
            "adapter_args",
            nargs=argparse.REMAINDER,
            help="Arguments passed to the adapter command after --.",
        )
        add_format_args(continue_parser)

        verify_parser = subcommands.add_parser(
            "verify",
            help="Generate a complete patch and run deterministic pack verification.",
            epilog="Examples:\n  loopforge verify\n  loopforge verify --confirm\n  loopforge verify --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("verify",)] = verify_parser
        verify_parser.add_argument(
            "--confirm",
            nargs="?",
            const="yes",
            help="Confirm verification artifact generation when the strict profile requires it.",
        )
        verify_parser.add_argument(
            "--details",
            action="store_true",
            help="Show detailed patch and risk evidence.",
        )
        add_format_args(verify_parser)

        learn_parser = subcommands.add_parser(
            "learn",
            help="Propose or approve durable project memory updates for the current run.",
            epilog="Examples:\n  loopforge learn\n  loopforge learn --note \"Fact: this repo uses unittest\"\n  loopforge learn --approve --confirm",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("learn",)] = learn_parser
        learn_parser.add_argument(
            "--approve",
            action="store_true",
            help="Promote safe proposals to durable project memory with human approval.",
        )
        learn_parser.add_argument(
            "--confirm",
            nargs="?",
            const="yes",
            help="Confirm durable memory promotion when the strict profile requires it.",
        )
        learn_parser.add_argument(
            "--note",
            action="append",
            default=[],
            help=(
                "Explicit memory candidate, such as "
                "'Fact: this repo uses unittest'. Can be passed more than once."
            ),
        )
        learn_parser.add_argument(
            "--details",
            action="store_true",
            help="Show proposal details in addition to the operator summary.",
        )
        add_format_args(learn_parser)

        shell_parser = subcommands.add_parser(
            "shell",
            aliases=("interactive",),
            help="Start the LoopForge interactive shell.",
            epilog=(
                "Examples:\n"
                "  loopforge shell\n"
                "  loopforge shell --command \"/status\"\n"
                "  loopforge shell --script commands.loopforge"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("shell",)] = shell_parser
        topics[("interactive",)] = shell_parser
        shell_parser.add_argument(
            "--command",
            dest="shell_command",
            help="Run a single interactive command, such as '/status', then exit.",
        )
        shell_parser.add_argument(
            "--script",
            type=Path,
            help="Run interactive commands from a UTF-8 script file, then exit.",
        )

        runs_parser = subcommands.add_parser(
            "runs",
            help="List known LoopForge runs for this project.",
            epilog="Examples:\n  loopforge runs\n  loopforge runs --format json\n  loopforge runs --columns run_id,status,task --filter failed",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("runs",)] = runs_parser
        runs_parser.add_argument(
            "--all-projects",
            action="store_true",
            help="List runs across registered projects.",
        )
        add_format_args(runs_parser, csv_format=True)
        add_table_args(runs_parser)

        projects_parser = subcommands.add_parser(
            "projects",
            help="List globally registered LoopForge projects.",
            epilog="Examples:\n  loopforge projects\n  loopforge projects --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("projects",)] = projects_parser
        add_format_args(projects_parser, csv_format=True)
        add_table_args(projects_parser)

        open_parser = subcommands.add_parser(
            "open",
            help="Open or register a project by path, id, or unique name.",
            epilog=(
                "Examples:\n  loopforge open ../api\n  loopforge open project-abc\n"
                "  loopforge open ../moved-repo --moved\n  loopforge open ../clone --clone"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("open",)] = open_parser
        open_parser.add_argument("project", nargs="?", help="Project path, registered id, or unique name.")
        identity = open_parser.add_mutually_exclusive_group()
        identity.add_argument("--moved", action="store_true", help="Confirm that this path is the moved registered project.")
        identity.add_argument("--clone", action="store_true", help="Give this copied repository a new project identity.")
        add_format_args(open_parser)

        version_parser = subcommands.add_parser(
            "version",
            help="Show LoopForge version and runtime details.",
            epilog="Examples:\n  loopforge version\n  loopforge version --format json",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("version",)] = version_parser
        add_format_args(version_parser)

        help_parser = subcommands.add_parser(
            "help",
            help="Show help for LoopForge or a command.",
            epilog="Examples:\n  loopforge help\n  loopforge help run\n  loopforge help pack list",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("help",)] = help_parser
        help_parser.add_argument("topic", nargs="*", help="Command or subcommand to explain.")

        completion_parser = subcommands.add_parser(
            "completion",
            help="Print shell completion script.",
            epilog=(
                "Examples:\n"
                "  loopforge completion bash\n"
                "  loopforge completion powershell > loopforge-completion.ps1"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        topics[("completion",)] = completion_parser
        completion_parser.add_argument("shell", choices=("bash", "zsh", "fish", "powershell"))

        setattr(parser, "_loopforge_topics", topics)
        return parser
