"""Kilo Code CLI argument helpers shared by bounded adapter runners."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

DEFAULT_IMPLEMENTATION_AGENT = "code"
DEFAULT_READONLY_AGENT = "ask"


def is_kilo_command(command: Sequence[str]) -> bool:
    """Return whether *command* invokes the Kilo Code CLI."""

    return bool(command) and Path(command[0]).name.lower() in {
        "kilo",
        "kilo.exe",
        "kilo.cmd",
    }


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


def command_without_windows_batch_launcher(command: Sequence[str]) -> list[str]:
    """Bypass ``kilo.cmd`` so multiline prompt arguments remain intact.

    Python starts Windows batch launchers through ``cmd.exe`` even with
    ``shell=False``. Newlines inside a positional argument are then truncated,
    so Kilo receives only the first line of a LoopForge prompt. Invoke the
    packaged JavaScript entry point with Node directly while preserving the
    exact argument list and the no-shell boundary.
    """

    prepared = list(command)
    if not prepared or Path(prepared[0]).name.lower() != "kilo.cmd":
        return prepared
    launcher = Path(prepared[0]).resolve(strict=True)
    entrypoint = launcher.parent / "node_modules" / "@kilocode" / "cli" / "bin" / "kilo"
    if not entrypoint.is_file():
        raise FileNotFoundError(f"Kilo Code entry point not found: {entrypoint}")
    node = launcher.with_name("node.exe")
    if not node.is_file():
        found = shutil.which("node.exe") or shutil.which("node")
        if not found:
            raise FileNotFoundError("Node.js executable not found for kilo.cmd")
        node = Path(found)
    return [
        str(node.resolve(strict=True)),
        str(entrypoint.resolve(strict=True)),
        *prepared[1:],
    ]
