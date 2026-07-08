"""Interactive shell for LoopForge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

try:
    from prompt_toolkit.completion import Completer
except ImportError:  # pragma: no cover - exercised only in minimal installs.
    class Completer:  # type: ignore[no-redef]
        pass

from loopforge.engine import (
    DEFAULT_ADAPTER,
    DEFAULT_PROFILE,
    GuidedAction,
    SUPPORTED_ADAPTERS,
    archive_current_run,
    compact_current_context,
    continue_run,
    create_run,
    current_guidance,
    current_status,
    dashboard_snapshot,
    dashboard_text_lines,
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


UNSUPPORTED_COMMANDS = {
    "advisor": "LoopForge does not manage a second-model advisor yet.",
    "agent": "LoopForge adapter attempts are tracked as runs, not live agent thread switches.",
    "agents": "LoopForge does not manage background subagent fleets yet.",
    "apps": "Connector browsing belongs to the agent client, not the LoopForge engine.",
    "background": "Detaching interactive sessions is not supported yet.",
    "batch": "Parallel worktree orchestration is not implemented yet.",
    "bg": "Detaching interactive sessions is not supported yet.",
    "btw": "Side conversations are not persisted by LoopForge yet.",
    "delete": "Deletion is intentionally not implemented in v1 to avoid destructive actions.",
    "effort": "Model reasoning effort is owned by the selected adapter CLI.",
    "experimental": "LoopForge does not expose experimental feature toggles yet.",
    "fast": "Fast tier selection is owned by the selected adapter CLI.",
    "feedback": "Feedback submission is not implemented yet.",
    "hooks": "Lifecycle hook management is not implemented yet.",
    "ide": "IDE context import is not implemented yet; mention files in the task or run scratch.",
    "import": "External agent configuration import is not implemented yet.",
    "keybindings": (
        "Use /keymap for session editing mode; persistent keybindings are not implemented."
    ),
    "login": "LoopForge does not own provider authentication.",
    "logout": "LoopForge does not own provider authentication.",
    "mcp": "MCP tool status belongs to the adapter/client layer for now.",
    "model": "Model selection is owned by the selected adapter CLI.",
    "personality": "Response style is owned by the adapter/client layer.",
    "rewind": "Checkpoint rewind is not implemented yet.",
    "sandbox-add-read-dir": (
        "Windows sandbox read-dir grants are owned by the adapter/client layer."
    ),
    "schedule": "Scheduled cloud routines are not implemented yet.",
    "side": "Side conversations are not persisted by LoopForge yet.",
    "stop": "Background task stopping is not implemented yet.",
    "ultraplan": "Cloud planning sessions are not implemented yet.",
    "ultrareview": "Cloud multi-agent review is not implemented yet.",
    "usage-credits": "Usage credit management is not implemented yet.",
}


COMMANDS = dict(sorted({**SUPPORTED_COMMANDS, **UNSUPPORTED_COMMANDS}.items()))
ALIASES = {
    "?": "help",
    "reset": "clear",
    "q": "quit",
}


@dataclass(frozen=True)
class DispatchResult:
    exit_code: int
    should_exit: bool = False


def tui_dependency_state() -> dict[str, bool]:
    return {
        "prompt_toolkit": importlib.util.find_spec("prompt_toolkit") is not None,
        "rich": importlib.util.find_spec("rich") is not None,
    }


def available_commands() -> dict[str, str]:
    return COMMANDS.copy()


class ShellRenderer:
    def __init__(self, output: TextIO, *, mode: str = "auto", theme: str = "default") -> None:
        self.output = output
        self.mode = mode
        self.theme = theme
        self.rich_available = importlib.util.find_spec("rich") is not None
        self.use_rich = mode == "rich" or (
            mode == "auto" and self.rich_available and output.isatty()
        )
        self.console = None
        if self.use_rich:
            from rich.console import Console

            self.console = Console(file=output, highlight=False)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.use_rich = mode == "rich" or (
            mode == "auto" and self.rich_available and self.output.isatty()
        )
        if self.use_rich and self.console is None:
            from rich.console import Console

            self.console = Console(file=self.output, highlight=False)

    def panel(self, title: str, lines: list[str]) -> None:
        if self.use_rich and self.console is not None:
            from rich.panel import Panel

            self.console.print(Panel("\n".join(lines), title=title, border_style="cyan"))
            return
        print(title, file=self.output)
        for line in lines:
            print(line, file=self.output)

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        if self.use_rich and self.console is not None:
            from rich.table import Table

            table = Table(title=title)
            for column in columns:
                table.add_column(column)
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
            return
        print(title, file=self.output)
        print(" | ".join(columns), file=self.output)
        for row in rows:
            print(" | ".join(row), file=self.output)


class SlashCommandCompleter(Completer):
    def __init__(self, commands: dict[str, str]) -> None:
        self.commands = commands

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
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.output = output or sys.stdout
        self.error = error or sys.stderr
        self.running = True
        self.allow_confirmation = allow_confirmation
        self.statusline = "full"
        self.theme = "default"
        self.renderer_mode = "auto"
        self.renderer = ShellRenderer(self.output, mode=self.renderer_mode, theme=self.theme)
        self.extra_context_dirs: list[Path] = []
        self.mentioned_paths: list[Path] = []
        self.editing_mode = "emacs"
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

    def write(self, message: str = "", *, error: bool = False) -> None:
        stream = self.error if error else self.output
        print(message, file=stream)

    def dispatch(self, raw_line: str) -> DispatchResult:
        line = raw_line.strip()
        if not line:
            return DispatchResult(0)

        command, args, implicit_run = self.parse_line(line)
        command = ALIASES.get(command, command)
        if implicit_run:
            return self.cmd_run(args)
        if command in UNSUPPORTED_COMMANDS:
            self.write(f"/{command} is recognized but not supported yet.")
            self.write(f"LoopForge equivalent: {UNSUPPORTED_COMMANDS[command]}")
            return DispatchResult(0)
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

    def split_args(self, raw: str) -> list[str] | None:
        try:
            return shlex.split(raw)
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

    def write_table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        self.renderer.table(title, columns, rows)

    def write_panel(self, title: str, lines: list[str]) -> None:
        self.renderer.panel(title, lines)

    def guidance_lines(self) -> list[str]:
        guidance = current_guidance(self.project_dir)
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
        if guidance.recommended_actions:
            first = guidance.recommended_actions[0]
            lines.extend(
                [
                    "recommended next action:",
                    f"[{first.id}] {first.label}",
                    f"command: {first.command}",
                    f"why: {first.why}",
                ]
            )
        return lines

    def write_guidance(self, *, concise: bool = False) -> None:
        guidance = current_guidance(self.project_dir)
        if concise:
            lines = [f"now: {guidance.summary}"]
            if guidance.recommended_actions:
                first = guidance.recommended_actions[0]
                lines.append(f"next: [{first.id}] {first.command}")
                lines.append(f"why: {first.why}")
            self.write_panel("LoopForge guidance", lines)
            return
        self.write_panel("LoopForge guidance", self.guidance_lines())
        if guidance.recommended_actions:
            self.write_actions(guidance.recommended_actions)

    def write_actions(self, actions: list[GuidedAction]) -> None:
        rows = [
            [
                action.id,
                action.risk,
                "yes" if action.requires_confirmation else "no",
                action.command,
                action.why,
            ]
            for action in actions
        ]
        self.write_table("Guided actions", ["ID", "Risk", "Confirm", "Command", "Why"], rows)

    def guidance_action(self, action_id: str) -> GuidedAction | None:
        for action in current_guidance(self.project_dir).recommended_actions:
            if action.id == action_id:
                return action
        return None

    def dispatch_guided_command(self, command: str) -> DispatchResult:
        if command == "loopforge init":
            return self.cmd_init("")
        if command.startswith("loopforge run "):
            self.write("This action needs a real task. Use /run <task>.", error=True)
            return DispatchResult(2)
        if command == "loopforge continue":
            return self.cmd_continue("--check")
        if command.startswith("loopforge continue --adapter "):
            adapter = command.rsplit(" ", 1)[-1]
            return self.cmd_continue(f"--adapter {adapter}")
        if command == "loopforge verify":
            return self.cmd_verify("")
        if command == "loopforge learn --approve":
            return self.cmd_learn("--approve")
        if command.startswith("loopforge shell --command "):
            raw = command.removeprefix("loopforge shell --command ").strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
                raw = raw[1:-1]
            return self.dispatch(raw)
        if command == "loopforge status":
            return self.cmd_status("")
        self.write(f"Cannot execute guided command yet: {command}", error=True)
        return DispatchResult(2)

    def status_lines(self) -> list[str]:
        result = current_status(self.project_dir)
        lines = [f"project: {result.project_dir.name}"]
        if not result.initialized:
            lines.extend(
                [
                    "state: not initialized",
                    f"config: {result.config_path}",
                    f"next step: {result.next_step}",
                ]
            )
            return lines
        assert result.config is not None
        lines.extend(
            [
                "state: initialized",
                f"profile: {result.config['profile']}",
                *profile_permission_lines(result.config["profile"]),
                f"run root: {result.config['run_root']}",
                f"default adapter: {result.config.get('default_adapter')}",
                "default adapter args: "
                + " ".join(result.config.get("default_adapter_args", [])),
            ]
        )
        if result.run is None:
            lines.append(f"current run: {result.config.get('current_run_id') or 'none'}")
            lines.append(f"next step: {result.next_step}")
            return lines
        run = result.run
        lines.extend(
            [
                f"current run: {run['run_id']}",
                f"task: {run['task']}",
                f"loop status: {run['status']}",
                f"attempts: {run.get('attempt_count', len(run.get('attempts', [])))}",
                f"pack: {run['pack']}",
                f"run directory: {result.run_dir}",
            ]
        )
        if result.loop_contract is not None:
            lines.append(f"loop contract: {result.loop_contract['status']}")
            lines.append(
                f"success checks: {len(result.loop_contract.get('success_checks', []))}"
            )
        if result.verification is not None:
            lines.append(f"verification: {result.verification.get('status', 'unknown')}")
        if result.memory is not None:
            lines.append(f"durable memory: {result.memory.get('durable_items', 0)} items")
            lines.append(f"memory proposals: {result.memory.get('pending', 0)} pending")
        lines.append("blockers:")
        if result.blockers:
            lines.extend(f"- {blocker}" for blocker in result.blockers)
        else:
            lines.append("- none")
        lines.append(f"next step: {result.next_step}")
        return lines

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
            command = ALIASES.get(command, command)
            if command in COMMANDS:
                self.write(f"/{command}: {COMMANDS[command]}")
                if command in UNSUPPORTED_COMMANDS:
                    self.write(f"Status: not supported yet. {UNSUPPORTED_COMMANDS[command]}")
                return DispatchResult(0)
            self.write(f"Unknown command: /{command}", error=True)
            return DispatchResult(2)
        self.write("LoopForge interactive shell")
        self.write("Type plain text to create a run, or use slash commands.")
        self.write(
            "Useful commands: /status, /context, /compact, /run, /continue, /verify, /learn."
        )
        self.write("Run /commands for the full catalog.")
        return DispatchResult(0)

    def cmd_commands(self, raw: str = "") -> DispatchResult:
        del raw
        rows = []
        for command, description in COMMANDS.items():
            state = "local" if command in SUPPORTED_COMMANDS else "not supported yet"
            rows.append([f"/{command}", state, description])
        self.write_table("LoopForge commands", ["Command", "Status", "Description"], rows)
        return DispatchResult(0)

    def cmd_adapters(self, raw: str = "") -> DispatchResult:
        del raw
        rows = []
        for adapter in SUPPORTED_ADAPTERS:
            selected = "yes" if adapter == self.selected_adapter else ""
            rows.append([adapter, selected])
        self.write_table("LoopForge adapters", ["Adapter", "Selected"], rows)
        self.write(f"selected adapter: {self.selected_adapter}")
        self.write("selected adapter args: " + " ".join(self.selected_adapter_args))
        return DispatchResult(0)

    def cmd_adapter(self, raw: str) -> DispatchResult:
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        if not tokens:
            return self.cmd_adapters("")
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
        self.write(result.message, error=not result.ok)
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
            return DispatchResult(1)
        self.refresh_session_config()
        self.write(f"selected adapter: {self.selected_adapter}")
        self.write("selected adapter args: " + " ".join(self.selected_adapter_args))
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
        self.write(f"LoopForge {action}: {result.config_path}")
        self.write(f"project: {result.config['project_name']}")
        self.write(f"profile: {result.config['profile']}")
        self.write(f"run root: {result.config['run_root']}")
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
        self.write(f"LoopForge run created: {result.run_dir}")
        self.write(f"run id: {result.run['run_id']}")
        self.write(f"status: {result.run['status']}")
        self.write(f"pack: {result.run['pack']}")
        for line in profile_permission_lines(result.run["profile"]):
            self.write(line)
        self.write_guidance(concise=True)
        return DispatchResult(0)

    def cmd_status(self, raw: str = "") -> DispatchResult:
        del raw
        self.write_panel("LoopForge status", self.status_lines())
        self.write_guidance(concise=True)
        return DispatchResult(0)

    def cmd_dashboard(self, raw: str = "") -> DispatchResult:
        del raw
        result = dashboard_snapshot(self.project_dir)
        self.write_panel("LoopForge dashboard", dashboard_text_lines(result.snapshot))
        return DispatchResult(0)

    def cmd_continue(self, raw: str) -> DispatchResult:
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
        result = continue_run(
            self.project_dir,
            adapter=adapter,
            adapter_args=chosen_args,
            confirmed=confirmed,
        )
        self.write(result.message, error=not result.ok)
        if result.run_dir is not None:
            self.write(f"run directory: {result.run_dir}", error=not result.ok)
        if result.attempt is not None:
            self.write(f"attempt: {result.attempt['id']}", error=not result.ok)
            self.write(f"adapter: {result.attempt['adapter']}", error=not result.ok)
            self.write(f"attempt status: {result.attempt['status']}", error=not result.ok)
            self.write(f"stdout: {result.attempt['stdout_path']}", error=not result.ok)
            self.write(f"stderr: {result.attempt['stderr_path']}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        if result.run is not None:
            for line in profile_permission_lines(result.run.get("profile")):
                self.write(line, error=not result.ok)
            self.write(
                f"next step: {current_status(self.project_dir).next_step}",
                error=not result.ok,
            )
        self.write_guidance(concise=True)
        return DispatchResult(0 if result.ok else 1)

    def cmd_verify(self, raw: str = "") -> DispatchResult:
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
        result = verify_run(self.project_dir, confirmed=confirmed)
        self.write(result.message, error=not result.ok)
        if result.run_dir is not None:
            self.write(f"run directory: {result.run_dir}", error=not result.ok)
        if result.run is not None:
            for line in profile_permission_lines(result.run.get("profile")):
                self.write(line, error=not result.ok)
        if result.verification is not None:
            self.write(f"verification: {result.verification['status']}", error=not result.ok)
            self.write(
                f"pack checks: {result.verification.get('checks_passed', 0)}/"
                f"{result.verification.get('checks_total', 0)}",
                error=not result.ok,
            )
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        self.write_guidance(concise=True)
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
        result = learn_run(
            self.project_dir,
            approve=args.approve,
            notes=args.note,
            confirmed=confirmed,
        )
        self.write(result.message, error=not result.ok)
        if result.proposal_path is not None:
            self.write(f"proposal path: {result.proposal_path}", error=not result.ok)
        if result.run is not None:
            for line in profile_permission_lines(result.run.get("profile")):
                self.write(line, error=not result.ok)
        self.write(f"proposals: {len(result.proposals)}", error=not result.ok)
        self.write(f"promoted: {len(result.promoted)}", error=not result.ok)
        self.write(f"rejected: {len(result.rejected)}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        self.write_guidance(concise=True)
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
            for pack in packs:
                description = pack.get("description") or ""
                self.write(f"{pack['name']}: {description}".rstrip())
                self.write(f"  source: {pack.get('source') or 'none'}")
            return DispatchResult(0)
        if tokens == ["detect"]:
            pack = detect_project_pack(self.project_dir)
            self.write(f"pack: {pack['name']}")
            self.write(f"source: {pack.get('source') or 'none'}")
            self.write(f"score: {pack.get('detection_score', 0)}")
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
        self.write(f"run root: {result.run_root}")
        if not result.runs:
            self.write("No runs found.")
            return DispatchResult(0)
        for run in result.runs:
            marker = "*" if run.get("current") else "-"
            task = str(run.get("task") or "").replace("\n", " ")
            self.write(f"{marker} {run['run_id']} [{run.get('status')}] {task}")
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
        del raw
        result = current_status(self.project_dir)
        if result.run is None or result.run_dir is None:
            self.write(f"No active loop contract. {result.next_step}")
            return DispatchResult(1)
        loop_path = result.run_dir / "loop.md"
        self.write(f"loop contract: {loop_path}")
        if result.loop_contract is not None:
            self.write(f"status: {result.loop_contract.get('status')}")
            checks = result.loop_contract.get("success_checks", [])
            self.write(f"success checks: {len(checks)}")
            for check in checks:
                self.write(f"- {check}")
        if loop_path.exists():
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
        self.write_guidance()
        return DispatchResult(0)

    def cmd_actions(self, raw: str = "") -> DispatchResult:
        del raw
        guidance = current_guidance(self.project_dir)
        if not guidance.recommended_actions:
            self.write("No guided actions are available.")
            return DispatchResult(0)
        self.write_actions(guidance.recommended_actions)
        return DispatchResult(0)

    def cmd_next(self, raw: str = "") -> DispatchResult:
        del raw
        guidance = current_guidance(self.project_dir)
        if not guidance.recommended_actions:
            self.write("next: no recommended action")
            return DispatchResult(0)
        action = guidance.recommended_actions[0]
        self.write(f"next: [{action.id}] {action.label}")
        self.write(f"command: {action.command}")
        self.write(f"risk: {action.risk}")
        self.write(f"requires confirmation: {action.requires_confirmation}")
        return DispatchResult(0)

    def cmd_why(self, raw: str = "") -> DispatchResult:
        action_id = raw.strip()
        guidance = current_guidance(self.project_dir)
        action = (
            self.guidance_action(action_id)
            if action_id
            else guidance.recommended_actions[0] if guidance.recommended_actions else None
        )
        if action is None:
            self.write("No matching guided action is available.", error=True)
            return DispatchResult(1)
        self.write(f"why [{action.id}]: {action.why}")
        self.write(f"command: {action.command}")
        return DispatchResult(0)

    def cmd_do(self, raw: str) -> DispatchResult:
        action_id = raw.strip()
        if not action_id:
            self.write("usage: /do <action-id>", error=True)
            return DispatchResult(2)
        action = self.guidance_action(action_id)
        if action is None:
            self.write(f"unknown guided action: {action_id}", error=True)
            return DispatchResult(1)
        if action.requires_confirmation:
            if not self.allow_confirmation:
                self.write(
                    f"action '{action.id}' requires confirmation; run {action.command} explicitly.",
                    error=True,
                )
                return DispatchResult(1)
            answer = input(f"Run '{action.command}'? Type yes to continue: ")
            if answer.strip().lower() != "yes":
                self.write("cancelled")
                return DispatchResult(1)
        self.write(f"doing [{action.id}]: {action.label}")
        return self.dispatch_guided_command(action.command)

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
        value = raw.strip() or "default"
        if value not in {"default", "light", "dark", "mono"}:
            self.write("usage: /theme default|light|dark|mono", error=True)
            return DispatchResult(2)
        self.theme = value
        self.renderer.theme = value
        self.write(f"theme: {self.theme}")
        return DispatchResult(0)

    def cmd_tui(self, raw: str) -> DispatchResult:
        value = raw.strip().lower() or "auto"
        if value not in {"auto", "rich", "plain"}:
            self.write("usage: /tui auto|rich|plain", error=True)
            return DispatchResult(2)
        self.renderer_mode = value
        self.renderer.set_mode(value)
        self.write(f"tui: {self.renderer_mode}")
        return DispatchResult(0)

    def cmd_title(self, raw: str) -> DispatchResult:
        value = raw.strip()
        if value:
            self.session_title = value
        self.write(f"title: {self.session_title}")
        return DispatchResult(0)

    def cmd_keymap(self, raw: str) -> DispatchResult:
        value = raw.strip().lower()
        if not value:
            self.write(f"keymap: {self.editing_mode}")
            self.write("usage: /keymap emacs|vim")
            return DispatchResult(0)
        if value not in {"emacs", "vim"}:
            self.write("usage: /keymap emacs|vim", error=True)
            return DispatchResult(2)
        self.editing_mode = value
        self.write(f"keymap: {self.editing_mode}")
        return DispatchResult(0)

    def cmd_vim(self, raw: str = "") -> DispatchResult:
        del raw
        self.editing_mode = "vim" if self.editing_mode != "vim" else "emacs"
        self.write(f"keymap: {self.editing_mode}")
        return DispatchResult(0)

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
                    ["tokens", "unavailable"],
                    ["cost", "unavailable"],
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
        self.write("usage: local run usage is tracked; model token usage is unavailable.")
        return self.cmd_stats("")

    def cmd_cost(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("cost: unavailable; LoopForge does not infer model/provider costs.")
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
        guidance = current_guidance(self.project_dir)
        if guidance.recommended_actions:
            action_rows = [
                [
                    "blocked" if action.requires_confirmation else "do now",
                    action.id,
                    action.label,
                    action.command,
                ]
                for action in guidance.recommended_actions
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
        self.write(path.read_text(encoding="utf-8", errors="replace"))
        return DispatchResult(0)

    def cmd_memory(self, raw: str = "") -> DispatchResult:
        del raw
        status = current_status(self.project_dir)
        memory = status.memory
        if memory is None:
            self.write("memory: unavailable")
            return DispatchResult(0)
        rows = [[key, str(memory.get(key))] for key in sorted(memory)]
        self.write_table("LoopForge memory", ["Key", "Value"], rows)
        return DispatchResult(0)

    def cmd_memories(self, raw: str = "") -> DispatchResult:
        return self.cmd_memory(raw)

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
        self.write("allowed tools:")
        if tools:
            for tool in tools:
                self.write(f"- {tool}")
        else:
            self.write("- none recorded")
        self.write("Set tools for new runs with /run --allow-tool <tool>.")
        return DispatchResult(0)

    def cmd_permissions(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("permissions: governed by the loop contract and adapter boundary.")
        return self.cmd_allowed_tools("")

    def cmd_sandbox(self, raw: str = "") -> DispatchResult:
        del raw
        self.write("sandbox: LoopForge records bounded adapter attempts and artifacts.")
        self.write("adapter-specific sandboxing remains owned by the adapter CLI.")
        return self.cmd_allowed_tools("")

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
        self.write(f"project dir: {self.project_dir}")
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
            return DispatchResult(0 if result.returncode == 0 else 1)
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.project_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.write("git branch is unavailable in this directory.", error=True)
            return DispatchResult(1)
        self.write(f"branch: {result.stdout.strip() or 'detached'}")
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
            self.write(f"statusline: {self.statusline}")
            self.write("usage: /statusline full|compact|off")
            return DispatchResult(0)
        if value not in {"full", "compact", "off"}:
            self.write("usage: /statusline full|compact|off", error=True)
            return DispatchResult(2)
        self.statusline = value
        self.write(f"statusline: {self.statusline}")
        return DispatchResult(0)

    def cmd_clear(self, raw: str = "") -> DispatchResult:
        del raw
        if self.output.isatty():
            self.write("\033[2J\033[H", error=False)
        else:
            self.write("screen cleared")
        return DispatchResult(0)

    def cmd_exit(self, raw: str = "") -> DispatchResult:
        del raw
        self.running = False
        self.write("bye")
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
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.project_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if branch.returncode == 0 and branch.stdout.strip():
            parts.append(f"git:{branch.stdout.strip()}")
        if self.statusline == "full":
            parts.append(f"blockers:{len(status.blockers)}")
            parts.append(status.next_step)
        return " | ".join(parts)

    def run_prompt(self) -> int:
        deps = tui_dependency_state()
        missing = [name for name, available in deps.items() if not available]
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

        from prompt_toolkit import PromptSession
        from prompt_toolkit.enums import EditingMode
        from prompt_toolkit.history import FileHistory

        history_dir = loopforge_home()
        history_dir.mkdir(parents=True, exist_ok=True)
        editing_mode = EditingMode.VI if self.editing_mode == "vim" else EditingMode.EMACS
        session = PromptSession(
            completer=SlashCommandCompleter(COMMANDS),
            history=FileHistory(str(history_dir / "interactive-history.txt")),
            bottom_toolbar=lambda: self.toolbar(),
            editing_mode=editing_mode,
        )
        self.write("LoopForge interactive shell. Type /help for commands.")
        exit_code = 0
        while self.running:
            try:
                line = session.prompt("loopforge> ")
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
) -> int:
    shell = InteractiveShell(
        project_dir,
        output=output,
        error=error,
        allow_confirmation=command is None and script is None,
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
    return shell.run_prompt()
