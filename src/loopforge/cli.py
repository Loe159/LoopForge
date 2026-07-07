"""Initial LoopForge CLI placeholder."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopforge")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init", help="Initialize LoopForge metadata for a project.")
    subcommands.add_parser("status", help="Show the current LoopForge run state.")

    run_parser = subcommands.add_parser("run", help="Create a run from a task.")
    run_parser.add_argument("--task", required=True, help="Task description.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        print("LoopForge init is planned; see docs/implementation-plan.md.")
        return 0
    if args.command == "status":
        print("LoopForge status is planned; see docs/implementation-plan.md.")
        return 0
    if args.command == "run":
        print(f"LoopForge run is planned for task: {args.task}")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
