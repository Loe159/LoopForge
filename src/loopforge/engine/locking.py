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

_WINDOWS = os.name == "nt"

if _WINDOWS:
    import msvcrt
else:
    import fcntl


class LockTimeoutError(TimeoutError):
    """The lock could not be acquired within its deadline."""


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

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()

    def acquire(self) -> None:
        if self.acquired:
            raise RuntimeError("FileLock is not reentrant")
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if _WINDOWS:
            flags |= os.O_BINARY
        fd = os.open(str(self._lock_path), flags, 0o600)
        deadline = time.monotonic() + self._timeout
        try:
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
            os.close(fd)
            raise

    def release(self) -> None:
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
            os.close(fd)

    @property
    def target(self) -> Path:
        return self._target

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def acquired(self) -> bool:
        return getattr(self._local, "fd", None) is not None
