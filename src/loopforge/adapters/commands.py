"""Headless and interactive command builders for agent harness adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from loopforge.adapters.kilo_code import DEFAULT_IMPLEMENTATION_AGENT, headless_run_command


AGENT_COMMANDS = {
    "codex": "codex",
    "claude-code": "claude",
    "kilo-code": "kilo",
    "aider": "aider",
    "opencode": "opencode",
    "mini-swe-agent": "mini-swe-agent",
}
INTERACTIVE_ADAPTERS = frozenset({"codex", "claude-code", "kilo-code", "opencode"})


class InteractiveAdapterUnavailable(ValueError):
    """Raised when an adapter has no safe interactive prompt contract."""


def require_interactive_adapter(adapter: str) -> None:
    if adapter not in INTERACTIVE_ADAPTERS:
        raise InteractiveAdapterUnavailable(
            f"adapter {adapter} does not define a safe interactive prompt command"
        )


def _without_options(
    arguments: Sequence[str],
    *,
    flags: Iterable[str] = (),
    value_options: Iterable[str] = (),
    variadic_value_options: Iterable[str] = (),
) -> list[str]:
    removed_flags = set(flags)
    removed_values = set(value_options)
    removed_variadic_values = set(variadic_value_options)
    prepared: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        option = argument.split("=", 1)[0]
        if option in removed_flags:
            index += 1
            continue
        if option in removed_values:
            index += 1 if "=" in argument else 2
            continue
        if option in removed_variadic_values:
            index += 1
            if "=" not in argument:
                while index < len(arguments) and not arguments[index].startswith("-"):
                    index += 1
            continue
        prepared.append(argument)
        index += 1
    return prepared


def headless_implementation_command(
    *,
    adapter: str,
    adapter_args: Sequence[str],
    workspace_dir: Path | None = None,
) -> list[str]:
    """Build the existing autonomous implementation command for *adapter*."""

    if adapter == "codex":
        args = list(adapter_args)
        if not args:
            args = ["exec"]
        elif args[0] not in {"exec", "e"}:
            args = ["exec", *args]
        if "-s" not in args and "--sandbox" not in args:
            args[1:1] = ["-s", "workspace-write"]
        if workspace_dir is not None and "-C" not in args and "--cd" not in args:
            args[1:1] = ["--cd", str(workspace_dir)]
        if "--color" not in args:
            args[1:1] = ["--color", "never"]
        if "--json" not in args:
            args[1:1] = ["--json"]
        if "-" not in args:
            args.append("-")
        return [AGENT_COMMANDS[adapter], *args]
    if adapter == "kilo-code":
        return headless_run_command(
            adapter_args,
            default_agent=DEFAULT_IMPLEMENTATION_AGENT,
        )
    return adapter_command(adapter, adapter_args)


def adapter_command(adapter: str, adapter_args: Sequence[str]) -> list[str]:
    if adapter == "local-adapter-fixture":
        if not adapter_args:
            raise ValueError("local-adapter-fixture requires a command after --")
        return list(adapter_args)
    executable = AGENT_COMMANDS.get(adapter)
    if executable is None:
        raise ValueError(f"unsupported adapter: {adapter}")
    return [executable, *adapter_args]


def redacted_interactive_command(command: Sequence[str], prompt: str) -> list[str]:
    return [
        "<LoopForge prompt from adapter-prompt.md>" if argument == prompt else argument
        for argument in command
    ]


def interactive_agent_command(
    *,
    adapter: str,
    adapter_args: Sequence[str],
    workspace_dir: Path,
    prompt: str,
) -> list[str]:
    """Build a TTY-owning agent command with LoopForge's prompt injected once."""

    if not prompt.strip():
        raise ValueError("interactive adapter prompt must not be empty")
    require_interactive_adapter(adapter)
    if adapter == "codex":
        args = list(adapter_args)
        if args[:1] in (["exec"], ["e"]):
            args = args[1:]
        args = _without_options(
            args,
            flags={
                "--json",
                "-",
                "--dangerously-bypass-approvals-and-sandbox",
                "--dangerously-bypass-hook-trust",
                "--yolo",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
            },
            value_options={
                "--color",
                "-C",
                "--cd",
                "-s",
                "--sandbox",
                "--add-dir",
                "--output-schema",
                "-o",
                "--output-last-message",
            },
        )
        args.extend(["-s", "workspace-write", "--cd", str(workspace_dir)])
        return [AGENT_COMMANDS[adapter], *args, prompt]
    if adapter == "claude-code":
        args = _without_options(
            adapter_args,
            flags={
                "-p",
                "--print",
                "--allow-dangerously-skip-permissions",
                "--dangerously-skip-permissions",
                "--include-hook-events",
                "--include-partial-messages",
                "--no-session-persistence",
                "--replay-user-messages",
            },
            value_options={
                "--input-format",
                "--output-format",
                "--max-turns",
                "--fallback-model",
                "--json-schema",
                "--max-budget-usd",
                "--permission-mode",
            },
            variadic_value_options={"--add-dir"},
        )
        return [AGENT_COMMANDS[adapter], *args, prompt]
    if adapter == "kilo-code":
        args = list(adapter_args)
        if args[:1] == ["run"]:
            args = args[1:]
        args = _without_options(
            args,
            flags={
                "-i",
                "--interactive",
                "--auto",
                "--dangerously-skip-permissions",
                "--thinking",
                "--no-thinking",
            },
            value_options={"--attach", "--dir", "--format"},
            variadic_value_options={"--file", "-f"},
        )
        if not any(
            argument == "--agent" or argument.startswith("--agent=")
            for argument in args
        ):
            args.extend(["--agent", DEFAULT_IMPLEMENTATION_AGENT])
        return [
            AGENT_COMMANDS[adapter],
            "run",
            "--interactive",
            "--dir",
            str(workspace_dir),
            *args,
            prompt,
        ]
    if adapter == "opencode":
        args = list(adapter_args)
        if args[:1] == ["run"]:
            args = args[1:]
        args = _without_options(
            args,
            flags={"--auto", "--share", "--thinking"},
            value_options={
                "--prompt",
                "-p",
                "--command",
                "--format",
                "--title",
                "--attach",
                "--dir",
                "--password",
                "--username",
                "--variant",
            },
            variadic_value_options={"--file", "-f"},
        )
        return [AGENT_COMMANDS[adapter], *args, "--prompt", prompt]
    raise AssertionError(f"interactive command builder is missing for {adapter}")


def interactive_implementation_command(
    *,
    adapter: str,
    adapter_args: Sequence[str],
    workspace_dir: Path,
    prompt: str,
) -> list[str]:
    """Build the interactive implementation command."""

    return interactive_agent_command(
        adapter=adapter,
        adapter_args=adapter_args,
        workspace_dir=workspace_dir,
        prompt=prompt,
    )


def interactive_stage_command(
    *,
    adapter: str,
    adapter_args: Sequence[str],
    workspace_dir: Path,
    prompt: str,
) -> list[str]:
    """Build an interactive research, plan, or review command.

    Read-only semantics are enforced by LoopForge's before/after snapshots.
    The harness receives workspace-write access solely so it can create the
    controlled stage candidate requested by the prompt.
    """

    return interactive_agent_command(
        adapter=adapter,
        adapter_args=adapter_args,
        workspace_dir=workspace_dir,
        prompt=prompt,
    )
