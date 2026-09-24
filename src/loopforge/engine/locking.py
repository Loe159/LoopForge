"""Cross-platform locks shared by JSON repositories.

Lock files deliberately persist: unlinking one while a waiter has it open
creates two independently lockable inodes. The kernel, not a stored PID or
file age, decides whether a lock is held and releases it after a crash.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
import threading
import time
import weakref

_WINDOWS = os.name == "nt"

if _WINDOWS:
    import msvcrt
else:
    import fcntl


class LockTimeoutError(TimeoutError):
    """The lock could not be acquired within its deadline."""


_THREAD_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = (
    weakref.WeakValueDictionary()
)
_THREAD_LOCKS_GUARD = threading.Lock()
_ACTIVE_FDS: set[int] = set()
_ACTIVE_FDS_GUARD = threading.RLock()


def _before_fork() -> None:
    _ACTIVE_FDS_GUARD.acquire()


def _after_fork_parent() -> None:
    _ACTIVE_FDS_GUARD.release()


def _after_fork_child() -> None:
    """Discard parent lock state without unlocking the parent's file locks."""
    global _THREAD_LOCKS, _THREAD_LOCKS_GUARD, _ACTIVE_FDS, _ACTIVE_FDS_GUARD
    for fd in _ACTIVE_FDS:
        try:
            os.close(fd)
        except OSError:
            pass
    _ACTIVE_FDS = set()
    _ACTIVE_FDS_GUARD = threading.RLock()
    _THREAD_LOCKS = weakref.WeakValueDictionary()
    _THREAD_LOCKS_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_parent,
        after_in_child=_after_fork_child,
    )


def _close_tracked_fd(fd: int) -> None:
    with _ACTIVE_FDS_GUARD:
        try:
            os.close(fd)
        finally:
            _ACTIVE_FDS.discard(fd)


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(str(lock_path)))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _read_lock_pid(lock_path: Path) -> int | None:
    """Read diagnostic ownership metadata; never use it to break a lock."""
    if _WINDOWS:
        return None
    try:
        pid = int(lock_path.read_text(encoding="ascii").strip())
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


class FileLock:
    """Exclusive, non-reentrant lock across threads and processes.

    Each acquiring thread owns its own file descriptor, including when a
    repository shares this FileLock instance between worker threads.
    """

    def __init__(self, target: Path, timeout: float = 5.0) -> None:
        if timeout < 0:
            raise ValueError("lock timeout must be non-negative")
        self._target = Path(target)
        self._lock_path = Path(str(target) + ".lock")
        self._timeout = timeout
        self._local = threading.local()
        self._thread_lock = _thread_lock_for(self._lock_path)
        self._pid = os.getpid()

    def _refresh_after_fork(self) -> None:
        current_pid = os.getpid()
        if current_pid != self._pid:
            self._local = threading.local()
            self._thread_lock = _thread_lock_for(self._lock_path)
            self._pid = current_pid

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()

    def acquire(self) -> None:
        self._refresh_after_fork()
        if self.acquired:
            raise RuntimeError("FileLock is not reentrant")
        deadline = time.monotonic() + self._timeout
        thread_acquired = False
        fd: int | None = None
        try:
            while not self._thread_lock.acquire(blocking=False):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockTimeoutError(
                        f"Could not acquire lock for {self._target} "
                        f"within {self._timeout:.1f}s"
                    )
                time.sleep(min(0.01, remaining))
            thread_acquired = True
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR
            if _WINDOWS:
                flags |= os.O_BINARY
            with _ACTIVE_FDS_GUARD:
                fd = os.open(str(self._lock_path), flags, 0o600)
                _ACTIVE_FDS.add(fd)
            while True:
                try:
                    if _WINDOWS:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LockTimeoutError(
                            f"Could not acquire lock for {self._target} "
                            f"within {self._timeout:.1f}s"
                        ) from error
                    time.sleep(min(0.01, remaining))
            if not _WINDOWS:
                os.ftruncate(fd, 0)
                os.write(fd, str(os.getpid()).encode("ascii"))
            self._local.fd = fd
        except BaseException:
            try:
                if fd is not None:
                    _close_tracked_fd(fd)
            finally:
                if thread_acquired:
                    self._thread_lock.release()
            raise

    def release(self) -> None:
        self._refresh_after_fork()
        fd = getattr(self._local, "fd", None)
        if fd is None:
            return
        self._local.fd = None
        try:
            if _WINDOWS:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            try:
                _close_tracked_fd(fd)
            finally:
                self._thread_lock.release()

    @property
    def target(self) -> Path:
        return self._target

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def acquired(self) -> bool:
        self._refresh_after_fork()
        return getattr(self._local, "fd", None) is not None
