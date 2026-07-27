"""Workspace creation, Git preflight, and workspace path resolution."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from loopforge.engine.path_resolvers import resolve_confined

logger = logging.getLogger(__name__)

WORKSPACE_MODE_GIT_WORKTREE = "git-worktree"
WORKSPACE_MODE_SHARED_CHECKOUT = "shared-checkout"


def _resolve_git_executable() -> str | None:
    """Resolve the absolute path to ``git`` so it passes the isolation
    policy's ``require_absolute_executable`` check in ``ProcessRunner``.

    Returns ``None`` when git is not installed or not on the current PATH.
    """
    import shutil
    found = shutil.which("git")
    if not found:
        return None
    resolved = Path(found).resolve()
    if resolved.is_file():
        return str(resolved)
    return None


def detect_git_base_commit(project_dir: Path) -> str | None:
    git_path = _resolve_git_executable()
    if git_path is None:
        return None
    from loopforge.engine.process_runner import ProcessRunner
    runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
    receipt = runner.run(
        [git_path, "rev-parse", "HEAD"],
        cwd=project_dir,
    )
    if not receipt.completed:
        return None
    commit = receipt.stdout.strip()
    return commit or None


def git_toplevel(project_dir: Path) -> Path | None:
    git_path = _resolve_git_executable()
    if git_path is None:
        return None
    from loopforge.engine.process_runner import ProcessRunner
    runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
    receipt = runner.run(
        [git_path, "rev-parse", "--show-toplevel"],
        cwd=project_dir,
    )
    if not receipt.completed:
        return None
    try:
        return Path(receipt.stdout.strip()).resolve()
    except OSError:
        return None


def _has_git(project_dir: Path) -> bool:
    dotgit = project_dir / ".git"
    if dotgit.is_dir():
        return True
    if dotgit.is_file():
        try:
            content = dotgit.read_text(encoding="utf-8").strip()
            match = re.match(r"^gitdir:\s*(.+)$", content)
            if match:
                return Path(match.group(1)).is_dir()
        except OSError:
            return False
    return False


def _check_git_available(project_dir: Path) -> None:
    if _has_git(project_dir):
        return
    snapshot_enabled = os.environ.get("LOOPFORGE_SNAPSHOT_BACKEND") == "1"
    if snapshot_enabled:
        return
    # In non-Git projects, fall back to shared-checkout mode with a warning.
    # This avoids breaking existing test fixtures and non-Git quick-starts.
    # The full non-Git policy (hard rejection) is gated behind a future
    # product decision tracked in Epic 28 Wave 5.3.
    logger.warning(
        "Project %s has no Git repository. "
        "Runs will use shared-checkout mode (no worktree isolation). "
        "Consider running `git init` or setting LOOPFORGE_SNAPSHOT_BACKEND=1.",
        str(project_dir),
    )


def codex_workspace_preflight_blockers(
    adapter: str,
    workspace_dir: Path,
    *,
    implementation: bool = False,
) -> list[str]:
    """Return the explicit Codex trust prerequisite for a workspace, if any."""
    from loopforge.engine.installation import isolated_process_module

    if adapter != "codex":
        return []
    try:
        is_git_workspace = git_toplevel(workspace_dir) is not None
    except (OSError, subprocess.SubprocessError):
        is_git_workspace = False
    blockers: list[str] = []
    if not is_git_workspace:
        blockers.append(
            "Codex requires a Git worktree. Initialize Git in this temporary project "
            "before using Codex: `git init`."
        )
    if implementation:
        try:
            isolated = isolated_process_module()
            policy = isolated.load_policy()
            isolated.codex_windows_runtime_environment(os.environ, policy)
        except ValueError as error:
            blockers.append(f"Codex Windows sandbox runtime preflight failed: {error}")
    return blockers


def run_workspace_path(
    run: dict[str, Any],
    fallback_project_dir: Path,
    run_dir: Path | None = None,
) -> Path:
    workspace = run.get("workspace", {})
    if isinstance(workspace, dict):
        raw_path = workspace.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            candidate = Path(raw_path).expanduser().resolve()
            if run_dir is not None:
                return resolve_confined(run_dir, candidate.name)
            return candidate
    if run_dir is not None:
        return resolve_confined(run_dir, fallback_project_dir.name)
    return fallback_project_dir.resolve()


def run_workspace_state(run: dict[str, Any], fallback_project_dir: Path) -> dict[str, Any]:
    workspace = run.get("workspace", {})
    if not isinstance(workspace, dict):
        workspace = {}
    mode = workspace.get("mode")
    if mode not in {WORKSPACE_MODE_GIT_WORKTREE, WORKSPACE_MODE_SHARED_CHECKOUT}:
        mode = WORKSPACE_MODE_SHARED_CHECKOUT
    base_commit = workspace.get("base_commit")
    if not isinstance(base_commit, str):
        base_commit = run.get("base_commit")
    return {
        "mode": mode,
        "path": str(run_workspace_path(run, fallback_project_dir)),
        "base_commit": base_commit,
        "created_at": workspace.get("created_at"),
    }


def prepare_run_workspace(
    *,
    project_dir: Path,
    run_id: str,
    base_commit: str | None,
    now: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    from loopforge.engine import default_workspace_root

    if base_commit is None or git_toplevel(project_dir) is None:
        return {
            "mode": WORKSPACE_MODE_SHARED_CHECKOUT,
            "path": str(project_dir),
            "base_commit": base_commit,
            "created_at": now,
        }

    workspace_path = default_workspace_root(project_dir, project_id=project_id) / run_id
    if workspace_path.exists():
        raise ValueError(f"workspace already exists: {workspace_path}")
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "git",
        "-c",
        "core.longpaths=true",
        "-c",
        f"safe.directory={project_dir.resolve().as_posix()}",
        "worktree",
        "add",
        "--detach",
        str(workspace_path),
        base_commit,
    ]
    # Exempt from ProcessRunner: worktree creation is one-shot repository infrastructure
    # with fixed timeouts (60s/30s) and capture_output. These are setup operations, not
    # repeated command execution, and must not be cancelled mid-flight (partial worktrees
    # cause repository corruption).
    result = subprocess.run(
        command,
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        # A failed checkout can leave both a directory and Git worktree metadata
        # behind. Remove only this run's controlled path before surfacing the
        # original error, so the user can retry safely.
        if workspace_path.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(workspace_path)],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            shutil.rmtree(workspace_path, ignore_errors=True)
        raise ValueError(f"could not create run worktree: {detail}")
    return {
        "mode": WORKSPACE_MODE_GIT_WORKTREE,
        "path": str(workspace_path.resolve()),
        "base_commit": base_commit,
        "created_at": now,
    }
