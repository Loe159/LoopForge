"""Linux child subreaper used by ProcessRunner for untrusted pack checks.

The helper is a separate process so PR_SET_CHILD_SUBREAPER cannot change the
parent CLI's process tree or interfere with unrelated subprocesses.
"""

from __future__ import annotations

import ctypes
import errno
import os
import resource
import signal
import subprocess
import sys
import time


_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True


def _children() -> list[int]:
    with open(f"/proc/{os.getpid()}/task/{os.getpid()}/children", encoding="ascii") as stream:
        return [int(pid) for pid in stream.read().split()]


def _reap_except(root_pid: int) -> None:
    for pid in _children():
        if pid == root_pid:
            continue
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


def _kill_child(pid: int) -> None:
    # A pidfd pins the child identity; a reused numeric PID must not be killed.
    descriptor = os.pidfd_open(pid)
    try:
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
    finally:
        os.close(descriptor)


def _fallback_children() -> list[int]:
    """Find adopted children even when the task/children interface fails."""
    parent = os.getpid()
    found: list[int] = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdecimal():
            continue
        try:
            # The command name can contain spaces and parentheses.
            stat = (entry.path + "/stat")
            with open(stat, encoding="ascii") as stream:
                fields = stream.read().rsplit(")", 1)[1].split()
            if int(fields[1]) == parent:
                found.append(int(entry.name))
        except (OSError, IndexError, ValueError):
            continue
    return found


def _emergency_cleanup(root_pid: int, known: dict[int, int], *, root_active: bool) -> None:
    """Best effort after a supervision failure; callers never certify clean."""
    # The session leader is not reaped while this runs, so its numeric PGID
    # cannot be recycled. A previously reaped leader needs pidfd/PPID cleanup.
    if root_active:
        try:
            os.killpg(root_pid, signal.SIGKILL)
        except OSError:
            pass
    for descriptor in known.values():
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        except OSError:
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            candidates = set(_children())
        except OSError:
            try:
                candidates = set(_fallback_children())
            except OSError:
                candidates = set()
        for pid in candidates:
            try:
                _kill_child(pid)
            except (OSError, AttributeError):
                pass
        try:
            _reap_except(root_pid)
        except OSError:
            pass
        try:
            if not (_children() or _fallback_children()):
                break
        except OSError:
            pass
        time.sleep(0.01)


def main() -> int:
    report_fd = int(sys.argv[1])
    command = sys.argv[2:]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        os.write(report_fd, b"unverified:subreaper setup failed\n")
        return 125
    try:
        _children()
        probe = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(probe, 0)
        finally:
            os.close(probe)
    except (OSError, AttributeError) as error:
        os.write(report_fd, f"unverified:supervision unavailable: {error}\n".encode("utf-8", "replace"))
        return 125
    signal.signal(signal.SIGTERM, _request_stop)
    try:
        child = subprocess.Popen(command, stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                                 stderr=sys.stderr.buffer, close_fds=True,
                                 start_new_session=True)
    except OSError as error:
        os.write(report_fd, f"unverified:launch failed: {error}\n".encode("utf-8", "replace"))
        return 125

    root_status: int | None = None
    failure = ""
    known_children: dict[int, int] = {}
    # Keep a few identities for failure cleanup, while leaving enough file
    # descriptors for /proc scans, report writing, and per-child pidfd kills.
    known_limit = max(0, min(8, resource.getrlimit(resource.RLIMIT_NOFILE)[0] - 24))
    while True:
        if root_status is None:
            root_status = child.poll()
        try:
            _reap_except(child.pid)
            descendants = _children()
            active = set(descendants)
            for pid in list(known_children):
                if pid not in active:
                    os.close(known_children.pop(pid))
            for pid in descendants:
                if pid not in known_children and len(known_children) < known_limit:
                    try:
                        known_children[pid] = os.pidfd_open(pid)
                    except ProcessLookupError:
                        continue
                    except OSError as error:
                        if error.errno == errno.EMFILE:
                            for descriptor in known_children.values():
                                os.close(descriptor)
                            known_children.clear()
                            break
                        raise
        except OSError as error:
            failure = f"child inspection failed: {error}"
            break
        if _stop:
            # Kill direct children, then repeat: orphaned grandchildren are
            # reparented here by the subreaper before they can escape cleanup.
            for pid in descendants:
                try:
                    _kill_child(pid)
                except ProcessLookupError:
                    continue
                except (OSError, AttributeError) as error:
                    failure = f"child termination failed: {error}"
            if failure:
                break
            if not descendants:
                break
        elif root_status is not None and not descendants:
            break
        time.sleep(0.01)

    if _stop and not failure:
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            try:
                _reap_except(child.pid)
                if child.poll() is None:
                    child.poll()
                if not _children():
                    break
            except OSError as error:
                failure = f"child inspection failed: {error}"
                break
            time.sleep(0.01)
        else:
            failure = "children remained after termination"

    if failure:
        _emergency_cleanup(child.pid, known_children, root_active=child.poll() is None)
        os.write(report_fd, f"unverified:{failure}\n".encode("utf-8", "replace"))
        for descriptor in known_children.values():
            os.close(descriptor)
        return 125
    os.write(report_fd, f"clean:{root_status}\n".encode("ascii"))
    for descriptor in known_children.values():
        os.close(descriptor)
    return 128 + signal.SIGTERM if _stop else (root_status or 0)


if __name__ == "__main__":
    raise SystemExit(main())
