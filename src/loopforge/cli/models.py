"""Data models shared by the LoopForge command-line interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from loopforge.cli.operations import OperationEvent
    from loopforge.cli.presentation import ShellSnapshot


# These explicit values deliberately travel with every screen snapshot.  A UI
# must never interpret absent data as a loading state.
SNAPSHOT_STATES = frozenset({"loading", "ready", "stale", "empty", "blocked", "failed"})


@dataclass(frozen=True)
class HomeSnapshot:
    state: str
    projects: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSnapshot:
    state: str
    project: Path | None = None
    shell: "ShellSnapshot | None" = None
    runs: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()
    branch: str = "no Git branch"


@dataclass(frozen=True)
class RunSnapshot:
    state: str
    shell: "ShellSnapshot | None" = None


@dataclass(frozen=True)
class EvidenceSnapshot:
    state: str
    items: tuple[Any, ...] = ()
    query: str = ""


@dataclass(frozen=True)
class SettingsSnapshot:
    state: str = "ready"
    values: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class OperationSnapshot:
    state: str = "empty"
    operation_id: str | None = None
    label: str = ""
    events: tuple["OperationEvent", ...] = ()
    finished: bool = False
    cancelled: bool = False
    message: str = ""


@dataclass(frozen=True)
class UiSnapshot:
    """One immutable, revisioned view of all live console state."""

    revision: int
    reasons: tuple[str, ...]
    selected_project: Path | None
    selected_run_id: str | None
    home: HomeSnapshot
    project: ProjectSnapshot
    run: RunSnapshot
    evidence: EvidenceSnapshot
    settings: SettingsSnapshot
    operation: OperationSnapshot


@dataclass(frozen=True)
class CliOptions:
    no_color: bool = False
    plain: bool = False
    no_input: bool = False
    quiet: bool = False
    debug: bool = False
    version: bool = False
    json: bool = False
    interactive_ui: bool = False


@dataclass(frozen=True)
class GitHubIssueRef:
    owner: str
    repo: str
    number: int
    url: str


@dataclass
class RunIntake:
    task: str
    success_checks: list[str]
    allowed_tools: list[str]
    subjective_rubric: str = ""
    source_metadata: dict[str, Any] | None = None
    initial_approval: dict[str, Any] | None = None
    notes: list[str] | None = None


@dataclass
class IssueReadResult:
    ok: bool
    issue: dict[str, Any] | None = None
    reason: str = ""
