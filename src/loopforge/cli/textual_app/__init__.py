"""Textual foundation for LoopForge's full-screen interface.

This package is imported only by the interactive backend selector. Keeping the
import boundary here ensures normal CLI commands, scripts, JSON, and CSV paths
never import Textual.
"""

from loopforge.cli.textual_app.app import LoopForgeApp

__all__ = ["LoopForgeApp"]
