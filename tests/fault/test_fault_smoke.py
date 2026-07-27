"""Smoke test for fault suite."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.builders import make_project
from loopforge.commands.base import execute_command


class FaultSuiteSmokeTests(unittest.TestCase):

    def test_corrupt_config_handled(self):
        """Verify a corrupt config doesn't crash the engine."""
        with TemporaryDirectory() as root:
            home = Path(root) / "home"
            ctx = make_project(Path(root), home)

            # Corrupt the config
            config_path = ctx.project_dir / ".loopforge" / "config.json"
            config_path.write_text("{corrupt!!!", encoding="utf-8")

            # Engine should handle gracefully
            result = execute_command("doctor", ctx)
            self.assertIsInstance(result.data, dict)
