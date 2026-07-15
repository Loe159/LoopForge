"""Compatibility import for :mod:`loopforge.checks.isolated_process`."""

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from loopforge.checks.isolated_process import *  # noqa: F401,F403
