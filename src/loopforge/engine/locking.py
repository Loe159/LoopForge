"""Cross-platform inter-process file locking for LoopForge.

Uses native OS primitives: msvcrt on Windows, fcntl on POSIX.
No external dependencies.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


_WINDOWS = os.name == "nt"


if _WINDOWS:
    import msvcrt
    import ctypes
    from ctypes import wintypes

    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    _kernel32 = ctypes.windll.kernel32

    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE

    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD

    _kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    _WAIT_TIMEOUT = 0x00000102
    _STILL_ACTIVE = 259

    def _pid_is_alive(pid: int) -> bool:
        """Check whether a Windows process with the given PID is still running,
        using only kernel32 calls (no psutil)."""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == _INVALID_HANDLE_VALUE or handle is None:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(handle)

    def _acquire_exclusive(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _release_lock(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (OSError, PermissionError):
            pass

else:
    import errno
    import fcntl

    def _pid_is_alive(pid: int) -> bool:
        """Check whether a POSIX process with the given PID is still running
        using os.kill(pid, 0)."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _acquire_exclusive(fd: int) -> None:
        fcntl.lockf(fd, fcntl.LOCK_EX)

    def _release_lock(fd: int) -> None:
        try:
            fcntl.lockf(fd, fcntl.LOCK_UN)
        except (OSError, ValueError):
            pass


class LockTimeoutError(TimeoutError):
    """Raised when a file lock cannot be acquired within the timeout period."""


def _lock_file_age(lock_path: Path) -> Optional[float]:
    """Return the age of a lock file in seconds, or None if it doesn't exist."""
    if not lock_path.is_file():
        return None
    try:
        return time.time() - lock_path.stat().st_mtime
    except OSError:
        return None


_STALE_WINDOWS_LOCK_AGE = 30.0


def _read_lock_pid(lock_path: Path) -> Optional[int]:
    """Read a PID from an existing lock file.

    Returns the parsed PID or None if the file cannot be read or contains
    an invalid value.
    """
    if _WINDOWS:
        return None
    if not lock_path.is_file():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw)
    except (ValueError, TypeError):
        return None
    if pid <= 0:
        return None
    return pid


def _remove_stale_lock(lock_path: Path, fd: Optional[int]) -> bool:
    """Remove a stale lock file and close the associated file descriptor.

    Returns True if the stale lock was successfully removed.
    """
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink()
        return True
    except OSError:
        return False


def _open_lock_file(lock_path: Path) -> int:
    """Open (or create) the lock file and return the file descriptor.

    On Windows the fd needs O_BINARY so msvcrt.locking works correctly.
    """
    flags = os.O_CREAT | os.O_RDWR
    if _WINDOWS:
        flags |= os.O_BINARY
    return os.open(str(lock_path), flags)


def _try_acquire_clean(target: Path) -> Tuple[Optional[int], bool]:
    """Attempt to acquire the lock for *target*.

    Returns ``(fd, True)`` on success, or ``(None, False)`` if the lock is
    held by another live process.

    Raises OSError (including EACCES / ENOLCK) when OS-level locking fails
    for a reason other than a live holder.
    """
    lock_path = Path(str(target) + ".lock")

    # --- stale-lock detection ------------------------------------------------
    if _WINDOWS:
        lock_age = _lock_file_age(lock_path)
        if lock_age is not None and lock_age > _STALE_WINDOWS_LOCK_AGE:
            logger.debug(
                "Detected stale lock for %s (age %.1fs > %.1fs), removing.",
                target,
                lock_age,
                _STALE_WINDOWS_LOCK_AGE,
            )
            _remove_stale_lock(lock_path, None)
    else:
        stale_pid = _read_lock_pid(lock_path)
        if stale_pid is not None and not _pid_is_alive(stale_pid):
            logger.debug(
                "Detected stale lock for %s (PID %d dead), removing.",
                target,
                stale_pid,
            )
            _remove_stale_lock(lock_path, None)

    # --- ensure parent directory exists --------------------------------------
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = _open_lock_file(lock_path)

    try:
        _acquire_exclusive(fd)
    except OSError:
        os.close(fd)
        return None, False

    # --- write our PID into the lock file (POSIX only) -----------------------
    if not _WINDOWS:
        os.truncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)

    return fd, True


class FileLock:
    """Exclusive inter-process file lock using native OS primitives.

    Usage::

        with FileLock(Path("/path/to/data.json")) as lock:
            # safely read/write data.json (other processes are blocked)
            pass

    The lock file is named ``data.json.lock`` and contains the PID of the
    owning process.  Stale locks (dead PID) are detected and removed before
    acquisition.
    """

    def __init__(self, target: Path, timeout: float = 5.0) -> None:
        self._target = Path(target)
        self._lock_path = Path(str(target) + ".lock")
        self._timeout = timeout
        self._fd: Optional[int] = None

    # -- context manager ------------------------------------------------------

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_value: Optional[BaseException],
        traceback: Optional[object],
    ) -> None:
        self.release()

    # -- public API -----------------------------------------------------------

    def acquire(self) -> None:
        """Block until the lock is acquired or *timeout* expires.

        Raises LockTimeoutError when the timeout is reached.
        """
        deadline = time.monotonic() + self._timeout
        last_error: Optional[Exception] = None

        while True:
            fd, acquired = _try_acquire_clean(self._target)
            if fd is not None and acquired:
                self._fd = fd
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LockTimeoutError(
                    f"Could not acquire lock for {self._target} "
                    f"within {self._timeout:.1f}s"
                )
            time.sleep(min(0.05, remaining))

    def release(self) -> None:
        """Release the lock and remove the lock file."""
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        if _WINDOWS:
            try:
                os.close(fd)
            except OSError:
                pass
            time.sleep(0.02)
        else:
            _release_lock(fd)
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            self._lock_path.unlink()
        except OSError:
            pass

    @property
    def target(self) -> Path:
        return self._target

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def acquired(self) -> bool:
        return self._fd is not None