"""Command line interface for LoopForge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loopforge.engine import (
    DEFAULT_PROFILE,
    SUPPORTED_ADAPTERS,
    continue_run,
    create_run,
    current_guidance,
    current_status,
    dashboard_snapshot,
    dashboard_text_lines,
    detect_project_pack,
    discover_pack_contracts,
    initialize_project,
    learn_run,
    profile_permission_lines,
    record_run_metrics,
    summarize_run_metrics,
    verify_run,
)


def print_guidance(project_dir: Path, *, concise: bool = False) -> None:
    guidance = current_guidance(project_dir)
    print("guidance:")
    print(f"now: {guidance.summary}")
    if guidance.blocked_reasons:
        print("problem:")
        for reason in guidance.blocked_reasons:
            print(f"- {reason}")
    elif guidance.diagnostics and not concise:
        print("diagnostics:")
        for diagnostic in guidance.diagnostics:
            print(f"- {diagnostic}")
    if guidance.recommended_actions:
        first = guidance.recommended_actions[0]
        print(f"recommended next action: [{first.id}] {first.label}")
        print(f"command: {first.command}")
        print(f"why: {first.why}")
    if not concise and len(guidance.recommended_actions) > 1:
        print("useful commands:")
        for action in guidance.recommended_actions[1:]:
            print(f"- [{action.id}] {action.command} ({action.why})")


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


def print_verification(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"verification: {state.get('status', 'unknown')}")
    patch = state.get("patch", {})
    if isinstance(patch, dict):
        print(f"patch: {patch.get('path') or 'none'}")
        print(f"patch size bytes: {patch.get('size_bytes', 0)}")
    diff_policy = state.get("diff_policy", {})
    if isinstance(diff_policy, dict):
        print(f"diff policy allowed: {diff_policy.get('allowed')}")
    risk = state.get("risk", {})
    if isinstance(risk, dict):
        print(f"risk: {risk.get('risk') or 'unknown'}")
        if risk.get("policy"):
            print(f"risk policy: {risk['policy']}")
    print(f"pack checks: {state.get('checks_passed', 0)}/{state.get('checks_total', 0)}")
    if state.get("stagnated"):
        print("stagnation: yes")


def print_memory(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"durable memory: {state.get('durable_items', 0)} items")
    print(f"durable memory path: {state.get('durable_path') or 'none'}")
    print(f"run memory snapshot: {state.get('run_snapshot') or 'none'}")
    print(
        "memory proposals: "
        f"{state.get('pending', 0)} pending, "
        f"{state.get('promoted', 0)} promoted, "
        f"{state.get('rejected', 0)} rejected"
    )
    if state.get("proposal_path"):
        print(f"memory proposal path: {state['proposal_path']}")


def print_pack_contract(run: dict[str, object]) -> None:
    contract = run.get("pack_contract", {})
    if not isinstance(contract, dict):
        return
    if contract.get("source"):
        print(f"pack source: {contract['source']}")
    if contract.get("detection"):
        print(f"pack selection: {contract['detection']}")
    skills = contract.get("skills", [])
    if isinstance(skills, list):
        print(f"pack skills: {len(skills)}")
        for skill in skills:
            print(f"- {skill}")


def print_profile_policy(profile: object, *, file=None) -> None:
    if file is None:
        file = sys.stdout
    for line in profile_permission_lines(profile):
        print(line, file=file)


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def print_json_payload(payload: object) -> None:
    import json

    print(json.dumps(payload, indent=2, sort_keys=True))


def format_metric_value(value: object) -> str:
    return "unknown" if value is None else str(value)


def print_metrics_record(record: dict[str, object], record_path: Path) -> None:
    print(f"metrics record: {record_path}")
    print(f"run id: {record.get('run_id')}")
    timing = record.get("timing", {})
    if isinstance(timing, dict):
        print(f"duration seconds: {format_metric_value(timing.get('duration_seconds'))}")
    adapter = record.get("adapter", {})
    if isinstance(adapter, dict):
        print(f"adapter: {format_metric_value(adapter.get('id'))}")
    model = record.get("model", {})
    if isinstance(model, dict):
        print(f"model: {format_metric_value(model.get('id'))}")
    tokens = record.get("tokens", {})
    if isinstance(tokens, dict):
        print(f"tokens: {tokens.get('status', 'unknown')}")
    cost = record.get("cost", {})
    if isinstance(cost, dict):
        print(f"cost: {cost.get('status', 'unknown')}")
    patch = record.get("patch", {})
    if isinstance(patch, dict):
        print(f"patch size bytes: {format_metric_value(patch.get('size_bytes'))}")
    verification = record.get("verification", {})
    if isinstance(verification, dict):
        print(f"verification: {format_metric_value(verification.get('status'))}")
    final = record.get("final_disposition", {})
    if isinstance(final, dict):
        print(f"final disposition: {format_metric_value(final.get('status'))}")


def print_metric_series(name: str, series: object) -> None:
    if not isinstance(series, dict):
        return
    average = series.get("average")
    if average is None:
        average_text = "unknown"
    elif isinstance(average, float):
        average_text = f"{average:.2f}".rstrip("0").rstrip(".")
    else:
        average_text = str(average)
    print(
        f"{name}: average {average_text} "
        f"(known {series.get('known_count', 0)}, unknown {series.get('unknown_count', 0)})"
    )


def print_metrics_summary(summary: dict[str, object]) -> None:
    print("LoopForge metrics summary")
    print(f"records: {summary.get('record_count', 0)}")
    print_metric_series("duration seconds", summary.get("duration_seconds"))
    print_metric_series("attempt count", summary.get("attempt_count"))
    print_metric_series("patch size bytes", summary.get("patch_size_bytes"))
    cost = summary.get("cost", {})
    if isinstance(cost, dict):
        totals = cost.get("amount_microunits_by_currency", {})
        print(
            "cost records: "
            f"known {cost.get('known_count', 0)}, unknown {cost.get('unknown_count', 0)}"
        )
        if isinstance(totals, dict) and totals:
            for currency, amount in totals.items():
                print(f"cost {currency}: {amount} microunits")
    verification = summary.get("verification_results", {})
    if isinstance(verification, dict):
        print("verification results:")
        for name, count in verification.items():
            print(f"- {name}: {count}")
    final = summary.get("final_dispositions", {})
    if isinstance(final, dict):
        print("final dispositions:")
        for name, count in final.items():
            print(f"- {name}: {count}")
    runs = summary.get("runs", [])
    if isinstance(runs, list) and runs:
        print("runs:")
        for run in runs:
            if not isinstance(run, dict):
                continue
            print(
                "- "
                f"{run.get('run_id')}: "
                f"duration={format_metric_value(run.get('duration_seconds'))}, "
                f"attempts={format_metric_value(run.get('attempt_count'))}, "
                f"patch={format_metric_value(run.get('patch_size_bytes'))}, "
                f"verification={format_metric_value(run.get('verification'))}, "
                f"disposition={format_metric_value(run.get('final_disposition'))}"
            )


def print_dashboard(snapshot: dict[str, object]) -> None:
    for line in dashboard_text_lines(snapshot):
        print(line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopforge")
    subcommands = parser.add_subparsers(dest="command")

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

    subcommands.add_parser(
        "status",
        help="Show the current LoopForge loop state.",
    )
    subcommands.add_parser(
        "guide",
        help="Explain the current workflow state and recommended next actions.",
    )
    dashboard_parser = subcommands.add_parser(
        "dashboard",
        help="Show a read-only local dashboard for LoopForge runs.",
    )
    dashboard_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    pack_parser = subcommands.add_parser(
        "pack",
        help="List or detect LoopForge project packs.",
    )
    pack_subcommands = pack_parser.add_subparsers(dest="pack_command", required=True)
    pack_subcommands.add_parser("list", help="List available project packs.")
    pack_subcommands.add_parser("detect", help="Show the pack selected for this project.")

    metrics_parser = subcommands.add_parser(
        "metrics",
        help="Record or summarize compact LoopForge run metrics.",
    )
    metrics_subcommands = metrics_parser.add_subparsers(
        dest="metrics_command",
        required=True,
    )
    metrics_record = metrics_subcommands.add_parser(
        "record",
        help="Write a compact JSON metrics record for the current or selected run.",
    )
    metrics_record.add_argument("--run-id", help="Run id to record. Defaults to current run.")
    metrics_record.add_argument("--model", help="Model id when adapter output did not report one.")
    metrics_record.add_argument("--input-tokens", type=non_negative_int)
    metrics_record.add_argument("--output-tokens", type=non_negative_int)
    metrics_record.add_argument("--total-tokens", type=non_negative_int)
    metrics_record.add_argument("--cost-microunits", type=non_negative_int)
    metrics_record.add_argument("--cost-currency")
    metrics_record.add_argument("--human-corrections", type=non_negative_int)
    metrics_record.add_argument("--final-disposition")
    metrics_record.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    metrics_summarize = metrics_subcommands.add_parser(
        "summarize",
        help="Compare recorded metrics across runs.",
    )
    metrics_summarize.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    continue_parser = subcommands.add_parser(
        "continue",
        help="Validate the current loop contract and optionally execute an adapter attempt.",
    )
    continue_parser.add_argument(
        "--adapter",
        choices=SUPPORTED_ADAPTERS,
        help="Adapter to use for a bounded Phase 4 attempt.",
    )
    continue_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm a mutating transition when the strict profile requires it.",
    )
    continue_parser.add_argument(
        "adapter_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to the adapter command after --.",
    )

    verify_parser = subcommands.add_parser(
        "verify",
        help="Generate a complete patch and run deterministic pack verification.",
    )
    verify_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm verification artifact generation when the strict profile requires it.",
    )

    learn_parser = subcommands.add_parser(
        "learn",
        help="Propose or approve durable project memory updates for the current run.",
    )
    learn_parser.add_argument(
        "--approve",
        action="store_true",
        help="Promote safe proposals to durable project memory with human approval.",
    )
    learn_parser.add_argument(
        "--confirm",
        action="store_true",
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

    shell_parser = subcommands.add_parser(
        "shell",
        aliases=("interactive",),
        help="Start the LoopForge interactive shell.",
    )
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from loopforge.interactive import run_interactive

            return run_interactive(Path.cwd())
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if args.command in {"shell", "interactive"}:
        from loopforge.interactive import run_interactive

        if args.shell_command is None and args.script is None:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                print(
                    "LoopForge shell requires an interactive terminal, "
                    "or use --command/--script.",
                    file=sys.stderr,
                )
                return 2
        return run_interactive(
            Path.cwd(),
            command=args.shell_command,
            script=args.script,
        )
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
        print_profile_policy(result.config["profile"])
        print(f"run root: {result.config['run_root']}")
        return 0
    if args.command == "run":
        try:
            result = create_run(
                Path.cwd(),
                task=args.task,
                pack=args.pack,
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
        print(f"pack: {result.run['pack']}")
        print_profile_policy(result.run["profile"])
        print(f"loop contract: {result.run['loop_contract']['path']}")
        if result.run["loop_contract"]["subjective"] and not args.rubric:
            print("rubric: needed before autonomous attempts")
        print_guidance(Path.cwd(), concise=True)
        return 0
    if args.command == "pack":
        if args.pack_command == "list":
            packs = discover_pack_contracts(Path.cwd())
            if not packs:
                print("No project packs found.")
                return 0
            for pack in packs:
                description = pack.get("description") or ""
                print(f"{pack['name']}: {description}".rstrip())
                print(f"  source: {pack.get('source') or 'none'}")
            return 0
        if args.pack_command == "detect":
            pack = detect_project_pack(Path.cwd())
            print(f"pack: {pack['name']}")
            print(f"source: {pack.get('source') or 'none'}")
            print(f"score: {pack.get('detection_score', 0)}")
            return 0
    if args.command == "metrics":
        if args.metrics_command == "record":
            result = record_run_metrics(
                Path.cwd(),
                run_id=args.run_id,
                model=args.model,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                total_tokens=args.total_tokens,
                cost_microunits=args.cost_microunits,
                cost_currency=args.cost_currency,
                human_corrections=args.human_corrections,
                final_disposition=args.final_disposition,
            )
            output = sys.stdout if result.ok else sys.stderr
            if args.format == "json":
                payload = {
                    "ok": result.ok,
                    "message": result.message,
                    "record_path": str(result.record_path) if result.record_path else None,
                    "record": result.record,
                    "blockers": result.blockers,
                }
                print_json_payload(payload)
            else:
                print(result.message, file=output)
                if result.record is not None and result.record_path is not None:
                    print_metrics_record(result.record, result.record_path)
                if result.blockers:
                    print("blockers:", file=output)
                    for blocker in result.blockers:
                        print(f"- {blocker}", file=output)
            return 0 if result.ok else 1
        if args.metrics_command == "summarize":
            result = summarize_run_metrics(Path.cwd())
            output = sys.stdout if result.ok else sys.stderr
            if args.format == "json":
                payload = {
                    "ok": result.ok,
                    "message": result.message,
                    "run_root": str(result.run_root) if result.run_root else None,
                    "summary": result.summary,
                    "blockers": result.blockers,
                }
                print_json_payload(payload)
            else:
                print(result.message, file=output)
                if result.run_root is not None:
                    print(f"run root: {result.run_root}", file=output)
                print_metrics_summary(result.summary)
                if result.blockers:
                    print("blockers:", file=output)
                    for blocker in result.blockers:
                        print(f"- {blocker}", file=output)
            return 0 if result.ok else 1
    if args.command == "status":
        result = current_status(Path.cwd())
        print(f"project: {result.project_dir.name}")
        if not result.initialized:
            print("state: not initialized")
            print(f"config: {result.config_path}")
            print(f"next step: {result.next_step}")
            print_guidance(Path.cwd())
            return 0

        assert result.config is not None
        print("state: initialized")
        print(f"profile: {result.config['profile']}")
        print_profile_policy(result.config["profile"])
        print(f"run root: {result.config['run_root']}")

        if result.run is None:
            print(f"current run: {result.config.get('current_run_id') or 'none'}")
            if result.run_dir is not None:
                print(f"run directory: {result.run_dir}")
                print_native_artifacts(result.native_artifacts)
            print_memory(result.memory)
            print("blockers:")
            if result.blockers:
                for blocker in result.blockers:
                    print(f"- {blocker}")
            else:
                print("- none")
            print(f"next step: {result.next_step}")
            print_guidance(Path.cwd())
            return 0

        run = result.run
        print(f"current run: {run['run_id']}")
        print(f"task: {run['task']}")
        print(f"loop status: {run['status']}")
        print(f"attempts: {run.get('attempt_count', len(run.get('attempts', [])))}")
        print(f"pack: {run['pack']}")
        print_pack_contract(run)
        print(f"base commit: {run.get('base_commit') or 'none'}")
        print(f"run directory: {result.run_dir}")
        print_native_artifacts(result.native_artifacts)
        print_loop_contract(result.loop_contract)
        print_legacy_artifacts(result.legacy_artifacts)
        print_verification(result.verification)
        print_memory(result.memory)
        print("blockers:")
        if result.blockers:
            for blocker in result.blockers:
                print(f"- {blocker}")
        else:
            print("- none")
        print(f"next step: {result.next_step}")
        print_guidance(Path.cwd())
        return 0
    if args.command == "guide":
        print_guidance(Path.cwd())
        return 0
    if args.command == "dashboard":
        result = dashboard_snapshot(Path.cwd())
        if args.format == "json":
            payload = {
                "ok": result.ok,
                "blockers": result.blockers,
                "dashboard": result.snapshot,
            }
            print_json_payload(payload)
        else:
            print_dashboard(result.snapshot)
        return 0
    if args.command == "continue":
        adapter_args = args.adapter_args
        if adapter_args and adapter_args[0] == "--":
            adapter_args = adapter_args[1:]
        result = continue_run(
            Path.cwd(),
            adapter=args.adapter,
            adapter_args=adapter_args,
            confirmed=args.confirm,
        )
        output = sys.stdout if result.ok else sys.stderr
        print(result.message, file=output)
        if result.run_dir is not None:
            print(f"run directory: {result.run_dir}", file=output)
        if result.contract is not None:
            print(f"loop contract: {result.contract['status']}", file=output)
            print(f"success checks: {len(result.contract.get('success_checks', []))}", file=output)
        if result.run is not None:
            print_profile_policy(result.run.get("profile"), file=output)
        if result.attempt is not None:
            print(f"attempt: {result.attempt['id']}", file=output)
            print(f"adapter: {result.attempt['adapter']}", file=output)
            print(f"attempt status: {result.attempt['status']}", file=output)
            print(f"workspace changed: {result.attempt['workspace_changed']}", file=output)
            print(f"stdout: {result.attempt['stdout_path']}", file=output)
            print(f"stderr: {result.attempt['stderr_path']}", file=output)
        if result.blockers:
            print("blockers:", file=output)
            for blocker in result.blockers:
                print(f"- {blocker}", file=output)
        print_guidance(Path.cwd(), concise=True)
        return 0 if result.ok else 1
    if args.command == "verify":
        result = verify_run(Path.cwd(), confirmed=args.confirm)
        output = sys.stdout if result.ok else sys.stderr
        print(result.message, file=output)
        if result.run_dir is not None:
            print(f"run directory: {result.run_dir}", file=output)
        if result.run is not None:
            print_profile_policy(result.run.get("profile"), file=output)
        if result.verification is not None:
            patch = result.verification.get("patch", {})
            diff_policy = result.verification.get("diff_policy", {})
            risk = result.verification.get("risk", {})
            print(f"verification: {result.verification['status']}", file=output)
            if isinstance(patch, dict):
                print(f"patch: {patch.get('path') or 'none'}", file=output)
                print(f"patch size bytes: {patch.get('size_bytes', 0)}", file=output)
            if isinstance(diff_policy, dict):
                print(f"diff policy allowed: {diff_policy.get('allowed')}", file=output)
            if isinstance(risk, dict):
                print(f"risk: {risk.get('risk') or 'unknown'}", file=output)
                if risk.get("policy"):
                    print(f"risk policy: {risk['policy']}", file=output)
            print(
                "pack checks: "
                f"{result.verification.get('checks_passed', 0)}/"
                f"{result.verification.get('checks_total', 0)}",
                file=output,
            )
        if result.blockers:
            print("blockers:", file=output)
            for blocker in result.blockers:
                print(f"- {blocker}", file=output)
        print_guidance(Path.cwd(), concise=True)
        return 0 if result.ok else 1
    if args.command == "learn":
        result = learn_run(
            Path.cwd(),
            approve=args.approve,
            notes=args.note,
            confirmed=args.confirm,
        )
        output = sys.stdout if result.ok else sys.stderr
        print(result.message, file=output)
        if result.run_dir is not None:
            print(f"run directory: {result.run_dir}", file=output)
        if result.run is not None:
            print_profile_policy(result.run.get("profile"), file=output)
        if result.proposal_path is not None:
            print(f"proposal path: {result.proposal_path}", file=output)
        print(f"proposals: {len(result.proposals)}", file=output)
        print(f"promoted: {len(result.promoted)}", file=output)
        print(f"rejected: {len(result.rejected)}", file=output)
        pending = sum(1 for proposal in result.proposals if proposal.get("status") == "pending")
        print(f"pending: {pending}", file=output)
        if result.blockers:
            print("blockers:", file=output)
            for blocker in result.blockers:
                print(f"- {blocker}", file=output)
        print_guidance(Path.cwd(), concise=True)
        return 0 if result.ok else 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
