"""Interactive shell for LoopForge."""

from __future__ import annotations

import argparse
import importlib.util
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
    DEFAULT_PROFILE,
    SUPPORTED_ADAPTERS,
    compact_current_context,
    continue_run,
    create_run,
    current_status,
    detect_project_pack,
    directory_file_sizes,
    discover_pack_contracts,
    initialize_project,
    list_runs,
    loopforge_home,
    resume_run,
    verify_run,
    learn_run,
)


SUPPORTED_COMMANDS = {
    "clear": "Clear the visible terminal screen.",
    "commands": "List available interactive commands.",
    "compact": "Write a deterministic compact handoff for the current run.",
    "context": "Show LoopForge project and run context.",
    "continue": "Validate the current loop or execute a bounded adapter attempt.",
    "debug-config": "Show LoopForge configuration diagnostics.",
    "diff": "Show current Git working tree status and diff summary.",
    "doctor": "Run local environment diagnostics.",
    "exit": "Exit the interactive shell.",
    "goal": "Show the current LoopForge run objective.",
    "help": "Show command help.",
    "init": "Initialize LoopForge metadata for this project.",
    "learn": "Propose or approve durable memory updates.",
    "pack": "List or detect project packs.",
    "plan": "Show the current loop contract and success checks.",
    "quit": "Exit the interactive shell.",
    "recap": "Print a one-line recap of the current run.",
    "resume": "Switch the current run by run id.",
    "run": "Create a new run. Plain text input is also treated as /run.",
    "runs": "List known runs for this project.",
    "status": "Show current LoopForge loop state.",
    "statusline": "Configure the session-only status line.",
    "verify": "Generate a patch and run deterministic pack checks.",
}


UNSUPPORTED_COMMANDS = {
    "add-dir": (
        "LoopForge v1 stays anchored to one project root; add extra context through run "
        "files or packs."
    ),
    "advisor": "LoopForge does not manage a second-model advisor yet.",
    "agent": "LoopForge adapter attempts are tracked as runs, not live agent thread switches.",
    "agents": "LoopForge does not manage background subagent fleets yet.",
    "allowed-tools": (
        "Use /run --allow-tool for a run contract instead of editing live permissions."
    ),
    "apps": "Connector browsing belongs to the agent client, not the LoopForge engine.",
    "approve": "LoopForge approvals are explicit commands such as /learn --approve.",
    "archive": "Archiving sessions is not supported yet; run artifacts are retained on disk.",
    "background": "Detaching interactive sessions is not supported yet.",
    "batch": "Parallel worktree orchestration is not implemented yet.",
    "bg": "Detaching interactive sessions is not supported yet.",
    "branch": "Conversation branching is not supported yet; create a new run for a new direction.",
    "btw": "Side conversations are not persisted by LoopForge yet.",
    "cd": "Changing project roots inside a session is not supported yet.",
    "code-review": (
        "Use /verify for deterministic checks; review automation is not implemented yet."
    ),
    "config": "Persistent TUI preferences are not implemented yet.",
    "copy": "Clipboard integration is not implemented yet.",
    "cost": "Usage and cost accounting is not implemented yet.",
    "delete": "Deletion is intentionally not implemented in v1 to avoid destructive actions.",
    "effort": "Model reasoning effort is owned by the selected adapter CLI.",
    "experimental": "LoopForge does not expose experimental feature toggles yet.",
    "export": "Transcript export is not implemented yet; run artifacts are plain files on disk.",
    "fast": "Fast tier selection is owned by the selected adapter CLI.",
    "feedback": "Feedback submission is not implemented yet.",
    "fork": "Forked subagents are not implemented yet; create a new run for an alternate path.",
    "hooks": "Lifecycle hook management is not implemented yet.",
    "ide": "IDE context import is not implemented yet; mention files in the task or run scratch.",
    "import": "External agent configuration import is not implemented yet.",
    "keybindings": "Keyboard shortcut editing is not implemented yet.",
    "keymap": "Keyboard shortcut editing is not implemented yet.",
    "login": "LoopForge does not own provider authentication.",
    "logout": "LoopForge does not own provider authentication.",
    "mcp": "MCP tool status belongs to the adapter/client layer for now.",
    "memories": "Use /learn for LoopForge durable memory proposals.",
    "memory": "Use /learn for LoopForge durable memory proposals.",
    "mention": "File attachment is not implemented yet; include file paths in the task text.",
    "model": "Model selection is owned by the selected adapter CLI.",
    "new": "Starting a fresh conversation is not a LoopForge concept; create a new /run.",
    "permissions": "Use loop contract allowed tools instead of live permission presets.",
    "personality": "Response style is owned by the adapter/client layer.",
    "plugins": "Plugin browsing is not implemented in LoopForge yet.",
    "ps": "Background process listing is not implemented yet.",
    "raw": "Raw scrollback is a client rendering feature and is not implemented here.",
    "review": "Use /verify for deterministic checks; PR review is not implemented yet.",
    "rewind": "Checkpoint rewind is not implemented yet.",
    "sandbox": "Sandbox policy is owned by the adapter/client layer.",
    "sandbox-add-read-dir": (
        "Windows sandbox read-dir grants are owned by the adapter/client layer."
    ),
    "schedule": "Scheduled cloud routines are not implemented yet.",
    "security-review": "Security review automation is not implemented yet.",
    "side": "Side conversations are not persisted by LoopForge yet.",
    "simplify": "Cleanup review automation is not implemented yet.",
    "skills": (
        "Pack skills are loaded through /pack and /run; a live skill picker is not "
        "implemented yet."
    ),
    "stats": "Usage and cost accounting is not implemented yet.",
    "stop": "Background task stopping is not implemented yet.",
    "tasks": "Background task management is not implemented yet.",
    "theme": "Theme selection is not implemented yet.",
    "title": "Terminal title customization is not implemented yet.",
    "tui": "Renderer switching is not implemented yet.",
    "ultraplan": "Cloud planning sessions are not implemented yet.",
    "ultrareview": "Cloud multi-agent review is not implemented yet.",
    "usage": "Usage and cost accounting is not implemented yet.",
    "usage-credits": "Usage credit management is not implemented yet.",
    "vim": "Vim composer mode is not implemented yet.",
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
    ) -> None:
        self.project_dir = project_dir
        self.output = output or sys.stdout
        self.error = error or sys.stderr
        self.running = True
        self.statusline = "full"

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
        for command, description in COMMANDS.items():
            marker = "" if command in SUPPORTED_COMMANDS else " (not supported yet)"
            self.write(f"/{command}: {description}{marker}")
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
        return DispatchResult(0)

    def cmd_status(self, raw: str = "") -> DispatchResult:
        del raw
        result = current_status(self.project_dir)
        self.write(f"project: {result.project_dir.name}")
        if not result.initialized:
            self.write("state: not initialized")
            self.write(f"config: {result.config_path}")
            self.write(f"next step: {result.next_step}")
            return DispatchResult(0)
        assert result.config is not None
        self.write("state: initialized")
        self.write(f"profile: {result.config['profile']}")
        self.write(f"run root: {result.config['run_root']}")
        if result.run is None:
            self.write(f"current run: {result.config.get('current_run_id') or 'none'}")
            self.write(f"next step: {result.next_step}")
            return DispatchResult(0)
        run = result.run
        self.write(f"current run: {run['run_id']}")
        self.write(f"task: {run['task']}")
        self.write(f"loop status: {run['status']}")
        self.write(f"attempts: {run.get('attempt_count', len(run.get('attempts', [])))}")
        self.write(f"pack: {run['pack']}")
        self.write(f"run directory: {result.run_dir}")
        if result.loop_contract is not None:
            self.write(f"loop contract: {result.loop_contract['status']}")
            self.write(f"success checks: {len(result.loop_contract.get('success_checks', []))}")
        if result.verification is not None:
            self.write(f"verification: {result.verification.get('status', 'unknown')}")
        if result.memory is not None:
            self.write(f"durable memory: {result.memory.get('durable_items', 0)} items")
            self.write(f"memory proposals: {result.memory.get('pending', 0)} pending")
        self.write("blockers:")
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}")
        else:
            self.write("- none")
        self.write(f"next step: {result.next_step}")
        return DispatchResult(0)

    def cmd_continue(self, raw: str) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/continue", add_help=False)
        parser.add_argument("--adapter", choices=SUPPORTED_ADAPTERS)
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
        result = continue_run(self.project_dir, adapter=args.adapter, adapter_args=adapter_args)
        self.write(result.message, error=not result.ok)
        if result.run_dir is not None:
            self.write(f"run directory: {result.run_dir}", error=not result.ok)
        if result.attempt is not None:
            self.write(f"attempt: {result.attempt['id']}", error=not result.ok)
            self.write(f"attempt status: {result.attempt['status']}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
        return DispatchResult(0 if result.ok else 1)

    def cmd_verify(self, raw: str = "") -> DispatchResult:
        del raw
        result = verify_run(self.project_dir)
        self.write(result.message, error=not result.ok)
        if result.run_dir is not None:
            self.write(f"run directory: {result.run_dir}", error=not result.ok)
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
        return DispatchResult(0 if result.ok else 1)

    def cmd_learn(self, raw: str) -> DispatchResult:
        parser = argparse.ArgumentParser(prog="/learn", add_help=False)
        parser.add_argument("--approve", action="store_true")
        parser.add_argument("--note", action="append", default=[])
        tokens = self.split_args(raw)
        if tokens is None:
            return DispatchResult(2)
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            return DispatchResult(2)
        result = learn_run(self.project_dir, approve=args.approve, notes=args.note)
        self.write(result.message, error=not result.ok)
        if result.proposal_path is not None:
            self.write(f"proposal path: {result.proposal_path}", error=not result.ok)
        self.write(f"proposals: {len(result.proposals)}", error=not result.ok)
        self.write(f"promoted: {len(result.promoted)}", error=not result.ok)
        self.write(f"rejected: {len(result.rejected)}", error=not result.ok)
        if result.blockers:
            self.write("blockers:", error=not result.ok)
            for blocker in result.blockers:
                self.write(f"- {blocker}", error=not result.ok)
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
        result = current_status(self.project_dir)
        self.write("LoopForge context")
        self.write(f"project: {result.project_dir}")
        self.write(f"initialized: {result.initialized}")
        if result.config is not None:
            self.write(f"profile: {result.config.get('profile')}")
            self.write(f"run root: {result.config.get('run_root')}")
        if result.run is not None and result.run_dir is not None:
            self.write(f"current run: {result.run.get('run_id')}")
            self.write(f"task: {result.run.get('task')}")
            self.write(f"status: {result.run.get('status')}")
            self.write(f"pack: {result.run.get('pack')}")
            sizes = directory_file_sizes(result.run_dir)
            self.write(f"run files: {len(sizes)}")
            self.write(f"run bytes: {sum(size for _, size in sizes)}")
        if result.memory is not None:
            self.write(f"durable memory items: {result.memory.get('durable_items', 0)}")
            self.write(f"pending memory proposals: {result.memory.get('pending', 0)}")
        self.write("blockers:")
        if result.blockers:
            for blocker in result.blockers:
                self.write(f"- {blocker}")
        else:
            self.write("- none")
        self.write(f"next step: {result.next_step}")
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

    def cmd_doctor(self, raw: str = "") -> DispatchResult:
        del raw
        deps = tui_dependency_state()
        status = current_status(self.project_dir)
        self.write("LoopForge doctor")
        self.write(f"project: {self.project_dir.resolve()}")
        self.write(f"initialized: {status.initialized}")
        self.write(f"prompt_toolkit: {'available' if deps['prompt_toolkit'] else 'missing'}")
        self.write(f"rich: {'available' if deps['rich'] else 'missing'}")
        git = subprocess.run(["git", "--version"], check=False, capture_output=True, text=True)
        self.write(f"git: {git.stdout.strip() if git.returncode == 0 else 'missing'}")
        self.write(f"supported adapters: {', '.join(SUPPORTED_ADAPTERS)}")
        if status.blockers:
            self.write("blockers:")
            for blocker in status.blockers:
                self.write(f"- {blocker}")
        return DispatchResult(0)

    def cmd_debug_config(self, raw: str = "") -> DispatchResult:
        del raw
        status = current_status(self.project_dir)
        self.write("LoopForge debug config")
        self.write(f"project dir: {status.project_dir}")
        self.write(f"config path: {status.config_path}")
        self.write(f"initialized: {status.initialized}")
        self.write(f"LOOPFORGE_HOME: {loopforge_home()}")
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
        from prompt_toolkit.history import FileHistory

        history_dir = loopforge_home()
        history_dir.mkdir(parents=True, exist_ok=True)
        session = PromptSession(
            completer=SlashCommandCompleter(COMMANDS),
            history=FileHistory(str(history_dir / "interactive-history.txt")),
            bottom_toolbar=lambda: self.toolbar(),
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
    shell = InteractiveShell(project_dir, output=output, error=error)
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
