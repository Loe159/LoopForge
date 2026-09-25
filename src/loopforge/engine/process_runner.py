"""Unified bounded process runner for LoopForge."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
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


def _windows_cancel_api() -> Any | None:
    """Return the synchronous-I/O cancellation API, if this host provides it."""
    if not _is_windows():
        return None
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenThread.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenThread.restype = ctypes.c_void_p
        kernel32.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
        kernel32.CancelSynchronousIo.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        return kernel32
    except (AttributeError, OSError):
        return None


def _open_windows_writer_handle(kernel32: Any) -> Any:
    """Pin the current writer thread before it can issue a blocking write."""
    # THREAD_TERMINATE is the access right required by CancelSynchronousIo.
    return kernel32.OpenThread(0x0001, False, threading.get_native_id())


def _cancel_windows_writer(handle: Any, kernel32: Any) -> None:
    """Cancel pending synchronous I/O using a stable thread handle."""
    if handle:
        kernel32.CancelSynchronousIo(handle)


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
    stdin_cleanup_failed: bool = False


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
        started_monotonic = time.monotonic()
        effective_timeout = timeout if timeout is not None else self._timeout
        deadline = started_monotonic + effective_timeout

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

        stdin_payload = stdin_data.encode("utf-8") if stdin_data is not None else None
        stdin_reader: int | None = None
        stdin_writer: int | None = None
        windows_cancel_api: Any | None = None
        stdin_source: Any = subprocess.DEVNULL
        if stdin_payload is not None:
            try:
                stdin_reader, stdin_writer = os.pipe()
                try:
                    os.set_blocking(stdin_writer, False)
                except (AttributeError, OSError):
                    windows_cancel_api = _windows_cancel_api()
                    if windows_cancel_api is None:
                        raise OSError("cancellable stdin is unavailable") from None
                stdin_source = stdin_reader
            except (AttributeError, OSError) as exc:
                if stdin_reader is not None:
                    os.close(stdin_reader)
                if stdin_writer is not None:
                    os.close(stdin_writer)
                return ProcessReceipt(
                    completed=False,
                    stderr=f"nonblocking stdin unavailable: {exc}",
                    started_at=started_at,
                    finished_at=time.time(),
                    issue="launch_failure",
                )

        if time.monotonic() >= deadline:
            if stdin_reader is not None:
                os.close(stdin_reader)
            if stdin_writer is not None:
                os.close(stdin_writer)
            return ProcessReceipt(
                completed=False,
                timed_out=True,
                started_at=started_at,
                finished_at=time.time(),
                issue="timeout",
            )

        popen_kwargs: dict[str, Any] = {
            "args": exact_command,
            "cwd": str(cwd),
            "env": env,
            "stdin": stdin_source,
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
            if stdin_writer is not None:
                os.close(stdin_writer)
            return ProcessReceipt(
                completed=False,
                stdout="",
                stderr=str(exc),
                started_at=started_at,
                finished_at=time.time(),
                issue="launch_failure",
            )
        finally:
            if stdin_reader is not None:
                os.close(stdin_reader)

        pid = process.pid
        # setsid() ran in the child before Popen returned. Its PID is the
        # group ID even if it exits before we begin collecting output.
        pgid = pid if _is_posix() else None

        assert process.stdout is not None
        assert process.stderr is not None

        return _collect_output(
            process,
            pid,
            pgid,
            started_at,
            deadline,
            cancel_event,
            stdin_fd=stdin_writer,
            stdin_payload=stdin_payload,
            windows_cancel_api=windows_cancel_api,
            output_limit_bytes=self._output_limit_bytes,
            spool_dir=self._spool_dir,
        )


def _collect_output(
    process: subprocess.Popen[bytes],
    pid: int | None,
    pgid: int | None,
    started_at: float,
    deadline: float,
    cancel_event: Event | None,
    *,
    stdin_fd: int | None = None,
    stdin_payload: bytes | None = None,
    windows_cancel_api: Any | None = None,
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

    returncode: int | None = None
    timed_out = False
    kill_requested = False
    cancelled = False
    children_terminated = False
    stdin_cleanup_failed = False
    stdin_delivery_failed = False
    writer_handle: Any = None
    writer_ready = threading.Event()
    writer_handle_lock = threading.Lock()

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

    # A child may never read stdin. Keep writes off the supervising thread so
    # timeout, cancellation, and bounded output collection continue to run.
    stdin_thread: threading.Thread | None = None
    if stdin_fd is not None and stdin_payload is not None:
        def write_stdin() -> None:
            nonlocal writer_handle, stdin_delivery_failed
            try:
                if windows_cancel_api is not None:
                    handle = _open_windows_writer_handle(windows_cancel_api)
                    if not handle:
                        stdin_delivery_failed = True
                        return
                    with writer_handle_lock:
                        writer_handle = handle
                    writer_ready.set()
                offset = 0
                while offset < len(stdin_payload) and not stopped.is_set():
                    try:
                        written = os.write(
                            stdin_fd, memoryview(stdin_payload)[offset : offset + 65536]
                        )
                    except BlockingIOError:
                        stopped.wait(0.01)
                        continue
                    if written == 0:
                        stopped.wait(0.01)
                    else:
                        offset += written
            except (OSError, ValueError):
                pass
            finally:
                writer_ready.set()
                if windows_cancel_api is not None:
                    with writer_handle_lock:
                        if writer_handle:
                            windows_cancel_api.CloseHandle(writer_handle)
                            writer_handle = None
                os.close(stdin_fd)

        stdin_thread = threading.Thread(
            target=write_stdin, name=f"loopforge-stdin-{pid}", daemon=True
        )
        stdin_thread.start()

    if windows_cancel_api is not None and stdin_thread is not None:
        while not writer_ready.is_set():
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                kill_requested = True
                stopped.set()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                stopped.set()
                break
            writer_ready.wait(timeout=min(remaining, 0.01))

    active_streams = 2

    def _check_cancel() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        return False

    while active_streams and not (timed_out or kill_requested):
        if _check_cancel():
            cancelled = True
            kill_requested = True
            break
        remaining = deadline - time.monotonic()
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
        while returncode is None:
            if _check_cancel():
                cancelled = True
                kill_requested = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                returncode = process.wait(timeout=min(remaining, 0.05))
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                break

    # The parent can exit successfully while a descendant still holds its
    # stdin read end. A receipt cannot report completion with a live writer.
    if returncode is not None and stdin_thread is not None:
        while stdin_thread.is_alive() and not (timed_out or output_limit_exceeded or kill_requested):
            if _check_cancel():
                cancelled = True
                kill_requested = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            stdin_thread.join(timeout=min(remaining, 0.05))

    if timed_out or output_limit_exceeded or kill_requested:
        stopped.set()
        if windows_cancel_api is not None:
            with writer_handle_lock:
                if writer_handle:
                    _cancel_windows_writer(writer_handle, windows_cancel_api)
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
    if stdin_thread is not None:
        if windows_cancel_api is not None:
            cleanup_deadline = time.monotonic() + 0.2
            while stdin_thread.is_alive() and time.monotonic() < cleanup_deadline:
                with writer_handle_lock:
                    if writer_handle:
                        _cancel_windows_writer(writer_handle, windows_cancel_api)
                stdin_thread.join(
                    timeout=max(0.0, min(0.02, cleanup_deadline - time.monotonic()))
                )
            stdin_cleanup_failed = stdin_thread.is_alive()
        else:
            stdin_thread.join()

    finished_at = time.time()
    children_terminated = _verify_no_descendants(pid)

    stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    output_truncated = output_limit_exceeded

    if stdin_cleanup_failed:
        issue = "stdin_cleanup_failure"
        stderr_str += "\nstdin writer remained active after cancellation"
    elif stdin_delivery_failed:
        issue = "stdin_setup_failure"
        stderr_str += "\nstdin writer could not acquire a cancellation handle"
    elif cancelled:
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
            and not stdin_cleanup_failed
            and not stdin_delivery_failed
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
        stdin_cleanup_failed=stdin_cleanup_failed,
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
