"""Unified bounded process runner for LoopForge."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Sequence

from loopforge.checks import isolated_process as isolated


def _is_posix() -> bool:
    return os.name == "posix"


def _is_windows() -> bool:
    return os.name == "nt"


@dataclass
class ProcessReceipt:
    """Trusted receipt of a completed (or failed/terminated) subprocess."""

    completed: bool
    timed_out: bool = False
    output_limit_exceeded: bool = False
    kill_requested: bool = False
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0
    pid: int | None = None
    children_terminated: bool = False
    issue: str = ""
    spool_path: Path | None = None


_POLICY = isolated.load_policy()


class ProcessRunner:
    """Unified process runner that bounds output, kills full process tree."""

    def __init__(
        self,
        *,
        output_limit_bytes: int = 1_000_000,
        timeout: float = 300.0,
        spool_dir: Path | None = None,
    ):
        self._output_limit_bytes = output_limit_bytes
        self._timeout = timeout
        self._spool_dir = spool_dir

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        stdin_data: str | None = None,
        cancel_event: Event | None = None,
        timeout: float | None = None,
    ) -> ProcessReceipt:
        """Execute a subprocess with output bounding and tree termination."""
        started_at = time.time()
        effective_timeout = timeout if timeout is not None else self._timeout

        try:
            exact_command = isolated.validate_command(
                [str(p) for p in command], cwd, _POLICY
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            return ProcessReceipt(
                completed=False,
                stdout="",
                stderr=str(exc),
                started_at=started_at,
                finished_at=time.time(),
                issue="launch_failure",
            )

        if env is None:
            env = isolated.build_child_environment(os.environ, _POLICY)

        popen_kwargs: dict[str, Any] = {
            "args": exact_command,
            "cwd": str(cwd),
            "env": env,
            "stdin": subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
        }
        if _is_posix():
            popen_kwargs["preexec_fn"] = os.setsid
        elif _is_windows():
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(**popen_kwargs)
        except OSError as exc:
            return ProcessReceipt(
                completed=False,
                stdout="",
                stderr=str(exc),
                started_at=started_at,
                finished_at=time.time(),
                issue="launch_failure",
            )

        pid = process.pid
        pgid = None
        if _is_posix() and pid is not None:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = None

        if stdin_data is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_data.encode("utf-8"))
                process.stdin.flush()
            except OSError:
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        assert process.stdout is not None
        assert process.stderr is not None

        return _collect_output(
            process,
            pid,
            pgid,
            started_at,
            effective_timeout,
            cancel_event,
            output_limit_bytes=self._output_limit_bytes,
            spool_dir=self._spool_dir,
        )


def _collect_output(
    process: subprocess.Popen[bytes],
    pid: int | None,
    pgid: int | None,
    started_at: float,
    effective_timeout: float,
    cancel_event: Event | None,
    *,
    output_limit_bytes: int = 1_000_000,
    spool_dir: Path | None = None,
) -> ProcessReceipt:
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_chunks: deque[bytes] = deque()
    stderr_chunks: deque[bytes] = deque()
    stdout_held = 0
    stderr_held = 0
    stdout_total_seen = 0
    stderr_total_seen = 0
    output_limit_exceeded = False

    deadline = started_at + effective_timeout
    returncode: int | None = None
    timed_out = False
    kill_requested = False
    children_terminated = False

    events: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=32)
    stopped = threading.Event()

    def _ring_append(coll: deque[bytes], chunk: bytes, held: int) -> tuple[int, int]:
        coll.append(chunk)
        held += len(chunk)
        while held > output_limit_bytes and coll:
            removed = coll.popleft()
            held -= len(removed)
        return held, len(chunk)

    def pump(name: str, stream: Any) -> None:
        try:
            while not stopped.is_set():
                chunk = (
                    stream.read1(4096)
                    if hasattr(stream, "read1")
                    else stream.read(4096)
                )
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
    for thread in threads:
        thread.start()

    active_streams = 2

    def _check_cancel() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        return False

    while active_streams:
        if _check_cancel():
            kill_requested = True
            break
        remaining = deadline - time.time()
        if remaining <= 0:
            timed_out = True
            break
        try:
            name, chunk = events.get(timeout=min(remaining, 0.05))
        except queue.Empty:
            if process.poll() is not None and active_streams == 2:
                events.get(timeout=0.5)
            continue
        if chunk is None:
            active_streams -= 1
            continue
        if name == "stdout":
            stdout_held, seen = _ring_append(stdout_chunks, chunk, stdout_held)
            stdout_total_seen += seen
        else:
            stderr_held, seen = _ring_append(stderr_chunks, chunk, stderr_held)
            stderr_total_seen += seen
        if stdout_total_seen + stderr_total_seen > output_limit_bytes:
            output_limit_exceeded = True
            break

    if not timed_out and not output_limit_exceeded and not kill_requested:
        remaining = deadline - time.time()
        if remaining <= 0:
            timed_out = True
        else:
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
            except OSError:
                pass

    if timed_out or output_limit_exceeded or kill_requested:
        stopped.set()
        _kill_tree(pid, pgid)
        kill_requested = True
        try:
            returncode = process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    if process.poll() is not None and returncode is None:
        returncode = process.returncode

    stopped.set()
    try:
        process.stdout.close()
    except OSError:
        pass
    try:
        process.stderr.close()
    except OSError:
        pass
    for thread in threads:
        thread.join(timeout=3)

    finished_at = time.time()
    children_terminated = _verify_no_descendants(pid)

    stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    output_truncated = output_limit_exceeded

    if kill_requested and cancel_event is not None and cancel_event.is_set():
        issue = "cancellation"
    elif timed_out:
        issue = "timeout"
    elif output_limit_exceeded:
        issue = "output_limit"
    elif returncode is None:
        issue = "protocol_failure"
    else:
        issue = ""

    spool_path: Path | None = None
    if spool_dir is not None:
        spool_dir.mkdir(parents=True, exist_ok=True)
        spool_path = spool_dir / f"run_{int(started_at)}.json"
        import json as _json

        spool_path.write_text(
            _json.dumps(
                {
                    "returncode": returncode,
                    "stdout": stdout_str[:10000],
                    "stderr": stderr_str[:10000],
                    "started_at": int(started_at),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return ProcessReceipt(
        completed=(
            returncode is not None
            and not timed_out
            and not output_limit_exceeded
            and not kill_requested
            and returncode == 0
        ),
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded,
        kill_requested=kill_requested,
        returncode=returncode,
        stdout=stdout_str,
        stderr=stderr_str,
        output_truncated=output_truncated,
        started_at=started_at,
        finished_at=finished_at,
        pid=pid,
        children_terminated=children_terminated,
        issue=issue,
        spool_path=spool_path,
    )


def _kill_tree(pid: int | None, pgid: int | None) -> None:
    if pid is None:
        return
    if _is_posix() and pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    elif _is_windows():
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _verify_no_descendants(pid: int | None) -> bool:
    if pid is None:
        return True
    if _is_posix():
        try:
            os.waitpid(pid, os.WNOHANG)
        except OSError:
            pass
        return True
    if _is_windows():
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return str(pid) not in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return True
    return True