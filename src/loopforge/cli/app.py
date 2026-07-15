"""Application and command handlers for the LoopForge CLI.

The public :mod:`loopforge.cli` module owns the compatibility facade.  This
module deliberately resolves command dependencies through that injected facade
at execution time so existing callers and monkeypatch-based tests keep their
historical lookup points.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import traceback
from typing import Any, Sequence

from loopforge.cli.context import CliContext
from loopforge.cli.workflow import (
    ContinueCommandHandler,
    LearnCommandHandler,
    RunCommandHandler,
    VerifyCommandHandler,
)




class DiscoveryCommandHandler:
    """Handle commands that do not participate in the project workflow."""

    commands = frozenset({"help", "version", "completion", "shell", "interactive"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command not in self.commands:
            return None
        api = context.api
        if args.command == "help":
            topic = getattr(args, "topic", [])
            if topic:
                api.show_help(context.parser, topic)
            else:
                api.print_grouped_help()
            return 0
        if args.command == "version":
            api.print_version(
                context.project_dir,
                api.output_format(args, context.options),
            )
            return 0
        if args.command == "completion":
            print(api.completion_script(args.shell), file=context.stdout, end="")
            return 0
        return self._run_shell(args, context)

    def _run_shell(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        if args.shell_command is None and args.script is None:
            if options.no_input:
                raise api.CliUsageError(
                    "LF_INPUT_REQUIRED",
                    "Interactive shell is disabled",
                    "`--no-input` prevents opening the interactive shell.",
                    fix='Use `loopforge shell --command "/status"` or remove `--no-input`.',
                )
            if not context.stdin.isatty() or not context.stdout.isatty():
                raise api.CliUsageError(
                    "LF_INPUT_REQUIRED",
                    "LoopForge shell requires an interactive terminal",
                    "Use --command or --script when running in a non-interactive environment.",
                    fix='Run `loopforge shell --command "/status"`.',
                )
        interactive = importlib.import_module("loopforge.cli.interactive")
        return interactive.run_interactive(
            context.project_dir,
            command=args.shell_command,
            script=args.script,
        )


class ProjectCommandHandler:
    """Handle project setup and read-only inspection commands."""

    commands = frozenset({"init", "pack", "projects", "open", "runs", "status", "guide", "dashboard"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command not in self.commands:
            return None
        method = getattr(self, f"_handle_{args.command}")
        return method(args, context)

    def _handle_init(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge init",
        )
        result = api.initialize_project(context.project_dir, profile=args.profile)
        if result.registration is not None and not result.registration.ok:
            blockers = [
                f"project id {result.registration.project_id} is already registered at {result.registration.conflict_path}",
                "Use `loopforge open <path> --moved` after moving a repository, or `--clone` for a copy.",
            ]
            if fmt == "json":
                api.print_json_payload({"ok": False, "config": result.config, "blockers": blockers})
            else:
                api.render_blocked(context.error_renderer(), "Project identity needs confirmation", [], blockers=blockers)
            return 1
        if result.created:
            action = "initialized"
        elif result.repaired:
            action = "repaired"
        else:
            action = "already initialized"
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": True,
                    "action": action,
                    "config_path": str(result.config_path),
                    "config": result.config,
                }
            )
            return 0
        if options.quiet:
            return 0
        title = (
            "LoopForge project ready"
            if result.created
            else "Project repaired"
            if result.repaired
            else "Project already ready"
        )
        rows: list[tuple[str, object]] = [
            ("id", result.config["project_id"]),
            ("project", result.config["project_name"]),
            ("profile", result.config["profile"]),
            ("runs", result.config["run_root"]),
        ]
        if result.repaired:
            rows.append(("config", result.config_path))
        if result.migrated_run_root is not None:
            rows.append(("migrated runs", result.migrated_run_root))
        api.render_success(
            context.renderer,
            title,
            rows,
            next_command='loopforge run --task "Describe the task"',
        )
        return 0

    def _handle_pack(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        if args.pack_command == "list":
            detected = api.detect_project_pack(context.project_dir)
            rows = [
                {
                    "current": "*" if pack.get("name") == detected.get("name") else "",
                    "name": pack.get("name") or "",
                    "description": pack.get("description") or "",
                    "skills": len(pack.get("skills", [])),
                    "agents": len(pack.get("agents", [])),
                    "stages": len(pack.get("workflow", [])),
                    "kind": api.pack_kind(pack.get("source"), context.project_dir),
                    "source": pack.get("source") or "none",
                }
                for pack in api.discover_pack_contracts(context.project_dir)
            ]
            if not rows and api.output_format(args, options) == "text":
                print("No project packs found.", file=context.stdout)
                return 0
            if options.quiet and api.output_format(args, options) == "text":
                return 0
            api.print_table_rows(
                rows,
                args,
                key="pack-list",
                title="LoopForge packs",
            )
            return 0
        if args.pack_command == "detect":
            fmt = api.normalize_format(
                api.output_format(args, options),
                allowed=("text", "json"),
                command="loopforge pack detect",
            )
            pack = api.detect_project_pack(context.project_dir)
            if fmt == "json":
                api.print_json_payload({"ok": True, "pack": pack})
                return 0
            if options.quiet:
                return 0
            api.render_success(
                context.renderer,
                "Detected pack",
                [
                    ("pack", pack["name"]),
                    ("score", pack.get("detection_score", 0)),
                    ("why", api.detection_reason(pack, context.project_dir)),
                    ("skills", len(pack.get("skills", []))),
                    ("agents", len(pack.get("agents", []))),
                    ("stages", len(pack.get("workflow", []))),
                    ("source", pack.get("source") or "none"),
                ],
                next_command=(
                    f'loopforge run --pack {pack["name"]} --task "Describe the task"'
                ),
            )
            return 0
        raise api.CliUsageError(
            "LF_USAGE",
            "Unknown pack command",
            str(args.pack_command),
            fix="Run `loopforge help pack`.",
        )

    def _handle_runs(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        if args.all_projects:
            result = api.list_runs_all_projects()
            rows = api.global_run_rows_from_result(result)
            if options.quiet and api.output_format(args, options) == "text":
                return 0
            if api.output_format(args, options) == "text":
                if not rows:
                    print("No runs in registered projects.", file=context.stdout)
                else:
                    api.print_table_rows(rows, args, key="global-runs", title="LoopForge runs")
            else:
                api.print_table_rows(rows, args, key="global-runs", title="LoopForge runs")
            return 0 if not result.blockers else 1
        result = api.list_runs(context.project_dir)
        if result.blockers:
            raise api.CliRuntimeError(
                "LF_CONFIG_MISSING",
                "Project is not initialized",
                "; ".join(result.blockers),
                fix="Run `loopforge init` first.",
            )
        rows = api.run_rows_from_result(result)
        if options.quiet and api.output_format(args, options) == "text":
            return 0
        if api.output_format(args, options) == "text":
            api.print_runs_text(result, args)
        else:
            api.print_table_rows(rows, args, key="runs", title="LoopForge runs")
        return 0

    def _handle_projects(self, args: Any, context: CliContext) -> int:
        api = context.api
        result = api.list_registered_projects()
        rows = api.project_rows(result)
        if context.options.quiet and api.output_format(args, context.options) == "text":
            return 0
        if not rows and api.output_format(args, context.options) == "text":
            print("No registered projects. Run `loopforge open .` to register this project.", file=context.stdout)
            return 0
        api.print_table_rows(rows, args, key="projects", title="LoopForge projects")
        return 0 if not result.blockers else 1

    def _handle_open(self, args: Any, context: CliContext) -> int:
        api = context.api
        resolution = "moved" if args.moved else "clone" if args.clone else None
        result = api.open_project(
            args.project,
            current_project_dir=context.project_dir,
            identity_resolution=resolution,
        )
        fmt = api.normalize_format(api.output_format(args, context.options), allowed=("text", "json"), command="loopforge open")
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "project_dir": str(result.project_dir) if result.project_dir else None,
                    "config": result.init.config if result.init else None,
                    "blockers": result.blockers,
                }
            )
            return 0 if result.ok else 1
        if result.ok and result.init is not None:
            if not context.options.quiet:
                api.render_success(
                    context.renderer,
                    "Project opened",
                    [
                        ("project", result.init.config["project_name"]),
                        ("id", result.init.config["project_id"]),
                        ("path", result.project_dir),
                    ],
                    next_command="loopforge runs",
                )
            return 0
        api.render_blocked(context.error_renderer(), "Project could not be opened", [], blockers=result.blockers)
        return 1

    def _handle_status(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge status",
        )
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": True,
                    "status": api.status_payload(context.project_dir),
                    "guidance": api.guidance_payload(context.project_dir),
                }
            )
            return 0
        if options.quiet:
            return 0
        result = api.current_status(context.project_dir)
        guidance = api.current_guidance(context.project_dir)
        api.render_status(context.renderer, result, guidance, details=args.details)
        return 0

    def _handle_guide(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge guide",
        )
        if fmt == "json":
            api.print_json_payload(
                {"ok": True, "guidance": api.guidance_payload(context.project_dir)}
            )
        else:
            if options.quiet:
                return 0
            api.render_guidance(
                context.renderer,
                api.current_guidance(context.project_dir),
                include_also=not options.quiet,
            )
        return 0

    def _handle_dashboard(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge dashboard",
        )
        result = api.dashboard_snapshot(context.project_dir)
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "blockers": result.blockers,
                    "dashboard": result.snapshot,
                }
            )
        else:
            if options.quiet and result.ok:
                return 0
            api.render_dashboard(context.renderer, result.snapshot, details=args.details)
        return 0


class MetricsCommandHandler:
    """Handle recording and summarizing compact run metrics."""

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command != "metrics":
            return None
        if args.metrics_command == "record":
            return self._record(args, context)
        if args.metrics_command == "summarize":
            return self._summarize(args, context)
        raise context.api.CliUsageError(
            "LF_USAGE",
            "Unknown metrics command",
            str(args.metrics_command),
            fix="Run `loopforge help metrics`.",
        )

    def _record(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        result = api.record_run_metrics(
            context.project_dir,
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
        if api.output_format(args, options) == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "record_path": str(result.record_path) if result.record_path else None,
                    "record": result.record,
                    "blockers": result.blockers,
                }
            )
        else:
            if options.quiet and result.ok:
                return 0
            if result.record is not None and result.record_path is not None:
                record = result.record
                timing = (
                    record.get("timing", {})
                    if isinstance(record.get("timing"), dict)
                    else {}
                )
                tokens = (
                    record.get("tokens", {})
                    if isinstance(record.get("tokens"), dict)
                    else {}
                )
                cost = (
                    record.get("cost", {})
                    if isinstance(record.get("cost"), dict)
                    else {}
                )
                api.render_success(
                    context.renderer,
                    "Metrics recorded",
                    [
                        ("run", record.get("run_id") or "none"),
                        ("duration", api.not_reported(timing.get("duration_seconds"))),
                        (
                            "tokens",
                            api.not_reported(
                                tokens.get("total_tokens") or tokens.get("total")
                            ),
                        ),
                        ("cost", api.not_reported(cost.get("amount_microunits"))),
                        ("file", result.record_path),
                    ],
                )
            if result.blockers:
                api.render_blocked(
                    context.renderer,
                    "Metrics blocked",
                    [("status", result.message)],
                    blockers=result.blockers,
                    next_command='loopforge run --task "Describe the task"',
                )
        return 0 if result.ok else 1

    def _summarize(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        result = api.summarize_run_metrics(context.project_dir)
        fmt = api.output_format(args, options)
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "run_root": str(result.run_root) if result.run_root else None,
                    "summary": result.summary,
                    "blockers": result.blockers,
                }
            )
            return 0 if result.ok else 1
        if fmt == "csv":
            api.print_table_rows(
                api.metrics_rows(result.summary),
                args,
                key="metrics-runs",
            )
            return 0 if result.ok else 1
        output = context.stdout if result.ok else context.stderr
        if options.quiet and result.ok:
            return 0
        api.print_metrics_summary(result.summary, details=args.details)
        if result.blockers:
            print("blockers:", file=output)
            for blocker in result.blockers:
                print(f"- {blocker}", file=output)
        return 0 if result.ok else 1




class LoopForgeCli:
    """Parse, dispatch, and contain failures for one CLI invocation."""

    def __init__(self, api: Any, *, handlers: Sequence[Any] | None = None) -> None:
        self.api = api
        self.handlers = tuple(
            handlers
            or (
                DiscoveryCommandHandler(),
                ProjectCommandHandler(),
                RunCommandHandler(),
                ContinueCommandHandler(),
                VerifyCommandHandler(),
                LearnCommandHandler(),
                MetricsCommandHandler(),
            )
        )

    def run(self, argv: list[str] | None = None) -> int:
        raw_argv = sys.argv[1:] if argv is None else list(argv)
        options, parsed_argv = self.api.preparse_global_options(raw_argv)
        parser = self.api.build_parser()
        context = CliContext(
            api=self.api,
            options=options,
            parser=parser,
            renderer=self.api.TerminalRenderer(sys.stdout, no_color=options.no_color),
            project_dir=Path.cwd(),
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        try:
            early_result = self._handle_early_invocation(parsed_argv, context)
            if early_result is not None:
                return early_result
            args = parser.parse_args(parsed_argv)
            self.api.set_format_from_json_alias(args, options)
            return self._dispatch(args, context)
        except KeyboardInterrupt:
            error = self.api.CliRuntimeError(
                "LF_INTERRUPTED",
                "Interrupted",
                "Interrupted. Run `loopforge status` to inspect state.",
                fix="Run `loopforge status`.",
                exit_code=130,
            )
            self.api.render_cli_error(error, options)
            return 130
        except self.api.CliError as error:
            self.api.render_cli_error(error, options)
            return error.exit_code
        except SystemExit as error:
            return int(error.code) if isinstance(error.code, int) else 2
        except Exception as error:  # pragma: no cover - defensive top-level guard.
            cli_error = self.api.CliRuntimeError(
                "LF_INTERNAL",
                "Unexpected LoopForge failure",
                str(error),
                fix="Re-run with `--debug` and report the debug log.",
            )
            if options.debug:
                path = self.api.write_debug_log(error)
                traceback.print_exc(file=context.stderr)
                print(f"debug log: {path}", file=context.stderr)
            self.api.render_cli_error(cli_error, options)
            return 1

    def _handle_early_invocation(
        self,
        argv: list[str],
        context: CliContext,
    ) -> int | None:
        api = context.api
        options = context.options
        if options.version and not argv:
            api.print_version(
                context.project_dir,
                "json" if options.json else "text",
            )
            return 0
        if not argv:
            if (
                context.stdin.isatty()
                and context.stdout.isatty()
                and not options.no_input
            ):
                interactive = importlib.import_module("loopforge.cli.interactive")
                return interactive.run_interactive(context.project_dir)
            if options.no_input:
                raise api.CliUsageError(
                    "LF_INPUT_REQUIRED",
                    "No command was provided",
                    "`--no-input` prevents LoopForge from opening the interactive shell.",
                    fix=(
                        "Run `loopforge help` or pass a command such as "
                        "`loopforge status`."
                    ),
                )
            print(context.parser.format_help(), file=context.stderr, end="")
            return 2
        if options.version:
            api.print_version(
                context.project_dir,
                "json" if options.json else "text",
            )
            return 0
        return None

    def _dispatch(self, args: Any, context: CliContext) -> int:
        for handler in self.handlers:
            result = handler.handle(args, context)
            if result is not None:
                return result
        raise self.api.CliUsageError(
            "LF_USAGE",
            "Unknown command",
            str(args.command),
            fix="Run `loopforge help`.",
        )


def run(api: Any, argv: list[str] | None = None) -> int:
    """Run the CLI with an injected compatibility facade."""

    return LoopForgeCli(api).run(argv)
