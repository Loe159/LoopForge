#!/usr/bin/env python3
"""Run one bounded child process with an exact reconstructed environment."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from loopforge.contracts import policy_path

POLICY_PATH = policy_path("parent-environment-isolation.json")

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "parent_environment_credential_isolation_enforcement",
    "mode": "bounded-runtime-enforcement",
    "allowed_parent_variables": [
        "ALLUSERSPROFILE",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    ],
    "codex_windows_runtime_parent_variables": [
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    ],
    "fixed_child_environment": {
        "AGENT_RUNNER_ENVIRONMENT_MODE": "isolated",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    },
    "max_timeout_seconds": 600.0,
    "max_captured_output_bytes": 131072,
    "capture_chunk_bytes": 4096,
    "max_pending_capture_chunks": 4,
    "cleanup_timeout_seconds": 2.0,
    "require_absolute_executable": True,
    "require_existing_working_directory": True,
    "forbid_windows_app_execution_alias": True,
    "forbid_shell": True,
    "forbid_parent_stdin": True,
    "allow_controlled_stdin": True,
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Parent-environment isolation policy does not match")
    return policy


def parent_name_index(parent: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name in parent:
        if not isinstance(name, str):
            raise ValueError("Parent environment names must be strings")
        folded = name.upper()
        if folded in normalized:
            raise ValueError("Parent environment contains duplicate case-insensitive names")
        normalized[folded] = name
    return normalized


def select_allowed_parent_environment(
    parent: Mapping[str, str],
    policy: dict[str, Any],
) -> dict[str, str]:
    """Select allowed variables and prefer canonical uppercase duplicates."""
    allowed = {
        str(name).upper()
        for name in policy.get("allowed_parent_variables", [])
        if isinstance(name, str)
    }
    selected: dict[str, tuple[str, str]] = {}
    for name, value in parent.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        folded = name.upper()
        if folded not in allowed:
            continue
        current = selected.get(folded)
        if current is None or name == folded:
            selected[folded] = (name, value)
    return {name: value for name, value in selected.values()}


def build_child_environment(
    parent: Mapping[str, str],
    policy: dict[str, Any],
) -> dict[str, str]:
    names = parent_name_index(parent)
    child: dict[str, str] = {}
    for name in policy["allowed_parent_variables"]:
        if name not in names:
            continue
        value = parent[names[name]]
        if not isinstance(value, str):
            raise ValueError("Allowed parent environment values must be strings")
        child[name] = value
    for name, value in policy["fixed_child_environment"].items():
        if name in child:
            raise ValueError("Fixed child environment overlaps an inherited variable")
        child[name] = value
    return child


def codex_windows_runtime_environment(
    parent: Mapping[str, str],
    policy: dict[str, Any],
    *,
    windows: bool | None = None,
) -> dict[str, str]:
    """Return the small, path-only Codex runtime extension on Windows.

    These variables identify Windows profile/runtime directories; they do not
    inherit credential values, proxy settings, or arbitrary parent variables.
    Codex needs them to start its workspace sandbox helper.  Values must name
    existing absolute directories so a malformed parent environment is blocked
    before an adapter attempt begins.
    """

    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return {}
    names = parent_name_index(parent)
    runtime_names = policy.get("codex_windows_runtime_parent_variables", [])
    if not isinstance(runtime_names, list) or runtime_names != [
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    ]:
        raise ValueError("Codex Windows runtime environment policy does not match")
    runtime: dict[str, str] = {}
    for name in runtime_names:
        if name not in names:
            raise ValueError(f"Codex Windows runtime requires {name}")
        value = parent[names[name]]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Codex Windows runtime {name} must be a non-empty path")
        path = Path(value)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError(
                f"Codex Windows runtime {name} must be an existing absolute directory"
            )
        runtime[name] = value
    return runtime


def build_codex_windows_child_environment(
    parent: Mapping[str, str],
    policy: dict[str, Any],
    *,
    windows: bool | None = None,
) -> dict[str, str]:
    """Build a normal isolated environment plus validated Codex runtime paths."""

    child = build_child_environment(parent, policy)
    child.update(codex_windows_runtime_environment(parent, policy, windows=windows))
    return child


def is_windows_app_execution_alias(path: Path) -> bool:
    normalized = str(path).replace("/", "\\").upper()
    return "\\APPDATA\\LOCAL\\MICROSOFT\\WINDOWSAPPS\\" in normalized


def resolve_child_executable(command: Sequence[str]) -> list[str]:
    """Resolve a command name to the executable selected by the current PATH.

    Windows does not resolve ``kilo`` to the npm-installed ``kilo.cmd`` when
    ``subprocess`` is invoked with ``shell=False``.  Resolve it before the
    isolated process is started, preserving the no-shell execution boundary.
    """

    if not command:
        raise ValueError("Child command must not be empty")
    resolved = list(command)
    executable = Path(resolved[0])
    if not executable.is_absolute():
        found = shutil.which(resolved[0])
        if not found:
            raise FileNotFoundError(f"agent executable not found: {resolved[0]}")
        executable = Path(found)
    try:
        executable = executable.resolve(strict=True)
    except OSError as error:
        raise FileNotFoundError(f"agent executable not found: {resolved[0]}") from error
    if not executable.is_file():
        raise FileNotFoundError(f"agent executable is not a regular file: {resolved[0]}")
    resolved[0] = str(executable)
    return resolved


def validate_command(command: Sequence[str], cwd: Path, policy: dict[str, Any]) -> list[str]:
    if (
        isinstance(command, (str, bytes))
        or not command
        or any(not isinstance(part, str) or not part or "\x00" in part for part in command)
    ):
        raise ValueError("Child command must be a non-empty sequence of non-empty strings")
    executable = Path(command[0])
    if policy["require_absolute_executable"] and not executable.is_absolute():
        raise ValueError("Child executable must be an absolute path")
    if executable.is_symlink() or not executable.is_file():
        raise ValueError("Child executable must be an existing regular file")
    if policy["forbid_windows_app_execution_alias"] and is_windows_app_execution_alias(
        executable.resolve()
    ):
        raise ValueError("Windows App Execution Alias executables are not allowed")
    if cwd.is_symlink():
        raise ValueError("Child working directory symlinks are not allowed")
    if policy["require_existing_working_directory"] and not cwd.resolve().is_dir():
        raise ValueError("Child working directory must be an existing directory")
    return list(command)


def run(
    command: Sequence[str],
    cwd: Path,
    parent_environment: Mapping[str, str],
    policy: dict[str, Any],
    timeout_seconds: float,
    prompt: bytes | None = None,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or timeout_seconds > policy["max_timeout_seconds"]
    ):
        raise ValueError("Child timeout exceeds the bounded isolation policy")
    exact_command = validate_command(command, cwd, policy)
    if prompt is not None:
        if not policy.get("allow_controlled_stdin"):
            raise ValueError("Isolation policy does not allow controlled prompt stdin")
        if not isinstance(prompt, bytes):
            raise ValueError("Controlled prompt stdin must be bytes")
        if len(prompt) > policy["max_captured_output_bytes"]:
            raise ValueError("Controlled prompt stdin exceeds the bounded input limit")
    cwd = cwd.resolve()
    child_environment = build_child_environment(parent_environment, policy)
    memory_bound = policy["max_captured_output_bytes"] + (
        policy["capture_chunk_bytes"]
        * (policy["max_pending_capture_chunks"] + 3)
    )
    try:
        process = popen(
            exact_command,
            cwd=cwd,
            env=child_environment,
            stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
        )
    except OSError:
        return {
            "completed": False,
            "timed_out": False,
            "output_limit_exceeded": False,
            "kill_requested": False,
            "direct_child_reaped": False,
            "returncode": None,
            "stdout": b"",
            "stderr": b"",
            "capture_complete": False,
            "captured_stdout_bytes": 0,
            "captured_stderr_bytes": 0,
            "capture_memory_bound_bytes": memory_bound,
        }
    if process.stdout is None or process.stderr is None:
        raise ValueError("Child process pipes were not created")

    def write_prompt() -> None:
        if prompt is None or process.stdin is None:
            return
        try:
            process.stdin.write(prompt)
            process.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

    events: queue.Queue[tuple[str, bytes | None]] = queue.Queue(
        maxsize=policy["max_pending_capture_chunks"]
    )
    stopped = threading.Event()

    def pump(name: str, stream: Any) -> None:
        try:
            while not stopped.is_set():
                chunk = stream.read(policy["capture_chunk_bytes"])
                if not chunk:
                    break
                while not stopped.is_set():
                    try:
                        events.put((name, chunk), timeout=0.05)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            pass
        finally:
            while not stopped.is_set():
                try:
                    events.put((name, None), timeout=0.05)
                    break
                except queue.Full:
                    continue

    threads = [
        threading.Thread(target=pump, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=pump, args=("stderr", process.stderr), daemon=True),
    ]
    prompt_thread = threading.Thread(target=write_prompt, daemon=True) if prompt is not None else None
    if prompt_thread is not None:
        prompt_thread.start()
    for thread in threads:
        thread.start()

    started = clock()
    deadline = started + timeout_seconds
    active_streams = 2
    stdout = bytearray()
    stderr = bytearray()
    timed_out = False
    output_limit_exceeded = False
    kill_requested = False
    direct_child_reaped = False
    returncode: int | None = None
    while active_streams:
        remaining = deadline - clock()
        if remaining <= 0:
            timed_out = True
            break
        try:
            name, chunk = events.get(timeout=min(remaining, 0.05))
        except queue.Empty:
            continue
        if chunk is None:
            active_streams -= 1
            continue
        if len(stdout) + len(stderr) + len(chunk) > policy["max_captured_output_bytes"]:
            output_limit_exceeded = True
            break
        (stdout if name == "stdout" else stderr).extend(chunk)

    if not timed_out and not output_limit_exceeded:
        remaining = deadline - clock()
        if remaining <= 0:
            timed_out = True
        else:
            try:
                returncode = process.wait(timeout=remaining)
                direct_child_reaped = True
            except subprocess.TimeoutExpired:
                timed_out = True
            except OSError:
                pass
    if timed_out or output_limit_exceeded:
        stopped.set()
        try:
            process.kill()
            kill_requested = True
        except OSError:
            pass
    if not direct_child_reaped:
        try:
            returncode = process.wait(timeout=policy["cleanup_timeout_seconds"])
            direct_child_reaped = True
        except (OSError, subprocess.TimeoutExpired):
            stopped.set()
            try:
                process.kill()
                kill_requested = True
                returncode = process.wait(timeout=policy["cleanup_timeout_seconds"])
                direct_child_reaped = True
            except (OSError, subprocess.TimeoutExpired):
                pass
    stopped.set()
    process.stdout.close()
    process.stderr.close()
    for thread in threads:
        thread.join(timeout=policy["cleanup_timeout_seconds"])
    if prompt_thread is not None:
        prompt_thread.join(timeout=policy["cleanup_timeout_seconds"])

    capture_complete = (
        active_streams == 0
        and not timed_out
        and not output_limit_exceeded
        and direct_child_reaped
        and all(not thread.is_alive() for thread in threads)
    )
    return {
        "completed": direct_child_reaped and not timed_out and not output_limit_exceeded,
        "timed_out": timed_out,
        "output_limit_exceeded": output_limit_exceeded,
        "kill_requested": kill_requested,
        "direct_child_reaped": direct_child_reaped,
        "returncode": returncode,
        "stdout": bytes(stdout) if capture_complete else b"",
        "stderr": bytes(stderr) if capture_complete else b"",
        "capture_complete": capture_complete,
        "captured_stdout_bytes": len(stdout),
        "captured_stderr_bytes": len(stderr),
        "capture_memory_bound_bytes": memory_bound,
    }
