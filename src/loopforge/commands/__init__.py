"""Unified application commands for LoopForge.

Each command wraps a single mutating engine operation into an
AppCommandResult, providing one behavior path across top-level CLI,
slash shell, and TUI.
"""

from loopforge.commands.base import (
    CommandContext,
    execute_command,
    register_command,
)
from loopforge.commands.init import InitProject
from loopforge.commands.run import StartRun, ResumeRun
from loopforge.commands.approve import ApproveStage
from loopforge.commands.stage import ExecuteStage
from loopforge.commands.verify import VerifyRun
from loopforge.commands.review import ReviewRun
from loopforge.commands.archive import ArchiveRun
from loopforge.commands.doctor import Doctor
from loopforge.commands.learn import LearnRun
from loopforge.commands.list_commands import ListRuns
from loopforge.commands.open_project import OpenProject

__all__ = [
    "CommandContext",
    "execute_command",
    "register_command",
    "InitProject",
    "OpenProject",
    "StartRun",
    "ResumeRun",
    "ApproveStage",
    "ExecuteStage",
    "VerifyRun",
    "ReviewRun",
    "ArchiveRun",
    "Doctor",
    "LearnRun",
    "ListRuns",
]
