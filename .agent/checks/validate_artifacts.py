#!/usr/bin/env python3
"""Compatibility launcher for :mod:`loopforge.checks.validate_artifacts`."""

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from loopforge.checks.validate_artifacts import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
