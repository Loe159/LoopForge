"""Kilo Code CLI argument helpers shared by bounded adapter runners."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

DEFAULT_IMPLEMENTATION_AGENT = "code"
DEFAULT_READONLY_AGENT = "ask"


def is_kilo_command(command: Sequence[str]) -> bool:
    """Return whether *command* invokes the Kilo Code CLI."""

    return bool(command) and Path(command[0]).name.lower() in {"kilo", "kilo.exe"}


def is_kilo_run_command(command: Sequence[str]) -> bool:
    """Return whether *command* is Kilo's documented headless run command."""

    return is_kilo_command(command) and len(command) >= 2 and command[1] == "run"


def headless_run_command(
    arguments: Sequence[str],
    *,
    default_agent: str,
) -> list[str]:
    """Build one non-interactive Kilo command with an explicit safe default agent."""

    prepared = list(arguments)
    if prepared[:1] == ["run"]:
        prepared = prepared[1:]
    if not any(argument == "--agent" or argument.startswith("--agent=") for argument in prepared):
        prepared.extend(["--agent", default_agent])
    return ["kilo", "run", *prepared]


def command_with_prompt(command: Sequence[str], prompt: str) -> list[str]:
    """Append *prompt* as Kilo's positional message for ``kilo run``.

    Other commands are preserved unchanged.  Kilo's CLI uses a positional
    message for headless execution, unlike adapters that consume the prompt on
    stdin.
    """

    prepared = list(command)
    if not is_kilo_run_command(prepared):
        return prepared
    if not prompt.strip():
        raise ValueError("kilo-code prompt must not be empty")
    return [*prepared, prompt]
