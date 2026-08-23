"""Adapter command building and bounded process execution for LoopForge runs.

Owns adapter command construction (``command_for_adapter``,
``command_for_readonly_stage``, ``command_for_attempt``), the bounded adapter
process execution paths (``run_streaming_process``, ``run_with_isolated_process``,
``execute_adapter_command``, ``execute_readonly_adapter_command``,
``execute_fixture_command``), adapter result parsing and validation
(``parse_adapter_result``, ``parse_adapter_result_file``,
``validate_attempt_result``, ``synthetic_adapter_result``), operation-event
emission helpers (``emit_operation_event``, ``emit_adapter_output``), and the
pack/JSON check runners (``run_pack_check``, ``run_json_check``).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; ``ProcessRunner`` and
``OperationCallback`` are safe top-level imports.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from loopforge.adapters.commands import adapter_command, headless_implementation_command
from loopforge.engine.process_runner import ProcessRunner
from loopforge.engine.execution import OperationCallback


def command_for_adapter(adapter: str, adapter_args: list[str]) -> list[str]:
    return adapter_command(adapter, adapter_args)


def command_for_readonly_stage(
    *,
    adapter: str,
    adapter_args: list[str],
    workspace_dir: Path,
    run_dir: Path | None = None,
) -> list[str]:
    from loopforge.engine import DEFAULT_READONLY_AGENT, kilo_headless_run_command

    if adapter == "local-adapter-fixture":
        return command_for_adapter(adapter, adapter_args)
    if adapter == "codex":
        args = list(adapter_args)
        if not args:
            args = ["exec"]
        elif args[0] not in {"exec", "e"}:
            args = ["exec", *args]
        for flag in ("-s", "--sandbox"):
            if flag in args:
                index = args.index(flag)
                if index + 1 < len(args):
                    args[index + 1] = "read-only"
                break
        else:
            args[1:1] = ["-s", "read-only"]
        if "-C" not in args and "--cd" not in args:
            args[1:1] = ["--cd", str(workspace_dir)]
        if run_dir is not None and "--add-dir" not in args:
            args[1:1] = ["--add-dir", str(run_dir)]
        if "--color" not in args:
            args[1:1] = ["--color", "never"]
        args = [value for value in args if value != "--json"]
        if "-" not in args:
            args.append("-")
        return ["codex", *args]
    if adapter == "claude-code" and not adapter_args:
        return ["claude", "-p", "--permission-mode", "plan"]
    if adapter == "kilo-code":
        return kilo_headless_run_command(
            adapter_args,
            default_agent=DEFAULT_READONLY_AGENT,
        )
    if not adapter_args:
        raise ValueError(f"read-only {adapter} requires non-interactive adapter arguments")
    return command_for_adapter(adapter, adapter_args)


def resolve_child_executable(command: list[str]) -> list[str]:
    """Return a command whose executable is an absolute, non-symlink file."""

    from loopforge.engine import isolated_process_module

    return isolated_process_module().resolve_child_executable(command)


def execute_readonly_adapter_command(
    *,
    command: list[str],
    prompt: bytes,
    project_dir: Path,
    timeout_seconds: int,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[dict[str, Any], bytes, bytes]:
    """Run a read-only adapter with bounded, observable output.

    Read-only stages still use the same isolated environment and command
    validation as before.  Unlike the historical ``subprocess.run`` path, the
    adapter output is forwarded as factual operation events while it runs.
    """

    from loopforge.engine import (
        is_kilo_run_command,
        isolated_process_module,
        kilo_command_with_prompt,
        kilo_command_without_windows_batch_launcher,
    )

    resolved = resolve_child_executable(command)
    kilo_prompted = is_kilo_run_command(resolved)
    prepared_command = (
        kilo_command_with_prompt(resolved, decode_output(prompt)) if kilo_prompted else resolved
    )
    if kilo_prompted:
        prepared_command = kilo_command_without_windows_batch_launcher(prepared_command)
    isolated = isolated_process_module()
    policy = isolated.load_policy()
    isolated.validate_command(prepared_command, project_dir, policy)
    child = run_streaming_process(
        prepared_command,
        project_dir,
        timeout_seconds,
        output_callback=operation_callback,
        cancel_event=cancel_event,
        stream_output=operation_callback is None,
        input_bytes=None if kilo_prompted else prompt,
        codex_windows_runtime=Path(resolved[0]).stem.casefold() == "codex",
    )
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def command_for_attempt(
    *,
    adapter: str,
    adapter_args: list[str],
    workspace_dir: Path | None = None,
    run_dir: Path | None = None,
) -> list[str]:
    del run_dir
    return headless_implementation_command(
        adapter=adapter,
        adapter_args=adapter_args,
        workspace_dir=workspace_dir,
    )


def validate_attempt_result(
    result: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    from loopforge.engine import validate_implementation_result

    expected_session = validate_implementation_result.validate_expected_session(session)
    validated = validate_implementation_result.validate_result(result)
    mismatched = sorted(
        key for key, value in expected_session.items() if validated.get(key) != value
    )
    if mismatched:
        raise ValueError(
            "Implementation result session mismatch: " + ", ".join(mismatched)
        )
    return validated


def decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def synthetic_adapter_result(
    *,
    session: dict[str, Any],
    status: str,
    summary: str,
    workspace_changed: bool,
) -> dict[str, Any]:
    return {
        "result_version": 1,
        "purpose": "implementation_session_result",
        "mode": "untrusted-runner-output",
        "status": status,
        **session,
        "summary": summary[:1000] or "Adapter execution did not produce a summary.",
        "workspace_changed": workspace_changed,
        "patch_generated": False,
        "deterministic_checks_run": False,
        "publication_requested": False,
        "network_requested": False,
        "next_action": "deterministic_patch_generation"
        if status == "completed"
        else "human_review",
    }


def run_with_isolated_process(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    *,
    prompt: bytes | None = None,
) -> dict[str, Any]:
    from loopforge.engine import isolated_process_module

    isolated_process = isolated_process_module()
    policy = isolated_process.load_policy()
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    return isolated_process.run(
        command,
        cwd,
        isolated_process.select_allowed_parent_environment(os.environ, policy),
        policy,
        timeout_seconds=bounded_timeout,
        prompt=prompt,
    )


def emit_operation_event(
    callback: OperationCallback | None,
    kind: str,
    message: str,
    **details: Any,
) -> None:
    """Publish factual work boundaries without making the engine UI-aware."""

    if callback is not None:
        callback({"kind": kind, "message": message, **details})


def emit_adapter_output(
    callback: OperationCallback | None,
    stage: str,
    stream: str,
    output: bytes,
) -> None:
    """Expose bounded adapter output through operation events, never terminal streams."""

    if callback is None:
        return
    message = decode_output(output).strip()
    if not message:
        return
    limit = 1200
    if len(message) > limit:
        message = message[: limit - 3] + "..."
    emit_operation_event(callback, "adapter_output", f"{stage} {stream}: {message}")


def run_streaming_process(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    *,
    output_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
    stream_output: bool = False,
    input_bytes: bytes | None = None,
    codex_windows_runtime: bool = False,
) -> dict[str, Any]:
    # Exempt from ProcessRunner: this is the primary adapter execution path
    # which requires live streaming (output_callback, streaming to
    # stderr/stdout). ProcessRunner is for bounded non-interactive subprocess
    # checks and Git queries. The low-level isolation policy is still enforced
    # via isolated_process.
    if cancel_event is not None and cancel_event.is_set():
        return {
            "completed": False,
            "returncode": None,
            "timed_out": False,
            "interrupted": True,
            "output_limit_exceeded": False,
            "stdout": b"",
            "stderr": b"",
        }

    from loopforge.engine import isolated_process_module

    isolated_process = isolated_process_module()
    policy = isolated_process.load_policy()
    if input_bytes is not None:
        if not bool(policy.get("allow_controlled_stdin")):
            raise ValueError("Isolation policy does not allow controlled prompt stdin")
        if not isinstance(input_bytes, bytes):
            raise ValueError("Controlled prompt stdin must be bytes")
        if len(input_bytes) > int(policy["max_captured_output_bytes"]):
            raise ValueError("Controlled prompt stdin exceeds the bounded input limit")
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    env = (
        isolated_process.build_codex_windows_child_environment(os.environ, policy)
        if codex_windows_runtime
        else isolated_process.build_child_environment(
            isolated_process.select_allowed_parent_environment(os.environ, policy),
            policy,
        )
    )
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def read_available(source) -> bytes:  # type: ignore[no-untyped-def]
        if hasattr(source, "read1"):
            return source.read1(4096)
        return source.read(1)

    def pump(source, target, buffer: bytearray, stream: str) -> None:  # type: ignore[no-untyped-def]
        try:
            while True:
                chunk = read_available(source)
                if not chunk:
                    break
                buffer.extend(chunk)
                if output_callback is not None:
                    emit_adapter_output(output_callback, "adapter", stream, chunk)
                elif stream_output:
                    binary_target = getattr(target, "buffer", None)
                    if binary_target is not None:
                        binary_target.write(chunk)
                        binary_target.flush()
                    else:
                        target.write(decode_output(chunk))
                        target.flush()
        finally:
            source.close()

    stdout_thread = threading.Thread(
        target=pump,
        args=(process.stdout, sys.stdout, stdout_buffer, "stdout"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=pump,
        args=(process.stderr, sys.stderr, stderr_buffer, "stderr"),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    input_thread: threading.Thread | None = None
    if input_bytes is not None:
        def feed_input() -> None:
            try:
                if process.stdin is not None:
                    process.stdin.write(input_bytes)
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                if process.stdin is not None:
                    process.stdin.close()

        input_thread = threading.Thread(target=feed_input, daemon=True)
        input_thread.start()
    timed_out = False
    interrupted = False
    try:
        deadline = time.monotonic() + bounded_timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                interrupted = True
                process.terminate()
                try:
                    returncode = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    returncode = process.wait()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, bounded_timeout)
            try:
                returncode = process.wait(timeout=min(remaining, 0.1))
                break
            except subprocess.TimeoutExpired:
                continue
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    except KeyboardInterrupt:
        interrupted = True
        process.terminate()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if input_thread is not None:
        input_thread.join(timeout=5)
    if interrupted and cancel_event is None:
        raise KeyboardInterrupt
    return {
        "completed": not timed_out,
        "returncode": returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "output_limit_exceeded": False,
        "stdout": bytes(stdout_buffer),
        "stderr": bytes(stderr_buffer),
    }


def adapter_protocol_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    workspace_dir: Path,
    stdin_file: Path | None,
    result_output: Path | None,
    child_stderr_output: Path | None = None,
) -> list[str]:
    from loopforge.engine import loopforge_module_command

    protocol = loopforge_module_command(
        "loopforge.adapters.local_implementation_adapter",
        [
            "--expected-session",
            str(expected_session_path),
            "--workspace",
            str(workspace_dir),
        ],
    )
    if stdin_file is not None:
        protocol.extend(["--stdin-file", str(stdin_file)])
    if result_output is not None:
        protocol.extend(["--result-output", str(result_output)])
    if child_stderr_output is not None:
        protocol.extend(["--child-stderr-output", str(child_stderr_output)])
    protocol.extend(["--", *command])
    return protocol


def execute_fixture_command(
    *,
    command: list[str],
    prompt: bytes,
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    resolved_command = resolve_child_executable(command)
    child = run_with_isolated_process(
        resolved_command,
        project_dir,
        timeout_seconds,
        prompt=prompt,
    )
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def execute_adapter_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    workspace_dir: Path,
    stdin_file: Path,
    result_output: Path,
    timeout_seconds: int,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
    stream_output: bool = True,
    child_stderr_output: Path | None = None,
) -> tuple[dict[str, Any], bytes, bytes]:
    from loopforge.engine import repository_root

    protocol_command = adapter_protocol_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=stdin_file,
        result_output=result_output,
        child_stderr_output=child_stderr_output,
    )
    child = run_streaming_process(
        protocol_command,
        repository_root(),
        min(timeout_seconds + 5, 600),
        output_callback=operation_callback,
        cancel_event=cancel_event,
        stream_output=stream_output,
        codex_windows_runtime=adapter == "codex",
    )
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def parse_adapter_result(stdout: bytes) -> dict[str, Any] | None:
    if not stdout.strip():
        return None
    try:
        parsed = json.loads(decode_output(stdout))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_adapter_result_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def pack_check_paths(project_dir: Path, pack: str) -> list[Path]:
    from loopforge.engine import _pack_registry

    return _pack_registry(project_dir).check_paths(pack)


def expand_check_value(
    value: str,
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> str:
    from loopforge.engine import usable_python_executable

    replacements = {
        "{python}": usable_python_executable(),
        "{repo}": str(project_dir),
        "{run_dir}": str(run_dir),
        "{patch}": str(patch_path or ""),
    }
    expanded = value
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    return expanded


def run_pack_check(
    check: dict[str, Any],
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> dict[str, Any]:
    from loopforge.engine import utc_now

    # Exempt from ProcessRunner: pack checks are user-defined scripts
    # that run in the full project environment (os.environ) with
    # variable expansion. Migration would require environment
    # normalization and pack-contract schema updates.
    command = [
        expand_check_value(
            part,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
        for part in check["command"]
    ]
    env = os.environ.copy()
    for key, value in check.get("env", {}).items():
        env[key] = expand_check_value(
            value,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
    started = utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(check["timeout_seconds"]),
            check=False,
        )
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "timed_out",
            "returncode": None,
            "stdout": (error.stdout or "")[-4000:]
            if isinstance(error.stdout, str)
            else "",
            "stderr": (error.stderr or "")[-4000:]
            if isinstance(error.stderr, str)
            else "",
            "timed_out": True,
        }
    except OSError as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "timed_out": False,
        }


def run_json_check(command: list[str], cwd: Path, timeout: int = 60) -> dict[str, Any]:
    # Exempt from ProcessRunner: json-checks are lightweight JSON-output
    # subprocesses (e.g. diff stats, linting) with built-in stdout parsing.
    # Timeout and capture are handled inline; migration would add overhead
    # without isolation benefit since the full parent environment is passed.
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": payload,
    }
