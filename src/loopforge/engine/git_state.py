"""Cached Git read models for project navigation.

The common path reads Git's small metadata files directly.  Git subprocesses
are reserved for unusual layouts and are never needed by render callbacks.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


FALLBACK_TIMEOUT_SECONDS = 0.25


@dataclass(frozen=True)
class GitState:
    """A bounded, display-ready snapshot of a project's Git state."""

    project_dir: Path
    branch: str | None
    head: str | None
    dirty: bool | None
    state: str
    signature: str | None

    @property
    def available(self) -> bool:
        return self.state in {"ready", "detached"}

    @property
    def head_signature(self) -> str | None:
        return self.signature


@dataclass(frozen=True)
class _DirectRead:
    state: GitState
    needs_fallback: bool = False


class GitStateService:
    """Cache Git state by resolved project path and cheap HEAD signatures."""

    def __init__(self, *, fallback_timeout: float = FALLBACK_TIMEOUT_SECONDS) -> None:
        self.fallback_timeout = fallback_timeout
        self._cache: dict[Path, GitState] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loopforge-git")

    @staticmethod
    def _file_signature(path: Path, content: str) -> str:
        try:
            stat = path.stat()
            metadata = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            metadata = "missing"
        return f"{metadata}:{content}"

    @staticmethod
    def _resolve_git_dir(project_dir: Path) -> tuple[Path | None, str | None]:
        dot_git = project_dir / ".git"
        try:
            if dot_git.is_dir():
                return dot_git, None
            if not dot_git.is_file():
                return None, "not_repository"
            value = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None, "unavailable"
        if not value.startswith("gitdir:"):
            return None, "unavailable"
        git_dir = Path(value.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (project_dir / git_dir).resolve()
        return git_dir, None

    @staticmethod
    def _packed_ref(git_dir: Path, reference: str) -> tuple[str | None, str]:
        packed_refs = git_dir / "packed-refs"
        try:
            content = packed_refs.read_text(encoding="utf-8")
        except OSError:
            return None, ""
        for line in content.splitlines():
            if line and not line.startswith(("#", "^")):
                value, _, name = line.partition(" ")
                if name == reference:
                    return value, self._file_signature(packed_refs, content)
        return None, self._file_signature(packed_refs, content)

    def _read_direct(self, project_dir: Path) -> _DirectRead:
        git_dir, error = self._resolve_git_dir(project_dir)
        if git_dir is None:
            return _DirectRead(GitState(project_dir, None, None, None, error or "unavailable", error))
        head_path = git_dir / "HEAD"
        try:
            head_value = head_path.read_text(encoding="utf-8").strip()
        except OSError:
            return _DirectRead(
                GitState(project_dir, None, None, None, "unavailable", "missing-head"),
                needs_fallback=True,
            )
        head_signature = self._file_signature(head_path, head_value)
        if not head_value.startswith("ref: "):
            if head_value:
                return _DirectRead(GitState(project_dir, None, head_value, None, "detached", head_signature))
            return _DirectRead(
                GitState(project_dir, None, None, None, "unavailable", head_signature),
                needs_fallback=True,
            )
        reference = head_value[5:].strip()
        if not reference:
            return _DirectRead(
                GitState(project_dir, None, None, None, "unavailable", head_signature),
                needs_fallback=True,
            )
        ref_path = git_dir / reference
        try:
            ref_value = ref_path.read_text(encoding="utf-8").strip()
            ref_signature = self._file_signature(ref_path, ref_value)
        except OSError:
            ref_value, ref_signature = self._packed_ref(git_dir, reference)
        branch = reference.removeprefix("refs/heads/") if reference.startswith("refs/heads/") else None
        signature = f"{head_signature}:{reference}:{ref_signature or 'unresolved'}"
        # A freshly initialized repository has no loose ref yet; the branch is
        # still known without needing to launch Git.
        return _DirectRead(GitState(project_dir, branch, ref_value, None, "ready", signature))

    def get(self, project_dir: Path, *, allow_fallback: bool = False) -> GitState:
        """Return the current cached/direct state without invoking Git normally."""

        try:
            resolved = project_dir.resolve()
        except OSError:
            resolved = project_dir
        direct = self._read_direct(resolved)
        with self._lock:
            cached = self._cache.get(resolved)
            if cached is not None and cached.signature == direct.state.signature:
                return cached
        if direct.needs_fallback and allow_fallback:
            return self._fallback(resolved, previous=cached, signature=direct.state.signature)
        if direct.state.state == "unavailable" and cached is not None and cached.available:
            state = GitState(resolved, cached.branch, cached.head, cached.dirty, "stale", direct.state.signature)
        else:
            state = direct.state
        with self._lock:
            self._cache[resolved] = state
        return state

    def refresh(self, project_dir: Path) -> GitState:
        """Explicitly refresh, using a bounded fallback only when direct reads fail."""

        return self.get(project_dir, allow_fallback=True)

    def refresh_background(self, project_dir: Path) -> Future[GitState]:
        """Run the exceptional subprocess fallback outside a UI callback."""

        return self._executor.submit(self.refresh, project_dir)

    def invalidate(self, project_dir: Path) -> None:
        try:
            project_dir = project_dir.resolve()
        except OSError:
            pass
        with self._lock:
            self._cache.pop(project_dir, None)

    def _fallback(self, project_dir: Path, *, previous: GitState | None, signature: str | None) -> GitState:
        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.fallback_timeout,
            )
            head_result = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.fallback_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            if previous is not None and previous.available:
                state = GitState(project_dir, previous.branch, previous.head, previous.dirty, "stale", signature)
            else:
                state = GitState(project_dir, None, None, None, "unavailable", signature)
        else:
            branch_value = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
            head_value = head_result.stdout.strip() if head_result.returncode == 0 else None
            if not branch_value and head_value is None:
                state = GitState(project_dir, None, None, None, "unavailable", signature)
            elif branch_value == "HEAD":
                state = GitState(project_dir, None, head_value, None, "detached", signature)
            else:
                state = GitState(project_dir, branch_value or None, head_value, None, "ready", signature)
        with self._lock:
            self._cache[project_dir] = state
        return state


DEFAULT_GIT_STATE_SERVICE = GitStateService()
