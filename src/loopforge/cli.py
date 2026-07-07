"""Command line interface for LoopForge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loopforge.engine import DEFAULT_PROFILE, create_run, current_status, initialize_project


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

    subcommands.add_parser(
        "status",
        help="Show the current LoopForge loop state.",
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
            result = create_run(Path.cwd(), task=args.task)
        except (FileNotFoundError, ValueError) as error:
            print(f"LoopForge run failed: {error}", file=sys.stderr)
            return 1
        print(f"LoopForge run created: {result.run_dir}")
        print(f"run id: {result.run['run_id']}")
        print(f"task id: {result.run['task_id']}")
        print(f"base commit: {result.run['base_commit'] or 'none'}")
        print(f"status: {result.run['status']}")
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
        print("blockers:")
        if result.blockers:
            for blocker in result.blockers:
                print(f"- {blocker}")
        else:
            print("- none")
        print(f"next step: {result.next_step}")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
