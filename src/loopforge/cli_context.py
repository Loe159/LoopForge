"""Invocation context shared by LoopForge CLI command handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from loopforge.ui import TerminalRenderer


@dataclass(frozen=True)
class CliContext:
    """Per-invocation dependencies shared by command handlers."""

    api: Any
    options: Any
    parser: Any
    renderer: TerminalRenderer
    project_dir: Path
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    def error_renderer(self) -> TerminalRenderer:
        return self.api.TerminalRenderer(self.stderr, no_color=self.options.no_color)
