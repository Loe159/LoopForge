#!/usr/bin/env python3
"""Run one local implementation command and emit the runner result JSON contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Sequence


CHECKS_DIR = Path(__file__).resolve().parents[1] / "checks"
if str(CHECKS_DIR) not in sys.path:
    sys.path.insert(0, str(CHECKS_DIR))

import validate_implementation_result
import isolated_process


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / ".agent" / "policies" / "local-implementation-adapter.json"

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "local_implementation_adapter",
    "mode": "agent-command-wrapper",
    "command_timeout_seconds": 540,
    "max_child_output_bytes": 32768,
    "max_summary_chars": 240,
    "require_clean_workspace_at_start": True,
    "require_expected_session_workspace_match": True,
    "ignored_workspace_status_prefixes": [".loopforge/"],
    "allowed_command_basenames": [
        "aider",
        "aider.exe",
        "claude",
        "claude.exe",
        "claude-code",
        "claude-code.exe",
        "codex",
        "codex.exe",
        "mini-swe-agent",
        "mini-swe-agent.exe",
        "opencode",
        "opencode.exe",
    ],
    "fixture_command_basenames": ["python", "python.exe", "python3"],
    "fixture_runner_ids": ["local-adapter-fixture"],
    "use_isolated_child_environment": True,
    "bindings": [
        ".agent/adapters/local_implementation_adapter.py",
        ".agent/policies/local-implementation-adapter.json",
        ".agent/checks/isolated_process.py",
        ".agent/policies/parent-environment-isolation.json",
        ".agent/checks/validate_implementation_result.py",
        ".agent/policies/implementation-result-validation.json",
        ".agent/schemas/implementation-result.schema.json",
    ],
    "stream_child_output": True,
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Local implementation adapter policy does not match")
    return policy


def run_git(workspace: Path, *args: str) -> bytes:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={workspace.resolve().as_posix()}",
            "-C",
            str(workspace),
            *args,
        ],
        check=False,
        capture_output=True,
        shell=False,
    )
    if completed.returncode != 0:
        raise ValueError("Local implementation adapter git command failed")
    return completed.stdout


def git_status_paths(workspace: Path) -> list[str]:
    output = run_git(workspace, "status", "--porcelain=v1", "--untracked-files=all")
    paths: list[str] = []
    for raw_line in output.decode("utf-8", errors="replace").splitlines():
        if not raw_line:
            continue
        path = raw_line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        paths.append(path.replace("\\", "/"))
    return paths


def workspace_dirty(workspace: Path, policy: dict[str, Any]) -> bool:
    ignored_prefixes = tuple(policy["ignored_workspace_status_prefixes"])
    return any(
        not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in ignored_prefixes)
        for path in git_status_paths(workspace)
    )


def command_basename(command: Sequence[str]) -> str:
    if not command:
        raise ValueError("Local implementation adapter command is required")
    name = Path(command[0]).name.lower()
    if not name:
        raise ValueError("Local implementation adapter command is invalid")
    return name


def validate_command_allowed(
    command: Sequence[str],
    session: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    name = command_basename(command)
    if name in policy["allowed_command_basenames"]:
        return
    if (
        name in policy["fixture_command_basenames"]
        and session["runner_id"] in policy["fixture_runner_ids"]
    ):
        return
    raise ValueError("Local implementation adapter command is not allowlisted")


def bounded_text(value: bytes, limit: int) -> str:
    text = value[:limit].decode("utf-8", errors="replace")
    text = " ".join(text.split())
    return text


def summary_for(
    status: str,
    completed: subprocess.CompletedProcess[bytes] | None,
    timed_out: bool,
    changed: bool,
    policy: dict[str, Any],
) -> str:
    if timed_out:
        text = "Implementation command timed out."
    elif completed is None:
        text = "Implementation command was not run."
    elif completed.returncode != 0:
        text = f"Implementation command failed with return code {completed.returncode}."
    elif status == "blocked":
        text = "Implementation command completed without workspace changes."
    elif changed:
        text = "Implementation command completed and changed the workspace."
    else:
        text = "Implementation command completed."
    return text[: policy["max_summary_chars"]]


def result_value(
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
        "summary": summary,
        "workspace_changed": workspace_changed,
        "patch_generated": False,
        "deterministic_checks_run": False,
        "publication_requested": False,
        "network_requested": False,
        "next_action": "deterministic_patch_generation"
        if status == "completed"
        else "human_review",
    }


def run_adapter(
    expected_session: Path,
    command: Sequence[str],
    workspace: Path,
    policy: dict[str, Any],
    stdin_file: Path | None = None,
    stream_output: bool = False,
) -> bytes:
    if not command:
        raise ValueError("Local implementation adapter command is required")
    session = validate_implementation_result.validate_expected_session(
        json.loads(expected_session.read_text(encoding="utf-8"))
    )
    workspace = workspace.resolve()
    if policy["require_expected_session_workspace_match"] and str(workspace) != session["workspace"]:
        raise ValueError("Adapter workspace does not match expected session")
    validate_command_allowed(command, session, policy)
    if policy["require_clean_workspace_at_start"] and workspace_dirty(workspace, policy):
        value = result_value(
            session,
            "failed",
            "Workspace was not clean before implementation command.",
            False,
        )
        return validate_implementation_result.canonical_result_bytes(value)

    completed: subprocess.CompletedProcess[bytes] | None = None
    timed_out = False
    try:
        stdin_handle = stdin_file.open("rb") if stdin_file is not None else None
        process = subprocess.Popen(
            list(command),
            cwd=workspace,
            stdin=stdin_handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=isolated_process.build_child_environment(
                os.environ,
                isolated_process.load_policy(),
            ),
        )
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()

        def read_available(source) -> bytes:  # type: ignore[no-untyped-def]
            if hasattr(source, "read1"):
                return source.read1(4096)
            return source.read(1)

        def pump(source, target, buffer: bytearray) -> None:  # type: ignore[no-untyped-def]
            try:
                while True:
                    chunk = read_available(source)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if stream_output and policy["stream_child_output"]:
                        target.buffer.write(chunk)
                        target.buffer.flush()
            finally:
                source.close()

        stdout_thread = threading.Thread(
            target=pump,
            args=(process.stdout, sys.stdout, stdout_buffer),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=pump,
            args=(process.stderr, sys.stderr, stderr_buffer),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            returncode = process.wait(timeout=policy["command_timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            returncode = process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if stdin_handle is not None:
            stdin_handle.close()
        completed = subprocess.CompletedProcess(
            list(command),
            returncode=returncode,
            stdout=bytes(stdout_buffer),
            stderr=bytes(stderr_buffer),
        )
    except subprocess.TimeoutExpired as error:
        timed_out = True
        completed = subprocess.CompletedProcess(
            list(command),
            returncode=124,
            stdout=(error.stdout or b""),
            stderr=(error.stderr or b""),
        )

    output_size = len(completed.stdout or b"") + len(completed.stderr or b"")
    changed = workspace_dirty(workspace, policy)
    if timed_out or completed.returncode != 0 or output_size > policy["max_child_output_bytes"]:
        status = "failed"
    elif changed:
        status = "completed"
    else:
        status = "blocked"
    summary = summary_for(status, completed, timed_out, changed, policy)
    if output_size > policy["max_child_output_bytes"]:
        summary = "Implementation command exceeded the adapter output limit."
    value = result_value(session, status, summary, changed)
    return validate_implementation_result.canonical_result_bytes(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-session", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--stdin-file", type=Path)
    parser.add_argument("--result-output", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    elif command and command[0].startswith("--"):
        print(
            "local-implementation-adapter: ERROR\n- adapter command options must follow --",
            file=sys.stderr,
        )
        return 1
    try:
        content = run_adapter(
            args.expected_session,
            command,
            args.workspace,
            load_policy(),
            stdin_file=args.stdin_file,
            stream_output=args.result_output is not None,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"local-implementation-adapter: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.result_output is not None:
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        args.result_output.write_bytes(content)
    else:
        sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
