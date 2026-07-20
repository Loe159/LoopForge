"""Interactive shell for LoopForge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TextIO

try:
    from prompt_toolkit.completion import Completer
except ImportError:  # pragma: no cover - exercised only in minimal installs.
    class Completer:  # type: ignore[no-redef]
        pass

from loopforge.engine import (
    DEFAULT_ADAPTER,
    DEFAULT_PROFILE,
    SUPPORTED_ADAPTERS,
    archive_current_run,
    compact_current_context,
    continue_run,
    create_run,
    current_guidance,
    current_status,
    dashboard_snapshot,
    detect_project_pack,
    directory_file_sizes,
    discover_pack_contracts,
    initialize_project,
    list_runs,
    loopforge_home,
    resume_run,
    set_default_adapter,
    update_project_config,
    verify_run,
    learn_run,
    profile_permission_lines,
    approve_plan,
    approve_review,
    approve_initial_task,
    complete_task_definition,
    execute_readonly_stage,
    next_readonly_stage,
    prepare_draft_publication,
    update_user_preferences,
    user_preferences,
)
from loopforge.engine.git_state import DEFAULT_GIT_STATE_SERVICE
from loopforge.cli.actions import ActionDescriptor, action_descriptors, primary_action
from loopforge.cli.ui import (
    TerminalRenderer,
    compact_text,
    format_status_lines,
    render_dashboard,
    render_guidance,
    render_status,
    render_success,
    render_blocked,
    render_summary_table,
    summary_table_lines,
    yes_no,
)


SUPPORTED_COMMANDS = {
    "add-dir": "Add a session-only context directory.",
    "adapter": "Show or select the default adapter for this project.",
    "adapters": "List supported adapters and the selected default.",
    "actions": "List guided actions available for the current state.",
    "allowed-tools": "Show allowed tools from the current loop contract.",
    "approve": "Approve safe memory proposals for the current run.",
    "archive": "Mark the current run as archived without deleting artifacts.",
    "branch": "Show or create a Git branch.",
    "clear": "Clear the visible terminal screen.",
    "commands": "List available interactive commands.",
    "complete-task": "Add objective proof to the current task contract.",
    "compact": "Write a deterministic compact handoff for the current run.",
    "config": "Show or update LoopForge project configuration.",
    "context": "Show LoopForge project and run context.",
    "continue": "Validate the current loop or execute a bounded adapter attempt.",
    "copy": "Copy or export run text such as status, context, compact, or plan.",
    "cost": "Show local cost status without inventing unavailable values.",
    "cd": "Change the session project directory.",
    "code-review": "Summarize local review evidence from diff, risk, and blockers.",
    "dashboard": "Show a read-only dashboard for runs, checks, memory, and actions.",
    "debug-config": "Show LoopForge configuration diagnostics.",
    "diff": "Show current Git working tree status and diff summary.",
    "doctor": "Run local environment diagnostics.",
    "do": "Execute a guided action by id when it is safe or confirmed.",
    "exit": "Exit the interactive shell.",
    "export": "Export status, context, compact, or plan text under run artifacts.",
    "fork": "Create a new run based on the current run's contract defaults.",
    "goal": "Show the current LoopForge run objective.",
    "guide": "Explain the current workflow state and recommended next actions.",
    "help": "Show command help.",
    "init": "Initialize LoopForge metadata for this project.",
    "keymap": "Show or change the session editing mode.",
    "learn": "Propose or approve durable memory updates.",
    "memories": "Show durable and proposed memory state.",
    "memory": "Show durable and proposed memory state.",
    "mention": "Add a session-only file mention to context.",
    "new": "Create a new run.",
    "next": "Show the single best next action.",
    "pack": "List or detect project packs.",
    "permissions": "Show loop permission guidance and allowed tools.",
    "plugins": "List local packs and explain external plugin limits.",
    "plan": "Show the current loop contract and success checks.",
    "ps": "List recorded attempts; LoopForge does not fake live processes.",
    "quit": "Exit the interactive shell.",
    "raw": "Print raw stdout/stderr for a recorded attempt.",
    "recap": "Print a one-line recap of the current run.",
    "report": "Preview or submit a sanitized report to the LoopForge project.",
    "resume": "Switch the current run by run id.",
    "review": "Summarize local review evidence from diff, risk, and blockers.",
    "run": "Create a new run. Plain text input is also treated as /run.",
    "runs": "List known runs for this project.",
    "sandbox": "Show local sandbox/adapter boundary guidance.",
    "security-review": "Summarize local security-relevant evidence.",
    "simplify": "Summarize local cleanup opportunities from diff and blockers.",
    "skills": "List local pack skills.",
    "stats": "Show local run statistics.",
    "status": "Show current LoopForge loop state.",
    "statusline": "Configure the session-only status line.",
    "tasks": "List recorded attempts and next action.",
    "theme": "Set the session theme.",
    "title": "Show or set a session title.",
    "tui": "Set the session renderer mode.",
    "usage": "Show local usage status without inventing unavailable values.",
    "verify": "Generate a patch and run deterministic pack checks.",
    "vim": "Toggle vim-style editing mode for the session.",
    "why": "Explain why LoopForge recommends the next action.",
}


# ``SUPPORTED_COMMANDS`` is the complete local command surface. Discovery uses
# the smaller contextual catalog below, while ``/commands all`` shows it all.
COMMANDS = dict(sorted(SUPPORTED_COMMANDS.items()))
ALIASES = {
    "?": "help",
    "adapters": "adapter",
    "code-review": "review",
    "cost": "stats",
    "memories": "memory",
    "ps": "tasks",
    "q": "exit",
    "quit": "exit",
    "reset": "clear",
    "security-review": "review",
    "simplify": "review",
    "usage": "stats",
    "vim": "keymap",
}

ALIAS_ARGUMENTS = {
    "adapters": "list",
    "memories": "details",
    "vim": "vim",
}

COMMAND_GROUPS = {
    "Projects": ("init", "cd", "dashboard", "pack", "config", "adapter"),
    "Runs": ("run", "new", "fork", "resume", "runs", "archive"),
    "Stages": ("status", "next", "guide", "actions", "do", "complete-task", "plan", "continue", "verify", "review", "learn"),
    "Help": ("report",),
}

ALWAYS_DISCOVERABLE = {"help", "commands", "clear", "exit", "report"}


def contextual_commands(project_dir: Path | None = None) -> dict[str, str]:
    """Return canonical supported commands useful in the current workflow state."""

    visible = set(ALWAYS_DISCOVERABLE)
    if project_dir is None:
        visible.update({"init", "run", "status", "dashboard"})
    else:
        status = current_status(project_dir)
        if not status.initialized:
            visible.update({"init", "status"})
        else:
            visible.update({"dashboard", "runs", "status", "adapter", "config", "pack"})
            if status.run is None:
                visible.update({"run", "new"})
            else:
                visible.update({"actions", "next", "guide", "plan", "review"})
                for action in action_descriptors(current_guidance(project_dir)):
                    command = {
                        "complete-task": "complete-task",
                        "run-readonly-stage": "continue",
                        "continue": "continue",
                        "retry-attempt": "continue",
                        "verify": "verify",
                        "approve-plan": "approve",
                        "approve-review": "approve",
                    }.get(action.id)
                    if command:
                        visible.add(command)
    return {
        command: SUPPORTED_COMMANDS[command]
        for command in sorted(visible)
        if command in SUPPORTED_COMMANDS
    }


@dataclass(frozen=True)
class DispatchResult:
    exit_code: int
    should_exit: bool = False


def tui_dependency_state() -> dict[str, bool]:
    return {
        "prompt_toolkit": importlib.util.find_spec("prompt_toolkit") is not None,
        "rich": importlib.util.find_spec("rich") is not None,
        # Discovery only: keep Textual unimported for every headless command.
        "textual": importlib.util.find_spec("textual") is not None,
    }


def interactive_ui_enabled(*, requested: bool = False) -> bool:
    """Return whether the full-screen console is the interactive default.

    ``requested`` remains accepted for callers that used the former opt-in
    flag.  Interactive TTY sessions now always open the console; ``--plain``
    selects the prompt-based compatibility surface instead.
    """

    return True


def available_commands() -> dict[str, str]:
    """Return the complete explicit compatibility catalog.

    Ordinary completion and ``/commands`` use :func:`contextual_commands`.
    """

    return COMMANDS.copy()


class SlashCommandCompleter(Completer):
    def __init__(
        self,
        commands: dict[str, str] | None = None,
        *,
        project_dir: Path | None = None,
    ) -> None:
        self.commands = commands if commands is not None else contextual_commands(project_dir)

    def get_completions(self, document, complete_event):  # type: ignore[no-untyped-def]
        from prompt_toolkit.completion import Completion

        word = document.get_word_before_cursor(WORD=True)
        if not word.startswith("/"):
            return
        needle = word[1:]
        for command in self.commands:
            if command.startswith(needle):
                yield Completion(
                    f"/{command}",
                    start_position=-len(word),
                    display_meta=self.commands[command],
                )


class InteractiveShell:
    def __init__(
        self,
        project_dir: Path,
        *,
        output: TextIO | None = None,
        error: TextIO | None = None,
        allow_confirmation: bool = True,
        renderer_mode: str = "auto",
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.output = output or sys.stdout
        self.error = error or sys.stderr
        self.running = True
        self.allow_confirmation = allow_confirmation
        preferences = user_preferences()
        self.statusline = preferences["statusline"]
        self.theme = preferences["theme"]
        self.renderer_mode = renderer_mode
        self.renderer = TerminalRenderer(self.output, mode=self.renderer_mode, theme=self.theme)
        self.extra_context_dirs: list[Path] = []
        self.mentioned_paths: list[Path] = []
        self.editing_mode = preferences["keymap"]
        self.session_title = "LoopForge"
        status = current_status(self.project_dir)
        config = status.config or {}
        adapter = str(config.get("default_adapter") or DEFAULT_ADAPTER)
        self.selected_adapter = adapter if adapter in SUPPORTED_ADAPTERS else DEFAULT_ADAPTER
        raw_args = config.get("default_adapter_args", [])
        if isinstance(raw_args, list):
            self.selected_adapter_args = [str(value) for value in raw_args]
        else:
            self.selected_adapter_args = []
        self._git_state = DEFAULT_GIT_STATE_SERVICE.get(self.project_dir)

    def write(self, message: str = "", *, error: bool = False) -> None:
        stream = self.error if error else self.output
        print(message, file=stream)

    def dispatch(self, raw_line: str) -> DispatchResult:
        line = raw_line.strip()
        if not line:
            return DispatchResult(0)

        command, args, implicit_run = self.parse_line(line)
        command, args = self.canonical_command(command, args)
        if implicit_run:
            return self.cmd_run(args)
        handler = getattr(self, f"cmd_{command.replace('-', '_')}", None)
        if handler is None:
            self.write(f"Unknown command: /{command}", error=True)
            self.write("Run /commands to see available commands.", error=True)
            return DispatchResult(2)
        return handler(args)

    def parse_line(self, line: str) -> tuple[str, str, bool]:
        if line.startswith("/"):
            body = line[1:].strip()
            if not body:
                return "commands", "", False
            command, _, args = body.partition(" ")
            return command.lower(), args.strip(), False

        command, _, args = line.partition(" ")
        lowered = command.lower()
        if lowered in COMMANDS:
            return lowered, args.strip(), False
        return "run", line, True

    @staticmethod
    def canonical_command(command: str, args: str) -> tuple[str, str]:
        canonical = ALIASES.get(command, command)
        default_args = ALIAS_ARGUMENTS.get(command, "")
        if default_args:
            args = f"{default_args} {args}".strip()
        return canonical, args

    def persist_user_preference(self, key: str, value: str) -> None:
        update_user_preferences({key: value})

    def split_args(self, raw: str) -> list[str] | None:
        try:
            if os.name != "nt":
                return shlex.split(raw)
            marker = "__LOOPFORGE_WINDOWS_BACKSLASH__"

            def protect_quoted_path(match: re.Match[str]) -> str:
                quote, path = match.group(1), match.group(2)
                return quote + path.replace("\\", marker) + quote

            protected = re.sub(
                r"(['\"])([A-Za-z]:\\.*?)(?:\1)",
                protect_quoted_path,
                raw,
            )
            protected = re.sub(
                r"(?<!\S)([A-Za-z]:\\\S+)",
                lambda match: match.group(1).replace("\\", marker),
                protected,
            )
            return [value.replace(marker, "\\") for value in shlex.split(protected)]
        except ValueError as error:
            self.write(f"Could not parse arguments: {error}", error=True)
            return None

    def confirm_if_available(self, prompt: str) -> bool:
        if not self.allow_confirmation:
            return False
        answer = input(f"{prompt} Type yes to continue: ")
        return answer.strip().lower() == "yes"

    def refresh_session_config(self) -> None:
        status = current_status(self.project_dir)
        if status.config is None:
            self.selected_adapter = DEFAULT_ADAPTER
            self.selected_adapter_args = []
            return
        adapter = str(status.config.get("default_adapter") or DEFAULT_ADAPTER)
        self.selected_adapter = adapter if adapter in SUPPORTED_ADAPTERS else DEFAULT_ADAPTER
        raw_args = status.config.get("default_adapter_args", [])
        self.selected_adapter_args = [
            str(value) for value in raw_args
        ] if isinstance(raw_args, list) else []
        self._git_state = DEFAULT_GIT_STATE_SERVICE.get(self.project_dir)

    def write_table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        self.renderer.table(title, columns, rows)

    def write_panel(self, title: str, lines: list[str]) -> None:
        self.renderer.panel(title, lines)

    def action_descriptors(self) -> tuple[ActionDescriptor, ...]:
        return action_descriptors(current_guidance(self.project_dir))

    def next_action(self) -> ActionDescriptor | None:
        return primary_action(current_guidance(self.project_dir))

    def write_home(self) -> None:
        status = current_status(self.project_dir)
        action = self.next_action()
        run_text = "none"
        if status.run is not None:
            run_text = f"{status.run.get('run_id')} {status.run.get('status')}"
        lines = summary_table_lines(
            [
                ("project", status.project_dir.name),
                ("run", run_text),
                ("adapter", self.selected_adapter),
                ("status", status.run.get("status") if status.run is not None else "not initialized" if not status.initialized else "ready_for_run"),
            ]
        )
        lines.extend(["", "Next", f"/do {action.id}" if action is not None else "/status"])
        self.write_panel("LoopForge shell", lines)

    def prompt_text(self) -> str:
        status = current_status(self.project_dir)
        value = "blocked" if status.blockers else "ready"
        if status.run is not None:
            value = str(status.run.get("status") or value)
        elif not status.initialized:
            value = "not_initialized"
        return f"loopforge {value} > "

    def guidance_lines(self) -> list[str]:
        guidance = current_guidance(self.project_dir)
        action = self.next_action()
        lines = [
            f"now: {guidance.summary}",
            f"state: {guidance.state}",
            f"priority: {guidance.priority}",
        ]
        if guidance.blocked_reasons:
            lines.append("problem:")
            lines.extend(f"- {reason}" for reason in guidance.blocked_reasons)
        if guidance.diagnostics:
            lines.append("diagnostics:")
            lines.extend(f"- {diagnostic}" for diagnostic in guidance.diagnostics)
        if action is not None:
            lines.extend(
                [
                    "recommended next action:",
                    f"[{action.id}] {action.label}",
                    f"command: {action.command_fallback}",
                    f"why: {action.description}",
                ]
            )
        return lines

    def write_guidance(self, *, concise: bool = False) -> None:
        guidance = current_guidance(self.project_dir)
        action = self.next_action()
        if concise:
            lines = [f"now: {guidance.summary}"]
            if action is not None:
                lines.append(f"next: [{action.id}] {action.command_fallback}")
                lines.append(f"why: {action.description}")
            self.write_panel("LoopForge guidance", lines)
            return
        self.write_panel("LoopForge guidance", self.guidance_lines())
        if guidance.recommended_actions:
            self.write_actions(self.action_descriptors())

    def write_actions(self, actions: tuple[ActionDescriptor, ...]) -> None:
        rows = [
            [
                action.id,
                action.risk,
                "yes" if action.requires_confirmation else "no",
                action.command_fallback,
                action.description,
            ]
            for action in actions
        ]
        self.write_table("Guided actions", ["ID", "Risk", "Confirm", "Command", "Why"], rows)

    def guidance_action(self, action_id: str) -> ActionDescriptor | None:
        for action in self.action_descriptors():
            if action.id == action_id:
                return action
        return None

    def execute_guided_action(
        self,
        action: ActionDescriptor,
        *,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        """Execute one engine-derived action through its shell adapter."""

        key = action.executor_key
        if key == "initialize":
            return self.cmd_init("")
        if key == "collect-task":
            self.write("This action needs a real task. Use /run <task>.", error=True)
            return DispatchResult(2)
        if key == "complete-task":
            self.write("Add objective proof with /complete-task <success check>.", error=True)
            return DispatchResult(2)
        if key == "run-readonly-stage":
            return self.execute_readonly_guided_stage(
                operation_callback=operation_callback,
                cancel_event=cancel_event,
            )
        if key == "approve-task":
            return self.execute_initial_task_approval()
        if key == "approve-plan":
            return self.execute_approval("plan")
        if key == "approve-review":
            return self.execute_approval("review")
        if key == "prepare-draft":
            return self.execute_draft_preparation()
        if key == "continue":
            return self._continue_with_adapter(
                self.selected_adapter,
                list(self.selected_adapter_args),
                confirmed=True,
                operation_callback=operation_callback,
                cancel_event=cancel_event,
            )
        if key == "verify":
            return self.cmd_verify(
                "--confirm",
                operation_callback=operation_callback,
                cancel_event=cancel_event,
            )
        if key == "adapter":
            self.write("Choose an adapter with /adapter <name>.", error=True)
            return DispatchResult(2)
        if key == "status":
            return self.cmd_status("")
        self.write(f"Cannot execute guided action yet: {action.command_fallback}", error=True)
        return DispatchResult(2)

    def execute_readonly_guided_stage(
        self,
        *,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        status = current_status(self.project_dir)
        if status.run is None:
            self.write("No current run is ready for a read-only stage.", error=True)
            return DispatchResult(1)
        stage = next_readonly_stage(status.run)
        if stage is None:
            self.write("No read-only stage is currently eligible.", error=True)
            return DispatchResult(1)
        with self.renderer.loading(f"Running read-only {stage} with {self.selected_adapter}..."):
            result = execute_readonly_stage(
                self.project_dir,
                stage=stage,
                adapter=self.selected_adapter,
                adapter_args=self.selected_adapter_args,
                operation_callback=operation_callback,
                cancel_event=cancel_event,
            )
        if result.ok:
            render_success(
                self.renderer,
                f"{stage.title()} ready",
                [("status", result.message), ("artifact", result.artifact_path or "none")],
                next_command="/status",
            )
        else:
            render_blocked(
                self.renderer,
                f"{stage.title()} blocked",
                [("status", result.message)],
                blockers=result.blockers,
                next_command="/status",
            )
        return DispatchResult(0 if result.ok else 1)

    def execute_initial_task_approval(self) -> DispatchResult:
        result = approve_initial_task(self.project_dir, source="interactive")
        if result.ok:
            render_success(
                self.renderer,
                "Task approved",
                [("status", result.message), ("artifact", result.artifact_path or "none")],
                next_command="/status",
            )
        else:
            render_blocked(
                self.renderer,
                "Task approval blocked",
                [("status", result.message)],
                blockers=result.blockers,
                next_command="/status",
            )
        return DispatchResult(0 if result.ok else 1)

    def complete_current_task_definition(self, success_check: str) -> DispatchResult:
        """Complete the selected run's task contract through the engine facade."""

        result = complete_task_definition(self.project_dir, success_check=success_check)
        rows = [("status", result.message), ("artifact", result.artifact_path or "none")]
        if result.ok:
            render_success(
                self.renderer,
                "Task contract complete",
                rows,
                next_command="/do approve-task",
            )
        else:
            render_blocked(
                self.renderer,
                "Task completion blocked",
                rows,
                blockers=result.blockers,
                next_command="/status",
            )
        return DispatchResult(0 if result.ok else 1)

    def cmd_complete_task(self, raw: str) -> DispatchResult:
        success_check = raw.strip()
        if not success_check:
            self.write("usage: /complete-task <objective success check>", error=True)
            return DispatchResult(2)
        return self.complete_current_task_definition(success_check)

    def execute_approval(self, stage: str) -> DispatchResult:
        result = (
            approve_plan(self.project_dir, source="interactive")
            if stage == "plan"
            else approve_review(self.project_dir, source="interactive")
        )
        if result.ok:
            render_success(
                self.renderer,
                f"{stage.title()} approved",
                [("status", result.message), ("artifact", result.artifact_path or "none")],
                next_command="/status",
            )
        else:
            render_blocked(
                self.renderer,
                f"{stage.title()} approval blocked",
                [("status", result.message)],
                blockers=result.blockers,
                next_command="/status",
            )
        return DispatchResult(0 if result.ok else 1)

    def execute_draft_preparation(self) -> DispatchResult:
        result = prepare_draft_publication(self.project_dir)
        if result.ok:
            render_success(
                self.renderer,
                "Draft publication prepared",
                [("status", result.message), ("artifact", result.artifact_path or "none")],
                next_command="/status",
            )
        else:
            render_blocked(
                self.renderer,
                "Draft publication blocked",
                [("status", result.message)],
                blockers=result.blockers,
                next_command="/status",
            )
        return DispatchResult(0 if result.ok else 1)

    def status_lines(self, *, details: bool = False) -> list[str]:
        result = current_status(self.project_dir)
        guidance = current_guidance(self.project_dir)
        return format_status_lines(result, guidance, details=details)

    def context_lines(self) -> list[str]:
        result = current_status(self.project_dir)
        lines = [
            "LoopForge context",
            f"project: {result.project_dir}",
            f"initialized: {result.initialized}",
            f"selected adapter: {self.selected_adapter}",
            "selected adapter args: " + " ".join(self.selected_adapter_args),
        ]
        if result.config is not None:
            lines.extend(
                [
                    f"profile: {result.config.get('profile')}",
                    *profile_permission_lines(result.config.get("profile")),
                    f"run root: {result.config.get('run_root')}",
                ]
            )
        if result.run is not None and result.run_dir is not None:
            sizes = directory_file_sizes(result.run_dir)
            lines.extend(
                [
                    f"current run: {result.run.get('run_id')}",
                    f"task: {result.run.get('task')}",
                    f"status: {result.run.get('status')}",
                    f"pack: {result.run.get('pack')}",
                    f"run files: {len(sizes)}",
                    f"run bytes: {sum(size for _, size in sizes)}",
                ]
            )
        if self.extra_context_dirs:
            lines.append("session context dirs:")
            lines.extend(f"- {path}" for path in self.extra_context_dirs)
        if self.mentioned_paths:
            lines.append("session mentions:")
            lines.extend(f"- {path}" for path in self.mentioned_paths)
        if result.memory is not None:
            lines.append(f"durable memory items: {result.memory.get('durable_items', 0)}")
            lines.append(f"pending memory proposals: {result.memory.get('pending', 0)}")
        lines.append("blockers:")
        if result.blockers:
            lines.extend(f"- {blocker}" for blocker in result.blockers)
        else:
            lines.append("- none")
        lines.append(f"next step: {result.next_step}")
        return lines

    def current_run_attempts(self) -> list[dict[str, object]]:
        status = current_status(self.project_dir)
        if status.run is None:
            return []
        raw_attempts = status.run.get("attempts", [])
        return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]

    def attempt_by_label(self, label: str) -> dict[str, object] | None:
        attempts = self.current_run_attempts()
        if not attempts:
            return None
        if label in {"", "latest", "last"}:
            return attempts[-1]
        for attempt in attempts:
            if label in {str(attempt.get("id")), str(attempt.get("number"))}:
                return attempt
        return None

    def export_dir(self) -> Path | None:
        status = current_status(self.project_dir)
        if status.run_dir is None:
            return None
        target = status.run_dir / "artifacts" / "exports"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def text_for_target(self, target: str) -> tuple[str | None, str | None]:
        target = (target or "status").strip().lower()
        status = current_status(self.project_dir)
        if target == "status":
            return "\n".join(self.status_lines()) + "\n", None
        if target == "context":
            return "\n".join(self.context_lines()) + "\n", None
        if target == "compact":
            result = compact_current_context(self.project_dir)
            if not result.ok:
                return None, "; ".join(result.blockers)
            return result.summary, None
        if target == "plan":
            if status.run_dir is None:
                return None, status.next_step
            path = status.run_dir / "loop.md"
            return path.read_text(encoding="utf-8"), None
        return None, f"unknown text target: {target}"

    def write_export(self, target: str) -> tuple[Path | None, str | None]:
        text, error = self.text_for_target(target)
        if error is not None or text is None:
            return None, error
        directory = self.export_dir()
        if directory is None:
            return None, "no current run is available for exports"
        path = directory / f"{target or 'status'}.txt"
        path.write_text(text, encoding="utf-8")
        return path, None

    def copy_to_clipboard(self, text: str) -> bool:
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["clip"],
                    input=text,
                    text=True,
                    check=True,
                    capture_output=True,
                )
                return True
            except (OSError, subprocess.CalledProcessError):
                return False
        for command in ("pbcopy", "xclip", "xsel"):
            if shutil.which(command):
                args = [command]
                if command == "xclip":
                    args.extend(["-selection", "clipboard"])
                if command == "xsel":
                    args.append("--clipboard")
                try:
                    subprocess.run(args, input=text, text=True, check=True, capture_output=True)
                    return True
                except (OSError, subprocess.CalledProcessError):
                    return False
        return False

    def cmd_help(self, raw: str) -> DispatchResult:
        command = raw.strip().lstrip("/")
        if command:
            command, _ = self.canonical_command(command, "")
            if command in COMMANDS:
                self.write(f"/{command}: {COMMANDS[command]}")
                return DispatchResult(0)
            self.write(f"Unknown command: /{command}", error=True)
            return DispatchResult(2)
        self.write("LoopForge follows Projects → Runs → Stages.")
        self.write("Projects: choose or configure a repository with /dashboard, /runs, or /pack.")
        self.write("Runs: create or resume work with /run, /new, or /resume.")
        self.write("Stages: inspect the current gate with /status, then use /next or /actions.")
        self.write("Use /commands for actions useful now; /commands all is the expert catalog.")
        return DispatchResult(0)

    def cmd_report(self, raw: str = "") -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/report", add_help=False)
        parser.add_argument("--kind", choices=("bug", "feature", "optimization"), default="bug")
        parser.add_argument("--title", required=True)
        parser.add_argument("--description", required=True)
        parser.add_argument("--expected", default="")
        parser.add_argument("--actual", default="")
        parser.add_argument("--include-context", action="store_true")
        parser.add_argument("--submit", action="store_true")
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            self.write(
                "usage: /report --title <title> --description <text> "
                "[--kind bug|feature|optimization] [--include-context] [--submit]",
                error=True,
            )
            return DispatchResult(2)
        from loopforge.cli import build_project_report, create_project_report

        preview = build_project_report(
            self.project_dir,
            kind=args.kind,
            title=args.title,
            description=args.description,
            expected=args.expected,
            actual=args.actual,
            include_context=args.include_context,
            screen="shell",
        )
        result = create_project_report(preview) if args.submit else preview
        if not result.ok:
            self.write(f"report was not submitted: {result.reason}", error=True)
            return DispatchResult(1)
        if result.submitted:
            render_success(
                self.renderer,
                "LoopForge report submitted",
                [("repository", result.repository), ("issue", result.url), ("redactions", result.redactions)],
            )
            return DispatchResult(0)
        self.write_panel(
            "LoopForge report preview",
            [f"repository: {result.repository}", f"redactions: {result.redactions}", "", result.body],
        )
        self.write("Review the preview, then rerun with --submit to create the issue.")
        return DispatchResult(0)

    def cmd_commands(self, raw: str = "") -> DispatchResult:
        show_all = raw.strip().lower() == "all"
        if show_all:
            rows = [[f"/{command}", description] for command, description in COMMANDS.items()]
            self.write_table("LoopForge commands", ["Command", "Description"], rows)
            return DispatchResult(0)

        available = contextual_commands(self.project_dir)
        shown: set[str] = set()
        for group, commands in COMMAND_GROUPS.items():
            rows = []
            for command in commands:
                if command in available:
                    shown.add(command)
                    rows.append([f"/{command}", SUPPORTED_COMMANDS[command]])
            if rows:
                self.write_table(group, ["Command", "Use"], rows)
        remaining = sorted(set(available) - shown)
        if remaining:
            rows = [[f"/{command}", SUPPORTED_COMMANDS[command]] for command in remaining]
            self.write_table("More", ["Command", "Use"], rows)
        self.write("Use /commands all for the complete command catalog.")
        return DispatchResult(0)

    def cmd_adapters(self, raw: str = "") -> DispatchResult:
        del raw
        rows = []
        for adapter in SUPPORTED_ADAPTERS:
            selected = "*" if adapter == self.selected_adapter else ""
            rows.append([selected, adapter, " ".join(self.selected_adapter_args) if adapter == self.selected_adapter else ""])
        self.write_table("Adapters", ["", "Adapter", "Default args"], rows)
        return DispatchResult(0)

    def cmd_adapter(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        if tokens and tokens[0] == "list":
            rows = []
            for adapter in SUPPORTED_ADAPTERS:
                selected = "*" if adapter == self.selected_adapter else ""
                rows.append([selected, adapter, " ".join(self.selected_adapter_args) if adapter == self.selected_adapter else ""])
            self.write_table("Adapters", ["", "Adapter", "Default args"], rows)
            return DispatchResult(0)
        if not tokens:
            render_summary_table(
                self.renderer,
                "Adapter",
                [
                    ("current", self.selected_adapter),
                    ("args", " ".join(self.selected_adapter_args) or "none"),
                ],
                next_command="/adapter local-adapter-fixture -- python script.py",
            )
            return DispatchResult(0)
        adapter = tokens[0]
        if adapter not in SUPPORTED_ADAPTERS:
            self.write(f"unsupported adapter: {adapter}", error=True)
            self.write(f"supported adapters: {', '.join(SUPPORTED_ADAPTERS)}", error=True)
            return DispatchResult(2)
        adapter_args: list[str] | None = None
        if len(tokens) > 1:
            if tokens[1] != "--":
                self.write("usage: /adapter <name> [-- <default adapter args...>]", error=True)
                return DispatchResult(2)
            adapter_args = tokens[2:]
        result = set_default_adapter(self.project_dir, adapter, adapter_args)
        self.write("Adapter set" if result.ok else result.message, error=not result.ok)
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
            return DispatchResult(1)
        self.refresh_session_config()
        self.write(f"current  {self.selected_adapter}")
        self.write(f"args     {' '.join(self.selected_adapter_args) or 'none'}")
        return DispatchResult(0)

    def cmd_init(self, raw: str) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/init", add_help=False)
        parser.add_argument(
            "--profile",
            default=DEFAULT_PROFILE,
            choices=("assist", "supervised", "autonomous", "strict"),
        )
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            return DispatchResult(2)
        result = initialize_project(self.project_dir, profile=args.profile)
        if result.created:
            action = "initialized"
        elif result.repaired:
            action = "repaired"
        else:
            action = "already initialized"
        title = (
            "LoopForge project ready"
            if result.created
            else "Project repaired"
            if result.repaired
            else "Project already ready"
        )
        render_success(
            self.renderer,
            title,
            [
                ("project", result.config["project_name"]),
                ("profile", result.config["profile"]),
                ("runs", result.config["run_root"]),
            ],
            next_command='/run --task "Describe the task"',
        )
        return DispatchResult(0)

    def cmd_run(self, raw: str) -> DispatchResult:
        task = raw.strip()
        pack = None
        success_checks: list[str] = []
        selected_skills: list[str] = []
        allowed_tools: list[str] = []
        max_attempts = 3
        timeout_seconds = 1800
        rubric = ""
        if raw.strip().startswith("--"):
            parser = argparse.ArgumentParser(prog="/run", add_help=False)
            parser.add_argument("--task", required=True)
            parser.add_argument("--pack")
            parser.add_argument("--success-check", action="append", default=[])
            parser.add_argument("--skill", action="append", default=[])
            parser.add_argument("--allow-tool", action="append", default=[])
            parser.add_argument("--max-attempts", type=int, default=3)
            parser.add_argument("--timeout", type=int, default=1800)
            parser.add_argument("--rubric", default="")
            tokens = self.split_args(raw)
            if tokens is None:
                return DispatchResult(2)
            try:
                args = parser.parse_args(tokens)
            except SystemExit:
                return DispatchResult(2)
            task = args.task
            pack = args.pack
            success_checks = args.success_check
            selected_skills = args.skill
            allowed_tools = args.allow_tool
            max_attempts = args.max_attempts
            timeout_seconds = args.timeout
            rubric = args.rubric
        if not task:
            self.write("Usage: /run <task> or /run --task \"...\"", error=True)
            return DispatchResult(2)
        try:
            with self.renderer.loading("Creating LoopForge run..."):
                result = create_run(
                    self.project_dir,
                    task=task,
                    pack=pack,
                    success_checks=success_checks,
                    selected_skills=selected_skills,
                    allowed_tools=allowed_tools,
                    max_attempts=max_attempts,
                    timeout_seconds=timeout_seconds,
                    subjective_rubric=rubric,
                )
        except (FileNotFoundError, ValueError) as error:
            self.write(f"LoopForge run failed: {error}", error=True)
            return DispatchResult(1)
        render_success(
            self.renderer,
            "Run created",
            [
                ("goal", compact_text(result.run["task"], limit=90)),
                ("run", result.run["run_id"]),
                ("pack", result.run["pack"]),
                ("contract", result.run["loop_contract"]["status"]),
            ],
            next_command="/continue",
        )
        return DispatchResult(0)

    def cmd_status(self, raw: str = "") -> DispatchResult:
        details = raw.strip().lower() == "details"
        if raw.strip() and not details:
            self.write("usage: /status [details]", error=True)
            return DispatchResult(2)
        result = current_status(self.project_dir)
        guidance = current_guidance(self.project_dir)
        render_status(self.renderer, result, guidance, details=details)
        return DispatchResult(0)

    def cmd_dashboard(self, raw: str = "") -> DispatchResult:
        details = raw.strip().lower() == "details"
        result = dashboard_snapshot(self.project_dir)
        render_dashboard(self.renderer, result.snapshot, details=details)
        return DispatchResult(0)

    def cmd_continue(
        self,
        raw: str,
        *,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/continue", add_help=False)
        parser.add_argument("--adapter", choices=SUPPORTED_ADAPTERS)
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("adapter_args", nargs=argparse.REMAINDER)
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            return DispatchResult(2)
        adapter_args = args.adapter_args
        if adapter_args and adapter_args[0] == "--":
            adapter_args = adapter_args[1:]
        adapter = None if args.check else args.adapter or self.selected_adapter
        if adapter is None:
            chosen_args = []
        elif args.adapter is None and not adapter_args:
            chosen_args = list(self.selected_adapter_args)
        else:
            chosen_args = adapter_args
        if adapter is not None:
            self.write(f"adapter: {adapter}")
            self.write("adapter args: " + " ".join(chosen_args))
        confirmed = args.confirm
        if adapter is not None and not confirmed:
            status = current_status(self.project_dir)
            profile = status.run.get("profile") if status.run is not None else None
            if profile == "strict":
                confirmed = self.confirm_if_available("Strict profile requires confirmation.")
        return self._continue_with_adapter(
            adapter,
            chosen_args,
            confirmed=confirmed,
            operation_callback=operation_callback,
            cancel_event=cancel_event,
        )

    def _continue_with_adapter(
        self,
        adapter: str | None,
        adapter_args: list[str],
        *,
        confirmed: bool,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        with self.renderer.loading("Continuing LoopForge run..."):
            result = continue_run(
                self.project_dir,
                adapter=adapter,
                adapter_args=adapter_args,
                confirmed=confirmed,
                operation_callback=operation_callback,
                cancel_event=cancel_event,
                stream_output=operation_callback is None,
            )
        rows: list[tuple[str, object]] = []
        if result.attempt is not None:
            rows.extend(
                [
                    ("attempt", result.attempt["id"]),
                    ("adapter", result.attempt["adapter"]),
                    ("changed", yes_no(result.attempt.get("workspace_changed"))),
                    ("status", result.attempt["status"]),
                ]
            )
        elif result.contract is not None:
            rows.extend(
                [
                    ("contract", result.contract.get("status")),
                    ("checks", len(result.contract.get("success_checks", []))),
                    ("adapter", "not executed"),
                ]
            )
        else:
            rows.append(("status", result.message))
        next_value = "/verify" if result.ok else "/raw latest stderr"
        if result.ok:
            render_success(self.renderer, "Attempt completed", rows, next_command=next_value)
        else:
            render_blocked(
                self.renderer,
                "Attempt blocked",
                rows,
                blockers=result.blockers,
                next_command=next_value,
            )
        return DispatchResult(0 if result.ok else 1)

    def cmd_verify(
        self,
        raw: str = "",
        *,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/verify", add_help=False)
        parser.add_argument("--confirm", action="store_true")
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            return DispatchResult(2)
        confirmed = args.confirm
        if not confirmed:
            status = current_status(self.project_dir)
            profile = status.run.get("profile") if status.run is not None else None
            if profile == "strict":
                confirmed = self.confirm_if_available("Strict profile requires confirmation.")
        with self.renderer.loading("Generating patch and running verification..."):
            result = verify_run(
                self.project_dir,
                confirmed=confirmed,
                operation_callback=operation_callback,
                cancel_event=cancel_event,
            )
        rows: list[tuple[str, object]] = [("status", "passed" if result.ok else "failed")]
        if result.verification is not None:
            patch = result.verification.get("patch", {})
            risk = result.verification.get("risk", {})
            if isinstance(patch, dict):
                rows.append(("patch", patch.get("path") or "none"))
            if isinstance(risk, dict):
                rows.append(("risk", risk.get("risk") or "unknown"))
            rows.append(
                (
                    "checks",
                    f"{result.verification.get('checks_passed', 0)}/"
                    f"{result.verification.get('checks_total', 0)} passed",
                )
            )
        if result.ok:
            render_success(self.renderer, "Verified", rows, next_command="/learn")
        else:
            render_blocked(
                self.renderer,
                "Verification failed",
                rows,
                blockers=result.blockers,
                next_command="/diff",
            )
        return DispatchResult(0 if result.ok else 1)

    def cmd_learn(self, raw: str) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/learn", add_help=False)
        parser.add_argument("--approve", action="store_true")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--note", action="append", default=[])
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            return DispatchResult(2)
        confirmed = args.confirm
        if args.approve and not confirmed:
            status = current_status(self.project_dir)
            profile = status.run.get("profile") if status.run is not None else None
            if profile == "strict":
                confirmed = self.confirm_if_available("Strict profile requires confirmation.")
        with self.renderer.loading("Updating LoopForge memory proposals..."):
            result = learn_run(
                self.project_dir,
                approve=args.approve,
                notes=args.note,
                confirmed=confirmed,
            )
        pending = sum(
            1
            for proposal in result.proposals
            if isinstance(proposal, dict) and proposal.get("status") == "pending"
        )
        rows: list[tuple[str, object]] = [
            ("pending", pending),
            ("promoted", len(result.promoted)),
            ("rejected", len(result.rejected)),
        ]
        if result.proposal_path is not None:
            rows.append(("file", result.proposal_path))
        if result.ok:
            render_success(
                self.renderer,
                "Memory promoted" if args.approve else "Memory proposals ready",
                rows,
                next_command="/approve" if pending else "/status",
            )
        else:
            render_blocked(
                self.renderer,
                "Memory blocked",
                rows,
                blockers=result.blockers,
                next_command="/memory",
            )
        return DispatchResult(0 if result.ok else 1)

    def cmd_pack(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        if tokens == ["list"]:
            packs = discover_pack_contracts(self.project_dir)
            if not packs:
                self.write("No project packs found.")
                return DispatchResult(0)
            detected = detect_project_pack(self.project_dir)
            rows = []
            for pack in packs:
                marker = "*" if pack.get("name") == detected.get("name") else ""
                source = Path(str(pack.get("source") or ""))
                kind = "local override" if str(source).startswith(str(self.project_dir)) else "bundled"
                rows.append(
                    [
                        marker,
                        str(pack.get("name") or ""),
                        compact_text(pack.get("description"), limit=42),
                        kind,
                    ]
                )
            self.write_table("Project packs", ["", "Pack", "Description", "Kind"], rows)
            return DispatchResult(0)
        if tokens == ["detect"]:
            pack = detect_project_pack(self.project_dir)
            render_success(
                self.renderer,
                "Detected pack",
                [
                    ("pack", pack["name"]),
                    ("score", pack.get("detection_score", 0)),
                    ("source", pack.get("source") or "none"),
                ],
                next_command=f'/run --pack {pack["name"]} --task "Describe the task"',
            )
            return DispatchResult(0)
        self.write("Usage: /pack list|detect", error=True)
        return DispatchResult(2)

    def cmd_context(self, raw: str = "") -> DispatchResult:
        del raw
        self.write_panel("LoopForge context", self.context_lines())
        return DispatchResult(0)

    def cmd_compact(self, raw: str = "") -> DispatchResult:
        result = compact_current_context(self.project_dir, focus=raw)
        self.write(result.message, error=not result.ok)
        if result.path is not None:
            self.write(f"compact path: {result.path}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        return DispatchResult(0 if result.ok else 1)

    def cmd_recap(self, raw: str = "") -> DispatchResult:
        del raw
        result = current_status(self.project_dir)
        if result.run is None:
            self.write(f"recap: no active run. next: {result.next_step}")
            return DispatchResult(0)
        self.write(
            "recap: "
            f"{result.run.get('task')} "
            f"[{result.run.get('status')}]. "
            f"next: {result.next_step}"
        )
        return DispatchResult(0)

    def cmd_diff(self, raw: str = "") -> DispatchResult:
        del raw
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.project_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if status.returncode != 0:
            self.write("Git status is unavailable in this directory.")
            return DispatchResult(0)
        self.write("git status:")
        self.write(status.stdout.strip() or "clean")
        diff = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=self.project_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if diff.stdout.strip():
            self.write("git diff --stat:")
            self.write(diff.stdout.rstrip())
        return DispatchResult(0)

    def cmd_runs(self, raw: str = "") -> DispatchResult:
        del raw
        result = list_runs(self.project_dir)
        if not result.initialized:
            self.write("LoopForge is not initialized.")
            for blocker in result.blockers:
                self.write(f"- {blocker}")
            return DispatchResult(1)
        if not result.runs:
            self.write("No runs yet")
            self.write('Next\n/run --task "Describe the task"')
            return DispatchResult(0)
        latest = result.runs[0]
        self.write_panel(
            "Runs",
            summary_table_lines(
                [
                    ("total", len(result.runs)),
                    ("current", result.current_run_id or "none"),
                    ("latest", latest.get("status") or "unknown"),
                ]
            ),
        )
        rows = []
        for run in result.runs:
            marker = "*" if run.get("current") else "-"
            task = str(run.get("task") or "").replace("\n", " ")
            rows.append(
                [
                    marker,
                    str(run.get("run_id") or ""),
                    str(run.get("status") or "unknown"),
                    compact_text(task, limit=54),
                ]
            )
        self.write_table("Run", ["", "Run", "Status", "Task"], rows)
        return DispatchResult(0)

    def cmd_resume(self, raw: str) -> DispatchResult:
        run_id = raw.strip()
        if not run_id:
            return self.cmd_runs("")
        result = resume_run(self.project_dir, run_id)
        self.write(result.message, error=not result.ok)
        if result.run_dir is not None:
            self.write(f"run directory: {result.run_dir}", error=not result.ok)
        if result.run is not None:
            self.write(f"task: {result.run.get('task')}", error=not result.ok)
            self.write(f"status: {result.run.get('status')}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        return DispatchResult(0 if result.ok else 1)

    def cmd_plan(self, raw: str = "") -> DispatchResult:
        details = raw.strip().lower() == "details"
        result = current_status(self.project_dir)
        if result.run is None or result.run_dir is None:
            self.write(f"No active loop contract. {result.next_step}")
            return DispatchResult(1)
        loop_path = result.run_dir / "loop.md"
        rows = [
            ("goal", compact_text(result.run.get("task"), limit=90)),
            ("status", result.loop_contract.get("status") if result.loop_contract else "unknown"),
            ("pack", result.run.get("pack") or "none"),
            ("file", loop_path),
        ]
        render_summary_table(self.renderer, "Plan", rows, next_command="/continue")
        if result.loop_contract is not None:
            checks = result.loop_contract.get("success_checks", [])
            check_lines = [f"[ ] {check}" for check in checks] or ["none recorded"]
            self.write_panel("Success checks", check_lines)
        tools = self.loop_section_items("Allowed Tools")
        self.write_panel("Allowed tools", [f"- {tool}" for tool in tools] or ["none recorded"])
        if details and loop_path.exists():
            self.write("")
            self.write(loop_path.read_text(encoding="utf-8"))
        return DispatchResult(0)

    def cmd_goal(self, raw: str = "") -> DispatchResult:
        del raw
        result = current_status(self.project_dir)
        if result.run is None:
            self.write(f"goal: none. {result.next_step}")
            return DispatchResult(0)
        self.write(f"goal: {result.run.get('task')}")
        self.write(f"status: {result.run.get('status')}")
        return DispatchResult(0)

    def cmd_guide(self, raw: str = "") -> DispatchResult:
        del raw
        render_guidance(self.renderer, current_guidance(self.project_dir))
        return DispatchResult(0)

    def cmd_actions(self, raw: str = "") -> DispatchResult:
        del raw
        actions = self.action_descriptors()
        if not actions:
            self.write("No guided actions are available.")
            return DispatchResult(0)
        rows = [
            [
                action.id,
                action.label,
                "confirm" if action.requires_confirmation else "safe",
            ]
            for action in actions
        ]
        self.write_table("Actions", ["ID", "Action", "Confirmation"], rows)
        return DispatchResult(0)

    def cmd_next(self, raw: str = "") -> DispatchResult:
        del raw
        action = self.next_action()
        if action is None:
            self.write("Next\nnone")
            return DispatchResult(0)
        self.write("Next")
        self.write(f"/do {action.id}")
        return DispatchResult(0)

    def cmd_why(self, raw: str = "") -> DispatchResult:
        action_id = raw.strip()
        action = (
            self.guidance_action(action_id)
            if action_id
            else self.next_action()
        )
        if action is None:
            self.write("No matching guided action is available.", error=True)
            return DispatchResult(1)
        self.write("Why")
        self.write(action.description)
        return DispatchResult(0)

    def cmd_do(
        self,
        raw: str,
        *,
        operation_callback=None,
        cancel_event: Event | None = None,
    ) -> DispatchResult:
        action_id = raw.strip()
        if not action_id:
            self.write("usage: /do <action-id>", error=True)
            return DispatchResult(2)
        action = self.guidance_action(action_id)
        if action is None:
            self.write(f"unknown guided action: {action_id}", error=True)
            return DispatchResult(1)
        self.write("Do this")
        self.write(action.command_fallback)
        self.write(f"Why: {action.description}")
        if action.requires_confirmation:
            if not self.allow_confirmation:
                self.write(
                    f"action '{action.id}' requires confirmation; run {action.command_fallback} explicitly.",
                    error=True,
                )
                return DispatchResult(1)
            answer = input(f"Run '{action.command_fallback}'? Type yes to continue: ")
            if answer.strip().lower() != "yes":
                self.write("cancelled")
                return DispatchResult(1)
        return self.execute_guided_action(
            action,
            operation_callback=operation_callback,
            cancel_event=cancel_event,
        )

    def cmd_config(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        status = current_status(self.project_dir)
        if not status.initialized or status.config is None:
            self.write("LoopForge is not initialized.", error=True)
            self.write(status.next_step, error=True)
            return DispatchResult(1)
        if not tokens or tokens[0] == "show":
            rows = [[key, json.dumps(status.config[key])] for key in sorted(status.config)]
            self.write_table("LoopForge config", ["Key", "Value"], rows)
            return DispatchResult(0)
        if tokens[0] != "set" or len(tokens) < 3:
            self.write(
                "usage: /config show|set <profile|default-adapter|adapter-args> <value>",
                error=True,
            )
            return DispatchResult(2)
        key = tokens[1].replace("_", "-")
        value = tokens[2:]
        if key == "profile":
            profile = value[0]
            if profile not in {"assist", "supervised", "autonomous", "strict"}:
                self.write(f"unsupported profile: {profile}", error=True)
                return DispatchResult(2)
            result = update_project_config(self.project_dir, {"profile": profile})
        elif key == "default-adapter":
            result = set_default_adapter(self.project_dir, value[0], None)
        elif key == "adapter-args":
            result = set_default_adapter(self.project_dir, self.selected_adapter, value)
        else:
            self.write(f"unsupported config key: {tokens[1]}", error=True)
            return DispatchResult(2)
        self.write(result.message, error=not result.ok)
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        self.refresh_session_config()
        return DispatchResult(0 if result.ok else 1)

    def cmd_theme(self, raw: str) -> DispatchResult:
        if not raw.strip():
            self.write(f"theme  {self.theme}")
            return DispatchResult(0)
        value = raw.strip()
        if value not in {"default", "light", "dark", "mono"}:
            self.write("usage: /theme default|light|dark|mono", error=True)
            return DispatchResult(2)
        self.theme = value
        self.renderer.theme = value
        self.persist_user_preference("theme", value)
        self.write("Theme set")
        self.write(f"theme  {self.theme}")
        return DispatchResult(0)

    def cmd_tui(self, raw: str) -> DispatchResult:
        if not raw.strip():
            self.write(f"tui  {self.renderer_mode}")
            return DispatchResult(0)
        value = raw.strip().lower()
        if value not in {"auto", "rich", "plain"}:
            self.write("usage: /tui auto|rich|plain", error=True)
            return DispatchResult(2)
        self.renderer_mode = value
        self.renderer.set_mode(value)
        self.write("TUI set")
        self.write(f"tui  {self.renderer_mode}")
        return DispatchResult(0)

    def cmd_title(self, raw: str) -> DispatchResult:
        value = raw.strip()
        if value:
            self.session_title = value
            self.write("Title set")
        self.write(f"title  {self.session_title}")
        return DispatchResult(0)

    def cmd_keymap(self, raw: str) -> DispatchResult:
        value = raw.strip().lower()
        if not value:
            self.write(f"keymap  {self.editing_mode}")
            return DispatchResult(0)
        if value not in {"emacs", "vim"}:
            self.write("usage: /keymap emacs|vim", error=True)
            return DispatchResult(2)
        self.editing_mode = value
        self.persist_user_preference("keymap", value)
        self.write("Keymap set")
        self.write(f"keymap  {self.editing_mode}")
        return DispatchResult(0)

    def cmd_vim(self, raw: str = "") -> DispatchResult:
        del raw
        return self.cmd_keymap("vim")

    def cmd_stats(self, raw: str = "") -> DispatchResult:
        del raw
        status = current_status(self.project_dir)
        rows = [["project", status.project_dir.name]]
        if status.run is None:
            rows.append(["run", "none"])
            rows.append(["next_step", status.next_step])
        else:
            attempts = status.run.get("attempt_count", len(status.run.get("attempts", [])))
            rows.extend(
                [
                    ["run_id", str(status.run.get("run_id"))],
                    ["status", str(status.run.get("status"))],
                    ["attempts", str(attempts)],
                    ["pack", str(status.run.get("pack"))],
                    ["tokens", "not reported"],
                    ["cost", "not reported"],
                ]
            )
            if status.verification is not None:
                rows.append(["verification", str(status.verification.get("status"))])
                patch = status.verification.get("patch", {})
                if isinstance(patch, dict):
                    rows.append(["patch_size_bytes", str(patch.get("size_bytes", 0))])
        self.write_table("LoopForge stats", ["Metric", "Value"], rows)
        return DispatchResult(0)

    def cmd_usage(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("usage: token data is not reported.")
        return self.cmd_stats("")

    def cmd_cost(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("cost: not reported")
        return DispatchResult(0)

    def cmd_tasks(self, raw: str = "") -> DispatchResult:
        del raw
        attempts = self.current_run_attempts()
        rows = []
        for attempt in attempts:
            rows.append(
                [
                    str(attempt.get("id")),
                    str(attempt.get("adapter")),
                    str(attempt.get("status")),
                    str(attempt.get("summary", "")),
                ]
            )
        if not rows:
            self.write("No attempts recorded.")
        else:
            self.write_table(
                "LoopForge attempts",
                ["Attempt", "Adapter", "Status", "Summary"],
                rows,
            )
        actions = self.action_descriptors()
        if actions:
            action_rows = [
                [
                    "blocked" if action.requires_confirmation else "do now",
                    action.id,
                    action.label,
                    action.command_fallback,
                ]
                for action in actions
            ]
            self.write_table(
                "Open actions",
                ["Kind", "ID", "Action", "Command"],
                action_rows,
            )
        self.write(f"next step: {current_status(self.project_dir).next_step}")
        return DispatchResult(0)

    def cmd_ps(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("LoopForge records bounded attempts; it does not manage live background jobs.")
        return self.cmd_tasks("")

    def cmd_raw(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        label = tokens[0] if tokens else "latest"
        stream = tokens[1] if len(tokens) > 1 else "stdout"
        if stream not in {"stdout", "stderr", "result"}:
            self.write("usage: /raw [latest|attempt-id|number] [stdout|stderr|result]", error=True)
            return DispatchResult(2)
        attempt = self.attempt_by_label(label)
        if attempt is None:
            self.write("No matching attempt found.", error=True)
            return DispatchResult(1)
        key = {"stdout": "stdout_path", "stderr": "stderr_path", "result": "result_path"}[stream]
        path = Path(str(attempt.get(key) or ""))
        if not path.is_absolute():
            status = current_status(self.project_dir)
            if status.run_dir is not None:
                path = status.run_dir / path
        if not path.exists():
            self.write(f"raw artifact not found: {path}", error=True)
            return DispatchResult(1)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        self.write(f"Raw {attempt.get('id')} {stream}")
        self.write(str(path))
        if not text:
            self.write("empty")
            return DispatchResult(0)
        if len(lines) > 120:
            self.write("\n".join(lines[-120:]))
            self.write(f"... truncated to last 120 of {len(lines)} lines")
        else:
            self.write(text)
        return DispatchResult(0)

    def cmd_memory(self, raw: str = "") -> DispatchResult:
        details = raw.strip().lower() == "details"
        status = current_status(self.project_dir)
        memory = status.memory
        if memory is None:
            self.write("memory: unavailable")
            return DispatchResult(0)
        render_summary_table(
            self.renderer,
            "Memory",
            [
                ("durable", f"{memory.get('durable_items', 0)} facts"),
                ("pending", f"{memory.get('pending', 0)} proposals"),
                ("promoted", memory.get("promoted", 0)),
                ("rejected", memory.get("rejected", 0)),
            ],
            next_command="/approve" if memory.get("pending", 0) else "/status",
        )
        if details:
            rows = [[key, str(memory.get(key))] for key in sorted(memory)]
            self.write_table("Memory details", ["Key", "Value"], rows)
        return DispatchResult(0)

    def cmd_memories(self, raw: str = "") -> DispatchResult:
        suffix = raw.strip()
        return self.cmd_memory("details" if not suffix else suffix)

    def cmd_approve(self, raw: str = "") -> DispatchResult:
        suffix = raw.strip()
        return self.cmd_learn("--approve" + (f" {suffix}" if suffix else ""))

    def cmd_skills(self, raw: str = "") -> DispatchResult:
        del raw
        rows = []
        for pack in discover_pack_contracts(self.project_dir):
            skills = pack.get("skills", [])
            if not skills:
                rows.append([str(pack["name"]), str(pack.get("skill_file") or "")])
            else:
                for skill in skills:
                    rows.append([str(pack["name"]), str(skill)])
        self.write_table("LoopForge skills", ["Pack", "Skill"], rows)
        return DispatchResult(0)

    def cmd_plugins(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("LoopForge external plugin management is not implemented yet.")
        self.write("Local project packs are available:")
        return self.cmd_pack("list")

    def loop_section_items(self, section: str) -> list[str]:
        status = current_status(self.project_dir)
        if status.run_dir is None:
            return []
        path = status.run_dir / "loop.md"
        if not path.exists():
            return []
        items: list[str] = []
        in_section = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.lstrip("#").strip() == section:
                in_section = True
                continue
            if in_section and stripped.startswith("#"):
                break
            if in_section and stripped.startswith("- "):
                items.append(stripped[2:])
        return items

    def cmd_allowed_tools(self, raw: str = "") -> DispatchResult:
        del raw
        tools = self.loop_section_items("Allowed Tools")
        rows = [[tool, "allowed"] for tool in tools] or [["none recorded", "blocked"]]
        self.write_table("Allowed tools", ["Tool", "Status"], rows)
        self.write("Next")
        self.write("/plan")
        return DispatchResult(0)

    def cmd_permissions(self, raw: str = "") -> DispatchResult:
        del raw
        self.write_table(
            "Permissions",
            ["Area", "Status"],
            [
                ["filesystem", "allowed by loop contract"],
                ["network", "adapter-owned"],
                ["publication", "requires review"],
                ["destructive actions", "blocked or confirm"],
            ],
        )
        self.write("Next")
        self.write("/plan")
        return DispatchResult(0)

    def cmd_sandbox(self, raw: str = "") -> DispatchResult:
        del raw
        self.write_table(
            "Sandbox",
            ["Boundary", "Status"],
            [
                ["attempts", "recorded"],
                ["artifacts", "kept"],
                ["adapter sandbox", "adapter-owned"],
            ],
        )
        self.write("Next")
        self.write("/allowed-tools")
        return DispatchResult(0)

    def cmd_review(self, raw: str = "") -> DispatchResult:
        del raw
        status = current_status(self.project_dir)
        lines = ["local review evidence"]
        if status.verification is not None:
            lines.append(f"verification: {status.verification.get('status')}")
            risk = status.verification.get("risk", {})
            if isinstance(risk, dict):
                lines.append(f"risk: {risk.get('risk') or 'unknown'}")
        else:
            lines.append("verification: not run")
        lines.append("blockers:")
        if status.blockers:
            lines.extend(f"- {blocker}" for blocker in status.blockers)
        else:
            lines.append("- none")
        self.write_panel("LoopForge review", lines)
        return DispatchResult(0)

    def cmd_code_review(self, raw: str = "") -> DispatchResult:
        return self.cmd_review(raw)

    def cmd_security_review(self, raw: str = "") -> DispatchResult:
        self.write("security review: local risk policy evidence only; no external audit is run.")
        return self.cmd_review(raw)

    def cmd_simplify(self, raw: str = "") -> DispatchResult:
        self.write("simplify: inspect diff and verification blockers for cleanup opportunities.")
        return self.cmd_review(raw)

    def cmd_export(self, raw: str) -> DispatchResult:
        target = raw.strip() or "status"
        path, error = self.write_export(target)
        if error is not None or path is None:
            self.write(f"export failed: {error}", error=True)
            return DispatchResult(1)
        self.write(f"export path: {path}")
        return DispatchResult(0)

    def cmd_copy(self, raw: str) -> DispatchResult:
        target = raw.strip() or "status"
        text, error = self.text_for_target(target)
        if error is not None or text is None:
            self.write(f"copy failed: {error}", error=True)
            return DispatchResult(1)
        if self.copy_to_clipboard(text):
            self.write(f"copied: {target}")
            return DispatchResult(0)
        path, export_error = self.write_export(target)
        if export_error is not None or path is None:
            self.write("clipboard unavailable; fallback export failed.", error=True)
            return DispatchResult(1)
        self.write(f"clipboard unavailable; exported instead: {path}")
        return DispatchResult(0)

    def cmd_new(self, raw: str) -> DispatchResult:
        return self.cmd_run(raw)

    def cmd_fork(self, raw: str) -> DispatchResult:
        task = raw.strip()
        if not task:
            self.write("usage: /fork <new task>", error=True)
            return DispatchResult(2)
        status = current_status(self.project_dir)
        if status.run is None:
            return self.cmd_run(task)
        try:
            result = create_run(
                self.project_dir,
                task=task,
                pack=str(status.run.get("pack") or ""),
                success_checks=[
                    str(check) for check in status.run.get("success_checks", [])
                ],
            )
        except (FileNotFoundError, ValueError) as error:
            self.write(f"fork failed: {error}", error=True)
            return DispatchResult(1)
        self.write(f"LoopForge fork created: {result.run_dir}")
        self.write(f"run id: {result.run['run_id']}")
        return DispatchResult(0)

    def cmd_cd(self, raw: str) -> DispatchResult:
        target = Path(raw.strip()).expanduser() if raw.strip() else Path.home()
        if not target.is_absolute():
            target = self.project_dir / target
        if not target.exists() or not target.is_dir():
            self.write(f"directory not found: {target}", error=True)
            return DispatchResult(1)
        self.project_dir = target.resolve()
        self.refresh_session_config()
        status = current_status(self.project_dir)
        action = self.next_action()
        render_summary_table(
            self.renderer,
            "Project changed",
            [
                ("project", self.project_dir),
                (
                    "status",
                    status.run.get("status")
                    if status.run is not None
                    else "not initialized"
                    if not status.initialized
                    else "ready_for_run",
                ),
            ],
            next_command=action.command_fallback if action is not None else status.next_step,
        )
        return DispatchResult(0)

    def cmd_add_dir(self, raw: str) -> DispatchResult:
        target = Path(raw.strip()).expanduser()
        if not target.is_absolute():
            target = self.project_dir / target
        if not target.exists() or not target.is_dir():
            self.write(f"context directory not found: {target}", error=True)
            return DispatchResult(1)
        resolved = target.resolve()
        if resolved not in self.extra_context_dirs:
            self.extra_context_dirs.append(resolved)
        self.write(f"added context dir: {resolved}")
        return DispatchResult(0)

    def cmd_mention(self, raw: str) -> DispatchResult:
        target = Path(raw.strip()).expanduser()
        if not target.is_absolute():
            target = self.project_dir / target
        if not target.exists():
            self.write(f"mention path not found: {target}", error=True)
            return DispatchResult(1)
        resolved = target.resolve()
        if resolved not in self.mentioned_paths:
            self.mentioned_paths.append(resolved)
        self.write(f"mentioned: {resolved}")
        return DispatchResult(0)

    def cmd_branch(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        if tokens and tokens[0] == "create":
            if len(tokens) != 2:
                self.write("usage: /branch create <name>", error=True)
                return DispatchResult(2)
            result = subprocess.run(
                ["git", "switch", "-c", tokens[1]],
                cwd=self.project_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            output = result.stdout.strip() or result.stderr.strip()
            self.write(output)
            if result.returncode == 0:
                DEFAULT_GIT_STATE_SERVICE.invalidate(self.project_dir)
                self._git_state = DEFAULT_GIT_STATE_SERVICE.get(self.project_dir)
            return DispatchResult(0 if result.returncode == 0 else 1)
        self._git_state = DEFAULT_GIT_STATE_SERVICE.refresh(self.project_dir)
        if not self._git_state.available:
            self.write("git branch is unavailable in this directory.", error=True)
            return DispatchResult(1)
        self.write(f"branch: {self._git_state.branch or 'detached'}")
        return DispatchResult(0)

    def cmd_archive(self, raw: str = "") -> DispatchResult:
        del raw
        result = archive_current_run(self.project_dir)
        self.write(result.message, error=not result.ok)
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        return DispatchResult(0 if result.ok else 1)

    def cmd_doctor(self, raw: str = "") -> DispatchResult:
        del raw
        deps = tui_dependency_state()
        status = current_status(self.project_dir)
        lines = [
            f"project: {self.project_dir.resolve()}",
            f"initialized: {status.initialized}",
            f"prompt_toolkit: {'available' if deps['prompt_toolkit'] else 'missing'}",
            f"rich: {'available' if deps['rich'] else 'missing'}",
            f"textual: {'available' if deps['textual'] else 'missing'}",
            f"selected adapter: {self.selected_adapter}",
            "selected adapter args: " + " ".join(self.selected_adapter_args),
            f"renderer: {self.renderer_mode}",
            f"theme: {self.theme}",
            f"keymap: {self.editing_mode}",
        ]
        git = subprocess.run(["git", "--version"], check=False, capture_output=True, text=True)
        lines.append(f"git: {git.stdout.strip() if git.returncode == 0 else 'missing'}")
        lines.append(f"supported adapters: {', '.join(SUPPORTED_ADAPTERS)}")
        if status.blockers:
            lines.append("blockers:")
            for blocker in status.blockers:
                lines.append(f"- {blocker}")
        self.write_panel("LoopForge doctor", lines)
        return DispatchResult(0)

    def cmd_debug_config(self, raw: str = "") -> DispatchResult:
        del raw
        status = current_status(self.project_dir)
        self.write("LoopForge debug config")
        self.write(f"project dir: {status.project_dir}")
        self.write(f"config path: {status.config_path}")
        self.write(f"initialized: {status.initialized}")
        self.write(f"LOOPFORGE_HOME: {loopforge_home()}")
        self.write(f"session adapter: {self.selected_adapter}")
        self.write("session adapter args: " + " ".join(self.selected_adapter_args))
        self.write(f"session theme: {self.theme}")
        self.write(f"session renderer: {self.renderer_mode}")
        self.write(f"session keymap: {self.editing_mode}")
        if status.config is not None:
            for key in sorted(status.config):
                self.write(f"{key}: {status.config[key]}")
        return DispatchResult(0)

    def cmd_statusline(self, raw: str) -> DispatchResult:
        value = raw.strip().lower()
        if value in {"", "status"}:
            self.write(f"statusline  {self.statusline}")
            return DispatchResult(0)
        if value not in {"full", "compact", "off"}:
            self.write("usage: /statusline full|compact|off", error=True)
            return DispatchResult(2)
        self.statusline = value
        self.persist_user_preference("statusline", value)
        self.write("Statusline set")
        self.write(f"statusline  {self.statusline}")
        return DispatchResult(0)

    def cmd_clear(self, raw: str = "") -> DispatchResult:
        del raw
        if self.output.isatty():
            self.write("\033[2J\033[H", error=False)
        return DispatchResult(0)

    def cmd_exit(self, raw: str = "") -> DispatchResult:
        del raw
        self.running = False
        return DispatchResult(0, should_exit=True)

    def cmd_quit(self, raw: str = "") -> DispatchResult:
        return self.cmd_exit(raw)

    def toolbar(self) -> str:
        if self.statusline == "off":
            return ""
        status = current_status(self.project_dir)
        parts = [status.project_dir.name]
        if status.config is not None:
            parts.append(str(status.config.get("profile")))
        if status.run is not None:
            parts.append(str(status.run.get("status")))
            parts.append(str(status.run.get("pack")))
        parts.append(f"adapter:{self.selected_adapter}")
        if self._git_state.branch:
            parts.append(f"git:{self._git_state.branch}")
        if self.statusline == "full":
            parts.append(f"blockers:{len(status.blockers)}")
            parts.append(status.next_step)
        return " | ".join(parts)

    def run_prompt(self, *, interactive_ui: bool = True) -> int:
        deps = tui_dependency_state()
        required = ("textual",) if interactive_ui and self.renderer_mode != "plain" else (
            "prompt_toolkit",
            "rich",
        )
        missing = [name for name in required if not deps[name]]
        if missing:
            self.write(
                "LoopForge interactive shell requires missing dependencies: "
                + ", ".join(missing),
                error=True,
            )
            self.write(
                "Install package dependencies or use `loopforge shell --command ...`.",
                error=True,
            )
            return 1

        if interactive_ui and self.renderer_mode != "plain":
            from loopforge.cli.tui import run_fullscreen_console

            return run_fullscreen_console(self)

        from prompt_toolkit import PromptSession
        from prompt_toolkit.enums import EditingMode
        from prompt_toolkit.history import FileHistory

        history_dir = loopforge_home()
        history_dir.mkdir(parents=True, exist_ok=True)
        editing_mode = EditingMode.VI if self.editing_mode == "vim" else EditingMode.EMACS
        session = PromptSession(
            completer=SlashCommandCompleter(contextual_commands(self.project_dir)),
            history=FileHistory(str(history_dir / "interactive-history.txt")),
            bottom_toolbar=lambda: self.toolbar(),
            editing_mode=editing_mode,
        )
        self.write_home()
        exit_code = 0
        while self.running:
            try:
                line = session.prompt(self.prompt_text())
            except (EOFError, KeyboardInterrupt):
                self.write("bye")
                break
            result = self.dispatch(line)
            if result.exit_code:
                exit_code = result.exit_code
            if result.should_exit:
                break
        return exit_code


def run_interactive(
    project_dir: Path,
    *,
    command: str | None = None,
    script: Path | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
    renderer_mode: str = "auto",
    interactive_ui: bool = False,
) -> int:
    shell = InteractiveShell(
        project_dir,
        output=output,
        error=error,
        allow_confirmation=command is None and script is None,
        renderer_mode=renderer_mode,
    )
    if command is not None:
        return shell.dispatch(command).exit_code
    if script is not None:
        exit_code = 0
        for raw_line in script.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            result = shell.dispatch(line)
            if result.exit_code:
                exit_code = result.exit_code
            if result.should_exit:
                break
        return exit_code
    return shell.run_prompt(interactive_ui=interactive_ui_enabled(requested=interactive_ui))
