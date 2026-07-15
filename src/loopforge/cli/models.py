"""Data models shared by the LoopForge command-line interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CliOptions:
    no_color: bool = False
    no_input: bool = False
    quiet: bool = False
    debug: bool = False
    version: bool = False
    json: bool = False


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
