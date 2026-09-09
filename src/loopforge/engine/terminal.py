"""External terminal launchers used by supervised agent-harness sessions."""

from __future__ import annotations

import json
import ctypes
from ctypes import wintypes
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Callable, Mapping

from loopforge.adapters.bounded_capture import BoundedCapture
from loopforge.engine.terminal_bridge import TERMINAL_BRIDGE_AUTHKEY


CREATE_NEW_CONSOLE = 0x00000010
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsJob:
    """Kill-on-close Windows Job Object supervising a terminal process tree."""

    def __init__(self, handle: int, kernel32: object) -> None:
        self.handle = handle
        self.kernel32 = kernel32

    @classmethod
    def create(cls) -> _WindowsJob:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        return cls(handle, kernel32)

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        self.kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not self.kernel32.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(process._handle))
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        if not self.kernel32.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = 0


@dataclass(frozen=True)
class TerminalLaunchRequest:
    command: tuple[str, ...]
    cwd: Path
    title: str
    timeout_seconds: int
    artifacts_dir: Path
    cancel_event: threading.Event | None = None
    environment: Mapping[str, str] | None = None
    output_chunk_callback: Callable[[str, bytes], None] | None = None
    max_output_bytes: int = 131_072


@dataclass(frozen=True)
class TerminalSessionResult:
    launched: bool
    returncode: int | None
    timed_out: bool = False
    interrupted: bool = False
    launcher: str = ""
    error: str = ""
    launcher_command: tuple[str, ...] = ()
    output: bytes = b""
    output_truncated: bool = False


class TerminalLauncher:
    """Small platform boundary for a separately visible terminal session."""

    name = "unsupported"

    def launch(self, request: TerminalLaunchRequest) -> TerminalSessionResult:
        raise NotImplementedError


def build_terminal_environment() -> dict[str, str]:
    """Build the same restricted child environment for every visible harness."""

    from loopforge.checks import isolated_process

    policy = isolated_process.load_policy()
    if os.name == "nt":
        return isolated_process.build_codex_windows_child_environment(
            os.environ,
            policy,
        )
    return isolated_process.build_child_environment(
        isolated_process.select_allowed_parent_environment(os.environ, policy),
        policy,
    )


class UnsupportedTerminalLauncher(TerminalLauncher):
    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.name = f"unsupported-{platform}"

    def launch(self, request: TerminalLaunchRequest) -> TerminalSessionResult:
        del request
        return TerminalSessionResult(
            launched=False,
            returncode=None,
            launcher=self.name,
            error=f"separate terminal launcher is not implemented for {self.platform}",
        )


WINDOWS_WRAPPER = r'''param([Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference = "Stop"
$request = Get-Content -Raw -LiteralPath $RequestPath | ConvertFrom-Json
$Host.UI.RawUI.WindowTitle = [string]$request.title
Set-Location -LiteralPath ([string]$request.cwd)
while (-not (Test-Path -LiteralPath ([string]$request.start_path))) {
  Start-Sleep -Milliseconds 25
}
$command = [string]$request.command[0]
$arguments = @($request.command | Select-Object -Skip 1 | ForEach-Object { [string]$_ })
$exitCode = 1
try {
  & $command @arguments
  if ($null -eq $LASTEXITCODE) { $exitCode = 0 } else { $exitCode = [int]$LASTEXITCODE }
} catch {
  $_ | Out-String | Set-Content -LiteralPath ([string]$request.error_path) -Encoding UTF8
  $exitCode = 1
}
exit $exitCode
'''


def _normalize_windows_terminal_command(
    command: list[str], environment: Mapping[str, str] | None
) -> list[str]:
    """Wrap Windows script shims without routing arbitrary commands through a shell."""

    suffix = Path(command[0]).suffix.casefold()
    path = str((environment or {}).get("PATH") or os.environ.get("PATH", ""))
    if suffix == ".ps1":
        powershell = shutil.which("pwsh.exe", path=path) or shutil.which(
            "powershell.exe", path=path
        )
        if powershell is None:
            raise FileNotFoundError("PowerShell is required to launch this agent harness")
        return [
            str(Path(powershell).resolve()),
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            *command,
        ]
    if suffix in {".bat", ".cmd"}:
        comspec = str((environment or {}).get("COMSPEC") or "").strip()
        if not comspec:
            comspec = shutil.which("cmd.exe", path=path) or ""
        if not comspec or not Path(comspec).resolve().is_file():
            raise FileNotFoundError("cmd.exe is required to launch this agent harness")
        return [str(Path(comspec).resolve()), "/d", "/s", "/c", *command]
    return command


class WindowsTerminalLauncher(TerminalLauncher):
    """Open a dedicated Windows console and wait for its harness process."""

    name = "windows-new-console"

    @staticmethod
    def _terminate_process_tree(
        process: subprocess.Popen[bytes], job: _WindowsJob | None = None
    ) -> str:
        cleanup_error = ""
        if job is not None:
            try:
                job.terminate()
                return ""
            except OSError as error:
                cleanup_error = str(error)
        for _attempt in range(2):
            try:
                result = subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_error = str(error)
            else:
                if result.returncode == 0 or process.poll() is not None:
                    return ""
                cleanup_error = (
                    result.stderr.decode("utf-8", errors="replace").strip()
                    if isinstance(result.stderr, bytes)
                    else str(result.stderr or "").strip()
                ) or f"taskkill exited with return code {result.returncode}"
        if process.poll() is None:
            process.terminate()
        return cleanup_error

    @staticmethod
    def _wait_for_terminated_process(
        process: subprocess.Popen[bytes], job: _WindowsJob | None
    ) -> None:
        try:
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            if job is not None:
                job.close()

    def launch(self, request: TerminalLaunchRequest) -> TerminalSessionResult:
        if request.cancel_event is not None and request.cancel_event.is_set():
            return TerminalSessionResult(
                launched=False,
                returncode=None,
                interrupted=True,
                launcher=self.name,
                error="Interactive terminal launch was cancelled before process creation.",
            )
        from loopforge.checks.isolated_process import resolve_child_executable

        try:
            resolved_command = resolve_child_executable(request.command)
            resolved_command = _normalize_windows_terminal_command(
                resolved_command, request.environment
            )
        except FileNotFoundError as error:
            return TerminalSessionResult(
                launched=False,
                returncode=None,
                launcher=self.name,
                error=str(error),
            )
        request.artifacts_dir.mkdir(parents=True, exist_ok=True)
        wrapper_path = request.artifacts_dir / "terminal-session.ps1"
        request_path = request.artifacts_dir / "terminal-request.json"
        error_path = request.artifacts_dir / "terminal-session.stderr"
        start_path = request.artifacts_dir / "terminal-session.start"
        for stale_path in (error_path, start_path):
            stale_path.unlink(missing_ok=True)
        stream_listener: Listener | None = None
        stream_queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=4)
        stream_thread: threading.Thread | None = None
        output = bytearray()
        capture = BoundedCapture(request.max_output_bytes)
        callback_error = ""
        output_callback = request.output_chunk_callback
        if output_callback is None:
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if powershell is None:
                return TerminalSessionResult(
                    launched=False,
                    returncode=None,
                    launcher=self.name,
                    error="Windows PowerShell is required to open a supervised terminal",
                )
            wrapper_path.write_text(WINDOWS_WRAPPER, encoding="ascii")
            request_payload = {
                "command": resolved_command,
                "cwd": str(request.cwd),
                "title": request.title,
                "error_path": str(error_path),
                "start_path": str(start_path),
            }
            launcher_command = (
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(wrapper_path),
                "-RequestPath",
                str(request_path),
            )
        else:
            pipe_name = rf"\\.\pipe\loopforge-{secrets.token_hex(16)}"
            try:
                stream_listener = Listener(
                    pipe_name,
                    family="AF_PIPE",
                    authkey=TERMINAL_BRIDGE_AUTHKEY,
                )
            except OSError as error:
                return TerminalSessionResult(
                    launched=False,
                    returncode=None,
                    launcher=self.name,
                    error=f"could not create terminal output bridge: {error}",
                )
            request_payload = {
                "command": resolved_command,
                "cwd": str(request.cwd),
                "title": request.title,
                "error_path": str(error_path),
                "start_path": str(start_path),
                "pipe_name": pipe_name,
            }
            bridge_path = Path(__file__).with_name("terminal_bridge.py").resolve()
            launcher_command = (
                str(Path(sys.executable).resolve()),
                str(bridge_path),
                "--request",
                str(request_path),
            )
        request_path.write_text(
            json.dumps(request_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        try:
            process = subprocess.Popen(
                launcher_command,
                cwd=request.cwd,
                shell=False,
                close_fds=True,
                creationflags=CREATE_NEW_CONSOLE,
                env=dict(request.environment) if request.environment is not None else None,
            )
        except OSError as error:
            if stream_listener is not None:
                stream_listener.close()
            return TerminalSessionResult(
                launched=False,
                returncode=None,
                launcher=self.name,
                error=str(error),
                launcher_command=launcher_command,
            )

        job: _WindowsJob | None = None
        try:
            job = _WindowsJob.create()
            job.assign(process)
        except (OSError, TypeError, ValueError) as error:
            if stream_listener is not None:
                stream_listener.close()
            if job is not None:
                job.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            return TerminalSessionResult(
                launched=False,
                returncode=process.returncode,
                launcher=self.name,
                error=f"could not establish Windows process-tree supervision: {error}",
                launcher_command=launcher_command,
            )
        if request.cancel_event is not None and request.cancel_event.is_set():
            if stream_listener is not None:
                stream_listener.close()
            self._terminate_process_tree(process, job)
            self._wait_for_terminated_process(process, job)
            return TerminalSessionResult(
                launched=False,
                returncode=process.returncode,
                interrupted=True,
                launcher=self.name,
                error="Interactive terminal launch was cancelled before harness release.",
                launcher_command=launcher_command,
            )
        if stream_listener is not None:
            listener = stream_listener

            def receive_output() -> None:
                connection = None
                try:
                    connection = listener.accept()
                    listener.close()
                    while True:
                        try:
                            stream_queue.put(connection.recv_bytes())
                        except EOFError:
                            break
                except Exception as error:
                    stream_queue.put(error)
                finally:
                    if connection is not None:
                        connection.close()
                    stream_queue.put(None)

            stream_thread = threading.Thread(
                target=receive_output,
                name="loopforge-terminal-output",
                daemon=True,
            )
            stream_thread.start()
        try:
            start_path.touch(exist_ok=False)
        except OSError as error:
            if stream_listener is not None:
                stream_listener.close()
            self._terminate_process_tree(process, job)
            self._wait_for_terminated_process(process, job)
            return TerminalSessionResult(
                launched=False,
                returncode=process.returncode,
                launcher=self.name,
                error=f"could not release supervised terminal wrapper: {error}",
                launcher_command=launcher_command,
            )

        def drain_output() -> None:
            nonlocal callback_error
            pending = bytearray()
            while True:
                try:
                    item = stream_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, Exception):
                    callback_error = f"terminal output bridge failed: {item}"
                    continue
                if item is None:
                    continue
                capture.append(output, item)
                pending.extend(item)
            if not pending:
                return
            try:
                output_callback("stdout", bytes(pending))
            except Exception as error:
                if not callback_error:
                    callback_error = f"terminal output callback failed: {error}"

        deadline = time.monotonic() + max(1, request.timeout_seconds)
        timed_out = False
        interrupted = False
        cleanup_error = ""
        try:
            while process.poll() is None:
                drain_output()
                if request.cancel_event is not None and request.cancel_event.is_set():
                    interrupted = True
                    cleanup_error = self._terminate_process_tree(process, job)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    cleanup_error = self._terminate_process_tree(process, job)
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            self._terminate_process_tree(process, job)
            self._wait_for_terminated_process(process, job)
            raise
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        drain_output()
        if stream_thread is not None:
            stream_thread.join(timeout=1.0)
        drain_output()
        if stream_listener is not None:
            try:
                stream_listener.close()
            except OSError:
                pass
        try:
            error = error_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            error = ""
        if cleanup_error:
            error = "\n".join(
                part for part in (error.strip(), f"Process-tree cleanup failed: {cleanup_error}") if part
            )
        if callback_error:
            error = "\n".join(part for part in (error.strip(), callback_error) if part)
        if job is not None:
            job.close()
        return TerminalSessionResult(
            launched=True,
            returncode=process.returncode,
            timed_out=timed_out,
            interrupted=interrupted,
            launcher=self.name,
            error=error,
            launcher_command=launcher_command,
            output=bytes(output),
            output_truncated=capture.exceeded.is_set(),
        )


def default_terminal_launcher(*, platform: str | None = None) -> TerminalLauncher:
    selected = platform or sys.platform
    if selected == "win32":
        return WindowsTerminalLauncher()
    return UnsupportedTerminalLauncher(selected)


def launch_terminal_session(
    *,
    command: tuple[str, ...],
    cwd: Path,
    title: str,
    timeout_seconds: int,
    artifacts_dir: Path,
    cancel_event: threading.Event | None = None,
    terminal_launcher: TerminalLauncher | None = None,
    output_chunk_callback: Callable[[str, bytes], None] | None = None,
) -> TerminalSessionResult:
    """Launch and normalize a supervised visible harness session."""

    from loopforge.checks import isolated_process

    launcher = terminal_launcher or default_terminal_launcher()
    policy = isolated_process.load_policy()
    try:
        result = launcher.launch(
            TerminalLaunchRequest(
                command=command,
                cwd=cwd,
                title=title,
                timeout_seconds=timeout_seconds,
                artifacts_dir=artifacts_dir,
                cancel_event=cancel_event,
                environment=build_terminal_environment(),
                output_chunk_callback=output_chunk_callback,
                max_output_bytes=int(policy["max_captured_output_bytes"]),
            )
        )
    except KeyboardInterrupt:
        return TerminalSessionResult(
            launched=True,
            returncode=None,
            interrupted=True,
            launcher=str(getattr(launcher, "name", "terminal")),
            error="Interactive terminal session was interrupted.",
        )
    if result.launcher:
        return result
    return replace(result, launcher=str(getattr(launcher, "name", "terminal")))
