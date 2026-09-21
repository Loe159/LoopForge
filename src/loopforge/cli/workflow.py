"""Workflow command handlers for the LoopForge CLI."""

from __future__ import annotations

from typing import Any

from loopforge.cli.context import CliContext


def _is_machine_mode(context: CliContext) -> bool:
    return bool(context.options.json or context.options.quiet)


class RunCommandHandler:
    """Create a run or inspect the active run without prompting."""

    commands = frozenset({"run"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command != "run":
            return None
        return self._handle_run(args, context)

    def _handle_run(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge run",
        )
        machine_mode = _is_machine_mode(context)
        if machine_mode:
            context.renderer.set_machine_mode(True)
        init_result = api.initialize_project(context.project_dir)
        active_status = api.current_status(context.project_dir)
        explicit_source = api.run_has_explicit_source(args)
        previous_current_run_id = (
            str(active_status.run.get("run_id") or "")
            if active_status.run is not None else ""
        )
        if active_status.run is not None and not explicit_source:
            api.render_active_run(
                context.project_dir, context.renderer, fmt=fmt, quiet=options.quiet,
            )
            return 0
        intake = api.noninteractive_run_intake(context.project_dir, args)
        try:
            with context.renderer.loading("Creating LoopForge run..."):
                result = api.create_run(
                    context.project_dir,
                    task=intake.task,
                    pack=args.pack,
                    success_checks=intake.success_checks,
                    selected_skills=args.skill,
                    allowed_tools=intake.allowed_tools,
                    max_attempts=args.max_attempts,
                    timeout_seconds=args.timeout,
                    subjective_rubric=intake.subjective_rubric,
                    source_metadata=intake.source_metadata,
                    initial_approval=intake.initial_approval,
                )
        except (FileNotFoundError, ValueError) as error:
            raise api.CliRuntimeError(
                "LF_RUN_FAILED",
                "LoopForge run failed",
                str(error),
                fix=(
                    "Run `loopforge init` first, then retry "
                    '`loopforge run --task "..."`.'
                ),
            ) from error
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": True,
                    "run_dir": str(result.run_dir),
                    "run": result.run,
                    "previous_current_run_id": previous_current_run_id or None,
                    "replaced_current_run_id": bool(
                        previous_current_run_id
                        and previous_current_run_id != result.run["run_id"]
                    ),
                }
            )
            return 0
        if options.quiet:
            return 0
        RunSummaryPresenter(context).render_created_run(
            result=result,
            init_result=init_result,
            intake=intake,
            previous_current_run_id=previous_current_run_id,
        )
        return 0


class RunSummaryPresenter:
    """Render the result of explicit run creation."""

    def __init__(self, context: CliContext) -> None:
        self.context = context

    def render_created_run(
        self,
        *,
        result: Any,
        init_result: Any,
        intake: Any,
        previous_current_run_id: str,
    ) -> None:
        context = self.context
        api = context.api
        extra: list[str] = []
        if init_result.created:
            extra.extend(
                ["Project", "Initialized LoopForge metadata before creating the run."]
            )
        elif init_result.repaired:
            extra.extend(
                ["Project", "Repaired LoopForge metadata before creating the run."]
            )
        if previous_current_run_id and previous_current_run_id != result.run["run_id"]:
            extra.extend(
                [
                    "Previous current run",
                    (
                        f"Replaced {previous_current_run_id} because a new "
                        "task/source was provided."
                    ),
                ]
            )
        if intake.notes:
            extra.append("Notes")
            extra.extend(str(note) for note in intake.notes)
        if not intake.success_checks:
            extra.extend(
                [
                    "Warning",
                    (
                        "No success check was provided; autonomous attempts may pause "
                        "for contract completion."
                    ),
                ]
            )
        if result.run["loop_contract"]["subjective"] and not intake.subjective_rubric:
            extra.extend(
                [
                    "Rubric",
                    "Subjective work needs a rubric before autonomous attempts.",
                ]
            )
        if intake.success_checks:
            extra.append("Selected checks")
            extra.extend(f"- {check}" for check in intake.success_checks[:5])
        if intake.allowed_tools:
            extra.append("Selected permissions")
            extra.extend(f"- {tool}" for tool in intake.allowed_tools[:5])
        api.render_summary_table(
            context.renderer,
            "Run created",
            [
                ("goal", api.compact_text(result.run["task"], limit=90)),
                ("run", result.run["run_id"]),
                ("pack", result.run["pack"]),
                ("contract", result.run["loop_contract"]["status"]),
                ("stage", result.run.get("current_stage") or "task_draft"),
            ],
            extra_lines=extra,
            next_command=api.next_command(context.project_dir, "loopforge run"),
        )

class ContinueCommandHandler:
    """Validate and execute the implementation transition."""

    commands = frozenset({"continue"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command != "continue":
            return None
        return self._handle_continue(args, context)

    def _handle_continue(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge continue",
        )
        machine_mode = _is_machine_mode(context)
        if machine_mode:
            context.renderer.set_machine_mode(True)
        adapter_args = args.adapter_args
        if adapter_args and adapter_args[0] == "--":
            adapter_args = adapter_args[1:]
        with context.renderer.loading("Continuing LoopForge run..."):
            result = api.continue_run(
                context.project_dir,
                adapter=args.adapter,
                adapter_args=adapter_args,
                implementation_mode=args.execution_mode,
                confirmed=api.confirmation_accepted(args.confirm),
                stream_output=fmt != "json",
            )
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "run_dir": str(result.run_dir) if result.run_dir else None,
                    "contract": result.contract,
                    "run": result.run,
                    "attempt": result.attempt,
                    "blockers": result.blockers,
                }
            )
            return 0 if result.ok else 1
        if options.quiet and result.ok:
            return 0
        api.render_continue_result(
            context.renderer if result.ok else context.error_renderer(),
            result,
            details=args.details,
        )
        return 0 if result.ok else 1


class VerifyCommandHandler:
    """Generate verification evidence for the active run."""

    commands = frozenset({"verify"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command != "verify":
            return None
        return self._handle_verify(args, context)

    def _handle_verify(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge verify",
        )
        machine_mode = _is_machine_mode(context)
        if machine_mode:
            context.renderer.set_machine_mode(True)
        with context.renderer.loading("Generating patch and running verification..."):
            result = api.verify_run(
                context.project_dir,
                confirmed=api.confirmation_accepted(args.confirm),
            )
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "run_dir": str(result.run_dir) if result.run_dir else None,
                    "run": result.run,
                    "verification": result.verification,
                    "blockers": result.blockers,
                }
            )
            return 0 if result.ok else 1
        if options.quiet and result.ok:
            return 0
        api.render_verify_result(
            context.renderer if result.ok else context.error_renderer(),
            result,
            details=args.details,
        )
        return 0 if result.ok else 1


class LearnCommandHandler:
    """Propose or promote durable project memory."""

    commands = frozenset({"learn"})

    def handle(self, args: Any, context: CliContext) -> int | None:
        if args.command != "learn":
            return None
        return self._handle_learn(args, context)

    def _handle_learn(self, args: Any, context: CliContext) -> int:
        api = context.api
        options = context.options
        fmt = api.normalize_format(
            api.output_format(args, options),
            allowed=("text", "json"),
            command="loopforge learn",
        )
        machine_mode = _is_machine_mode(context)
        if machine_mode:
            context.renderer.set_machine_mode(True)
        with context.renderer.loading("Updating LoopForge memory proposals..."):
            result = api.learn_run(
                context.project_dir,
                approve=args.approve,
                notes=args.note,
                confirmed=api.confirmation_accepted(args.confirm),
            )
        if fmt == "json":
            api.print_json_payload(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "run_dir": str(result.run_dir) if result.run_dir else None,
                    "run": result.run,
                    "proposal_path": (
                        str(result.proposal_path) if result.proposal_path else None
                    ),
                    "proposals": result.proposals,
                    "promoted": result.promoted,
                    "rejected": result.rejected,
                    "blockers": result.blockers,
                }
            )
            return 0 if result.ok else 1
        if options.quiet and result.ok:
            return 0
        api.render_learn_result(
            context.renderer if result.ok else context.error_renderer(),
            result,
            approved=args.approve,
        )
        if args.details:
            for proposal in result.proposals[:10]:
                if isinstance(proposal, dict):
                    print(
                        "- "
                        f"{proposal.get('id')}: {proposal.get('status')} "
                        f"{api.compact_text(proposal.get('text'), limit=100)}",
                        file=context.stdout,
                    )
        return 0 if result.ok else 1
