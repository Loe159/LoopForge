"""Full-screen Textual application facade for the interactive LoopForge shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopforge.cli.interactive import InteractiveShell


def run_fullscreen_console(shell: "InteractiveShell") -> int:
    """Start LoopForge's sole full-screen Textual application."""

    from loopforge.cli.textual_app import LoopForgeApp

    LoopForgeApp(shell).run()
    return 0
