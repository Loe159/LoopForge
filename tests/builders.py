"""Factory builders for LoopForge tests.

All factories use the public engine API and application commands to create
test state — never writing to run.json directly.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import loopforge.commands  # noqa: F401 — registers all commands
from loopforge.commands.base import CommandContext, execute_command
from loopforge.engine.models.scope import ActionScope


def temp_home() -> tuple[TemporaryDirectory, Path]:
    """Return a (tempdir, home_path) pair for an isolated LOOPFORGE_HOME."""
    td = TemporaryDirectory()
    return td, Path(td.name)


def make_project(root: Path, home: Path, *, name: str = "test-project", profile: str = "supervised") -> CommandContext:
    """Create an initialized project and return its CommandContext."""
    project_dir = root / name
    project_dir.mkdir(parents=True, exist_ok=True)
    ctx = CommandContext(project_dir=project_dir, home=home, renderer=None)
    result = execute_command("init", ctx, profile=profile)
    assert result.ok, f"init failed: {result.errors}"
    return ctx


def make_run(ctx: CommandContext, *, task: str = "Test task", success_checks: list[str] | None = None, pack: str | None = None) -> str:
    """Create a run and return its run_id."""
    if success_checks is None:
        success_checks = ["tests pass"]
    result = execute_command("start_run", ctx, task=task, success_checks=success_checks, pack=pack)
    assert result.ok, f"start_run failed: {result.errors}"
    return result.data["run_id"]


def make_action_scope(project_id: str, project_path: Path, run_id: str | None = None) -> ActionScope:
    """Build an ActionScope for testing."""
    return ActionScope(
        project_id=project_id,
        project_path=project_path,
        run_id=run_id,
    )


def make_config(**overrides: Any) -> dict[str, Any]:
    """Build a minimal config dict for testing (does NOT persist)."""
    config = {
        "schema_version": 2,
        "project_id": "test-project-id",
        "project_name": "test-project",
        "profile": "supervised",
        "run_root": "/tmp/runs",
        "current_run_id": None,
        "default_adapter": "codex",
        "default_adapter_args": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    config.update(overrides)
    return config
