"""Command line interface for LoopForge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loopforge.engine import (
    DEFAULT_PROFILE,
    continue_run,
    create_run,
    current_status,
    initialize_project,
)


def print_native_artifacts(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"native artifacts: {state['status']} ({state['present']}/{state['total']})")
    missing_files = state.get("missing_files", [])
    missing_directories = state.get("missing_directories", [])
    if missing_files:
        print(f"native missing files: {', '.join(str(name) for name in missing_files)}")
    if missing_directories:
        print(f"native missing directories: {', '.join(str(name) for name in missing_directories)}")


def print_legacy_artifacts(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"legacy artifacts: {state['status']}")
    print(f"legacy issue: {state.get('issue') or 'none'}")
    print(f"legacy artifact directory: {state.get('artifact_dir') or 'none'}")
    errors = state.get("errors", [])
    if errors:
        print("legacy artifact notes:")
        for error in errors:
            if isinstance(error, dict):
                artifact = error.get("artifact", "*")
                rule = error.get("rule", "note")
                message = error.get("message", error)
                print(f"- {artifact} {rule}: {message}")
            else:
                print(f"- {error}")


def print_loop_contract(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"loop contract: {state['status']}")
    print(f"success checks: {len(state.get('success_checks', []))}")
    print(f"subjective: {'yes' if state.get('subjective') else 'no'}")
    if state.get("subjective"):
        print(f"rubric: {'present' if state.get('rubric') else 'missing'}")
    errors = state.get("errors", [])
    if errors:
        print("loop contract notes:")
        for error in errors:
            print(f"- {error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopforge")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser(
        "init",
        help="Initialize LoopForge metadata for a project.",
    )
    init_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=("assist", "supervised", "autonomous", "strict"),
        help="Autonomy profile to store in .loopforge/config.json.",
    )

    run_parser = subcommands.add_parser(
        "run",
        help="Create a LoopForge run for a task.",
    )
    run_parser.add_argument(
        "--task",
        required=True,
        help="Task description for the run.",
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

    subcommands.add_parser(
        "status",
        help="Show the current LoopForge loop state.",
    )

    subcommands.add_parser(
        "continue",
        help="Validate the current loop contract before the next bounded action.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        result = initialize_project(Path.cwd(), profile=args.profile)
        if result.created:
            action = "initialized"
        elif result.repaired:
            action = "repaired"
        else:
            action = "already initialized"
        print(f"LoopForge {action}: {result.config_path}")
        print(f"project: {result.config['project_name']}")
        print(f"profile: {result.config['profile']}")
        print(f"run root: {result.config['run_root']}")
        return 0
    if args.command == "run":
        try:
            result = create_run(
                Path.cwd(),
                task=args.task,
                success_checks=args.success_check,
                selected_skills=args.skill,
                allowed_tools=args.allow_tool,
                max_attempts=args.max_attempts,
                timeout_seconds=args.timeout,
                subjective_rubric=args.rubric,
            )
        except (FileNotFoundError, ValueError) as error:
            print(f"LoopForge run failed: {error}", file=sys.stderr)
            return 1
        print(f"LoopForge run created: {result.run_dir}")
        print(f"run id: {result.run['run_id']}")
        print(f"task id: {result.run['task_id']}")
        print(f"base commit: {result.run['base_commit'] or 'none'}")
        print(f"status: {result.run['status']}")
        print(f"loop contract: {result.run['loop_contract']['path']}")
        if result.run["loop_contract"]["subjective"] and not args.rubric:
            print("rubric: needed before autonomous attempts")
        return 0
    if args.command == "status":
        result = current_status(Path.cwd())
        print(f"project: {result.project_dir.name}")
        if not result.initialized:
            print("state: not initialized")
            print(f"config: {result.config_path}")
            print(f"next step: {result.next_step}")
            return 0

        assert result.config is not None
        print("state: initialized")
        print(f"profile: {result.config['profile']}")
        print(f"run root: {result.config['run_root']}")

        if result.run is None:
            print(f"current run: {result.config.get('current_run_id') or 'none'}")
            if result.run_dir is not None:
                print(f"run directory: {result.run_dir}")
                print_native_artifacts(result.native_artifacts)
            print("blockers:")
            if result.blockers:
                for blocker in result.blockers:
                    print(f"- {blocker}")
            else:
                print("- none")
            print(f"next step: {result.next_step}")
            return 0

        run = result.run
        print(f"current run: {run['run_id']}")
        print(f"task: {run['task']}")
        print(f"loop status: {run['status']}")
        print(f"pack: {run['pack']}")
        print(f"base commit: {run.get('base_commit') or 'none'}")
        print(f"run directory: {result.run_dir}")
        print_native_artifacts(result.native_artifacts)
        print_loop_contract(result.loop_contract)
        print_legacy_artifacts(result.legacy_artifacts)
        print("blockers:")
        if result.blockers:
            for blocker in result.blockers:
                print(f"- {blocker}")
        else:
            print("- none")
        print(f"next step: {result.next_step}")
        return 0
    if args.command == "continue":
        result = continue_run(Path.cwd())
        output = sys.stdout if result.ok else sys.stderr
        print(result.message, file=output)
        if result.run_dir is not None:
            print(f"run directory: {result.run_dir}", file=output)
        if result.contract is not None:
            print(f"loop contract: {result.contract['status']}", file=output)
            print(f"success checks: {len(result.contract.get('success_checks', []))}", file=output)
        if result.blockers:
            print("blockers:", file=output)
            for blocker in result.blockers:
                print(f"- {blocker}", file=output)
        return 0 if result.ok else 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
