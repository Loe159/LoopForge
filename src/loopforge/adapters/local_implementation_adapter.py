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

from loopforge.adapters.kilo_code import (
    command_without_windows_batch_launcher,
    command_with_prompt,
    is_kilo_command,
)
from loopforge.checks import isolated_process, validate_implementation_result
from loopforge.contracts import policy_path

POLICY_PATH = policy_path("local-implementation-adapter.json")

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "local_implementation_adapter",
    "mode": "agent-command-wrapper",
    "command_timeout_seconds": 540,
    "max_child_output_bytes": 32768,
    "max_summary_chars": 240,
    "require_clean_workspace_at_start": True,
    "allow_dirty_workspace_for_authorized_recovery": True,
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
        "kilo",
        "kilo.exe",
        "mini-swe-agent",
        "mini-swe-agent.exe",
        "opencode",
        "opencode.exe",
    ],
    "fixture_command_basenames": ["python", "python.exe", "python3"],
    "fixture_runner_ids": ["local-adapter-fixture"],
    "use_isolated_child_environment": True,
    "bindings": [
        "loopforge/adapters/local_implementation_adapter.py",
        "loopforge/contracts/policies/local-implementation-adapter.json",
        "loopforge/checks/isolated_process.py",
        "loopforge/contracts/policies/parent-environment-isolation.json",
        "loopforge/checks/validate_implementation_result.py",
        "loopforge/contracts/policies/implementation-result-validation.json",
        "loopforge/contracts/schemas/implementation-result.schema.json",
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
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"Local implementation adapter git command failed{suffix}")
    return completed.stdout


def git_status_paths(workspace: Path) -> list[str] | None:
    try:
        output = run_git(workspace, "status", "--porcelain=v1", "--untracked-files=all")
    except ValueError as error:
        if "not a git repository" in str(error).lower():
            return None
        raise
    paths: list[str] = []
    for raw_line in output.decode("utf-8", errors="replace").splitlines():
        if not raw_line:
            continue
        path = raw_line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        paths.append(path.replace("\\", "/"))
    return paths


def relevant_git_status_paths(paths: list[str], policy: dict[str, Any]) -> list[str]:
    ignored_prefixes = tuple(policy["ignored_workspace_status_prefixes"])
    return [
        path
        for path in paths
        if not any(
            path == prefix.rstrip("/") or path.startswith(prefix)
            for prefix in ignored_prefixes
        )
    ]


def workspace_file_snapshot(workspace: Path, policy: dict[str, Any]) -> dict[str, tuple[int, int]]:
    ignored_prefixes = tuple(policy["ignored_workspace_status_prefixes"])
    snapshot: dict[str, tuple[int, int]] = {}
    for path in workspace.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if any(
            relative == prefix.rstrip("/") or relative.startswith(prefix)
            for prefix in ignored_prefixes
        ):
            continue
        stat = path.stat()
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def workspace_dirty(workspace: Path, policy: dict[str, Any]) -> bool:
    paths = git_status_paths(workspace)
    return bool(relevant_git_status_paths(paths, policy)) if paths is not None else False


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


def compact_stream_text(value: object, limit: int = 180) -> str:
    if isinstance(value, list):
        text = " ".join(str(part) for part in value)
    else:
        text = str(value or "")
    text = " ".join(text.replace("\r", "\n").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def is_codex_command(command: Sequence[str]) -> bool:
    return command_basename(command) in {"codex", "codex.exe"}


def command_with_kilo_prompt(
    command: Sequence[str], stdin_file: Path | None
) -> list[str]:
    """Pass the LoopForge prompt to Kilo's positional ``kilo run`` message.

    Kilo's non-interactive command accepts the task as a positional argument,
    rather than reading it from stdin like Codex.  Keep this conversion in the
    shared protocol wrapper so command allowlisting, isolated execution, and
    result validation remain identical for every implementation adapter.
    """

    prepared = list(command)
    if stdin_file is None or not is_kilo_command(prepared):
        return prepared
    prompt = stdin_file.read_text(encoding="utf-8")
    return command_with_prompt(prepared, prompt)


def is_codex_json_stream(command: Sequence[str]) -> bool:
    return is_codex_command(command) and "--json" in command


def classify_codex_windows_sandbox_failure(stderr: bytes) -> str | None:
    """Recognize the Codex helper failure before it is reduced to no changes."""

    message = stderr.decode("utf-8", errors="replace").lower()
    if (
        "windows sandbox" in message
        and "orchestrator_helper_launch_failed" in message
        and "helper" in message
    ):
        return "codex_windows_sandbox_helper_launch_failed"
    return None


def nested_value(value: object, names: set[str]) -> object | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in names:
                return item
        for item in value.values():
            found = nested_value(item, names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = nested_value(item, names)
            if found is not None:
                return found
    return None


def collect_text(value: object) -> list[str]:
    texts: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "message", "summary", "output_text"} and isinstance(item, str):
                if item.strip():
                    texts.append(item.strip())
            elif key in {"content", "delta", "item", "payload", "output"}:
                texts.extend(collect_text(item))
    elif isinstance(value, list):
        for item in value:
            texts.extend(collect_text(item))
    return texts


def codex_event_lines(event: dict[str, Any], state: dict[str, str]) -> list[str]:
    event_type = str(event.get("type") or event.get("event") or "").lower()
    event_blob = json.dumps(event, sort_keys=True).lower()
    if "reason" in event_type or "thinking" in event_type or "reasoning" in event_blob:
        if state.get("last") != "thinking":
            state["last"] = "thinking"
            return ["Reflexion en cours..."]
        return []
    if "error" in event_type or "error" in event:
        state["last"] = "error"
        detail = (
            nested_value(event, {"message", "error", "detail"})
            or event_type
            or "unknown error"
        )
        return [f"Erreur adaptateur: {compact_stream_text(detail)}"]
    if any(marker in event_type for marker in ("tool", "exec", "command", "function_call")):
        command_value = nested_value(event, {"command", "cmd", "name"})
        if command_value is None:
            command_value = event_type.replace("_", " ")
        state["last"] = "tool"
        return [f"Outil: {compact_stream_text(command_value)}"]
    if "message" in event_type or "response" in event_type or "agent" in event_type:
        texts = [text for text in collect_text(event) if text.strip()]
        if texts:
            state["last"] = "message"
            lines = ["Message"]
            for text in texts[:3]:
                lines.extend(f"  {line}" for line in text.splitlines() if line.strip())
            return lines
    return []


class StreamPresenter:
    def __init__(  # type: ignore[no-untyped-def]
        self,
        target,
        *,
        parse_codex_json: bool = False,
        codex_text: bool = False,
    ):
        self.target = target
        self.parse_codex_json = parse_codex_json
        self.codex_text = codex_text
        self.buffer = ""
        self.state: dict[str, str] = {}
        self.noted_diagnostic = False

    def write(self, chunk: bytes) -> None:
        if not self.parse_codex_json and not self.codex_text:
            self.target.buffer.write(chunk)
            self.target.buffer.flush()
            return
        text = chunk.decode("utf-8", errors="replace")
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.write_line(line.rstrip("\r"))

    def write_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if self.parse_codex_json:
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                if not self.noted_diagnostic:
                    print(f"Adapter: {compact_stream_text(stripped)}", file=self.target, flush=True)
                    self.noted_diagnostic = True
                return
            if isinstance(event, dict):
                for rendered in codex_event_lines(event, self.state):
                    print(rendered, file=self.target, flush=True)
            return
        if not self.noted_diagnostic:
            print(f"Adapter: {compact_stream_text(stripped)}", file=self.target, flush=True)
            self.noted_diagnostic = True

    def close(self) -> None:
        if self.buffer:
            self.write_line(self.buffer)
            self.buffer = ""


def summary_for(
    status: str,
    completed: subprocess.CompletedProcess[bytes] | None,
    timed_out: bool,
    changed: bool,
    policy: dict[str, Any],
    *,
    fixture: bool = False,
    stderr: bytes = b"",
) -> str:
    command_name = "Fixture command" if fixture else "Implementation command"
    failure = classify_codex_windows_sandbox_failure(stderr)
    if failure is not None:
        text = (
            "Codex Windows workspace sandbox helper failed to launch before "
            "implementation; inspect the retained child stderr evidence."
        )
    elif timed_out:
        text = f"{command_name} timed out."
    elif completed is None:
        text = f"{command_name} was not run."
    elif completed.returncode != 0:
        text = f"{command_name} failed with return code {completed.returncode}."
    elif status == "blocked":
        text = f"{command_name} completed without workspace changes."
    elif changed:
        text = f"{command_name} completed and changed the workspace."
    else:
        text = f"{command_name} completed."
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
    child_stderr_output: Path | None = None,
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
    initial_git_paths = git_status_paths(workspace)
    initial_snapshot = (
        workspace_file_snapshot(workspace, policy)
        if initial_git_paths is None
        else None
    )
    clean_start_required = policy["require_clean_workspace_at_start"] and not (
        policy["allow_dirty_workspace_for_authorized_recovery"]
        and session["recovery_authorized"]
    )
    if clean_start_required and initial_git_paths is not None and relevant_git_status_paths(initial_git_paths, policy):
        value = result_value(
            session,
            "failed",
            "Workspace was not clean before implementation command.",
            False,
        )
        return validate_implementation_result.canonical_result_bytes(value)

    resolved_command = isolated_process.resolve_child_executable(
        command_with_kilo_prompt(command, stdin_file)
    )
    kilo_prepared = is_kilo_command(resolved_command)
    prepared_command = (
        command_without_windows_batch_launcher(resolved_command)
        if kilo_prepared
        else resolved_command
    )
    completed: subprocess.CompletedProcess[bytes] | None = None
    timed_out = False
    try:
        stdin_handle = (
            stdin_file.open("rb")
            if stdin_file is not None and not kilo_prepared
            else None
        )
        isolation_policy = isolated_process.load_policy()
        process = subprocess.Popen(
            prepared_command,
            cwd=workspace,
            stdin=stdin_handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=(
                isolated_process.build_codex_windows_child_environment(
                    os.environ,
                    isolation_policy,
                )
                if is_codex_command(prepared_command)
                else isolated_process.build_child_environment(
                    isolated_process.select_allowed_parent_environment(
                        os.environ,
                        isolation_policy,
                    ),
                    isolation_policy,
                )
            ),
        )
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        present_codex_json = is_codex_json_stream(prepared_command)
        present_codex_text = is_codex_command(prepared_command) and not present_codex_json

        def read_available(source) -> bytes:  # type: ignore[no-untyped-def]
            if hasattr(source, "read1"):
                return source.read1(4096)
            return source.read(1)

        def pump(  # type: ignore[no-untyped-def]
            source,
            target,
            buffer: bytearray,
            presenter: StreamPresenter,
        ) -> None:
            try:
                while True:
                    chunk = read_available(source)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if stream_output and policy["stream_child_output"]:
                        presenter.write(chunk)
            finally:
                presenter.close()
                source.close()

        stdout_thread = threading.Thread(
            target=pump,
            args=(
                process.stdout,
                sys.stdout,
                stdout_buffer,
                StreamPresenter(
                    sys.stdout,
                    parse_codex_json=present_codex_json,
                    codex_text=present_codex_text,
                ),
            ),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=pump,
            args=(
                process.stderr,
                sys.stderr,
                stderr_buffer,
                StreamPresenter(sys.stderr, codex_text=present_codex_text or present_codex_json),
            ),
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
            prepared_command,
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

    if child_stderr_output is not None:
        child_stderr_output.parent.mkdir(parents=True, exist_ok=True)
        child_stderr_output.write_bytes(completed.stderr or b"")
    output_size = len(completed.stdout or b"") + len(completed.stderr or b"")
    current_git_paths = git_status_paths(workspace)
    if current_git_paths is None:
        changed = initial_snapshot != workspace_file_snapshot(workspace, policy)
    else:
        changed = bool(relevant_git_status_paths(current_git_paths, policy))
    if timed_out or completed.returncode != 0 or output_size > policy["max_child_output_bytes"]:
        status = "failed"
    elif changed:
        status = "completed"
    else:
        status = "blocked"
    summary = summary_for(
        status,
        completed,
        timed_out,
        changed,
        policy,
        fixture=(
            stream_output
            and session["runner_id"] in policy["fixture_runner_ids"]
        ),
        stderr=completed.stderr or b"",
    )
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
    parser.add_argument("--child-stderr-output", type=Path)
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
            child_stderr_output=args.child_stderr_output,
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
