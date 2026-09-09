#!/usr/bin/env python3
"""Mirror one interactive Windows harness to its console and LoopForge parent."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import sys
import threading
import time
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence


TERMINAL_BRIDGE_AUTHKEY = b"loopforge-terminal-bridge-v1"


class PtyProcessLike(Protocol):
    """Small pywinpty surface used by the bridge and its tests."""

    def read(self, size: int = 1024) -> str: ...

    def write(self, value: str) -> int: ...

    def isalive(self) -> bool: ...

    def wait(self) -> int: ...

    def sendintr(self) -> object: ...

    def setwinsize(self, rows: int, cols: int) -> object: ...


ProcessFactory = Callable[
    [Sequence[str], str, dict[str, str], tuple[int, int]], PtyProcessLike
]


_EXTENDED_KEYS = {
    "H": "\x1b[A",
    "P": "\x1b[B",
    "M": "\x1b[C",
    "K": "\x1b[D",
    "G": "\x1b[H",
    "O": "\x1b[F",
    "I": "\x1b[5~",
    "Q": "\x1b[6~",
    "R": "\x1b[2~",
    "S": "\x1b[3~",
}


def _confined_path(parent: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"terminal bridge {label} must be a non-empty path")
    candidate = Path(raw).resolve()
    try:
        candidate.relative_to(parent)
    except ValueError:
        raise ValueError(f"terminal bridge {label} escapes its artifacts directory") from None
    return candidate


def _load_request(request_path: Path) -> dict[str, Any]:
    artifacts_dir = request_path.resolve().parent
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("terminal bridge request must be an object")
    command = payload.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part or "\x00" in part for part in command)
    ):
        raise ValueError("terminal bridge command must contain non-empty strings")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("terminal bridge executable must be an existing absolute file")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).resolve().is_dir():
        raise ValueError("terminal bridge cwd must be an existing directory")
    pipe_name = payload.get("pipe_name")
    if not isinstance(pipe_name, str) or not pipe_name.startswith("\\\\.\\pipe\\loopforge-"):
        raise ValueError("terminal bridge pipe name is invalid")
    payload["command"] = command
    payload["cwd"] = str(Path(cwd).resolve())
    payload["start_path"] = _confined_path(
        artifacts_dir, payload.get("start_path"), "start path"
    )
    payload["error_path"] = _confined_path(
        artifacts_dir, payload.get("error_path"), "error path"
    )
    return payload


def _default_process_factory(
    command: Sequence[str],
    cwd: str,
    environment: dict[str, str],
    dimensions: tuple[int, int],
) -> PtyProcessLike:
    try:
        from winpty import PtyProcess
    except ImportError as error:
        raise RuntimeError(
            "pywinpty is required to mirror an interactive Windows harness"
        ) from error
    return PtyProcess.spawn(
        list(command),
        cwd=cwd,
        env=environment,
        dimensions=dimensions,
    )


def _console_dimensions() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return max(1, size.lines), max(1, size.columns)


def _set_console_title(title: object) -> None:
    if os.name != "nt" or not isinstance(title, str) or not title:
        return
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except (AttributeError, OSError):
        return


def _input_loop(process: PtyProcessLike) -> None:
    if os.name != "nt" or not sys.stdin.isatty():
        return
    import msvcrt

    while process.isalive():
        try:
            character = msvcrt.getwch()
        except KeyboardInterrupt:
            process.sendintr()
            continue
        if character in {"\x00", "\xe0"}:
            character = _EXTENDED_KEYS.get(msvcrt.getwch(), "")
        if not character:
            continue
        try:
            process.write(character)
        except (EOFError, OSError):
            return


def _resize_loop(process: PtyProcessLike) -> None:
    dimensions = _console_dimensions()
    while process.isalive():
        updated = _console_dimensions()
        if updated != dimensions:
            try:
                process.setwinsize(*updated)
            except (EOFError, OSError):
                return
            dimensions = updated
        time.sleep(0.25)


def mirror_process(
    process: PtyProcessLike,
    connection: Connection,
    *,
    output: Any = None,
    start_input: bool = True,
) -> int:
    """Copy every PTY chunk to the visible console and authenticated pipe."""

    if output is None:
        output = sys.stdout
    if start_input:
        threading.Thread(target=_input_loop, args=(process,), daemon=True).start()
        threading.Thread(target=_resize_loop, args=(process,), daemon=True).start()
    while True:
        try:
            chunk = process.read(4096)
        except KeyboardInterrupt:
            process.sendintr()
            continue
        except EOFError:
            break
        if not chunk:
            continue
        output.write(chunk)
        output.flush()
        try:
            connection.send_bytes(chunk.encode("utf-8", errors="replace"))
        except (BrokenPipeError, EOFError, OSError):
            # The visible console remains useful if its parent UI disappears.
            pass
    return int(process.wait() or 0)


def run_bridge(
    request_path: Path,
    *,
    process_factory: ProcessFactory = _default_process_factory,
) -> int:
    payload = _load_request(request_path)
    _set_console_title(payload.get("title"))
    start_path = payload["start_path"]
    deadline = time.monotonic() + 30.0
    while not start_path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("terminal bridge was not released by its parent")
        time.sleep(0.025)
    connection = Client(
        payload["pipe_name"],
        family="AF_PIPE",
        authkey=TERMINAL_BRIDGE_AUTHKEY,
    )
    try:
        dimensions = _console_dimensions()
        process = process_factory(
            payload["command"],
            payload["cwd"],
            dict(os.environ),
            dimensions,
        )
        return mirror_process(process, connection)
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    request_path = Path(_parser().parse_args(argv).request)
    try:
        return run_bridge(request_path)
    except BaseException as error:
        try:
            payload = _load_request(request_path)
            error_path = payload["error_path"]
            error_path.write_text(
                f"{type(error).__name__}: {error}\n",
                encoding="utf-8",
            )
        except BaseException:
            pass
        print(f"LoopForge terminal bridge failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
