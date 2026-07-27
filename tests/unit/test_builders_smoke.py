"""Smoke test: verify builders work via public API."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.builders import temp_home, make_project, make_run, make_action_scope, make_config
from loopforge.commands.base import execute_command


class BuildersSmokeTests(unittest.TestCase):

    def test_make_project_creates_config(self):
        with TemporaryDirectory() as root:
            home = Path(root) / "home"
            ctx = make_project(Path(root), home)
            self.assertTrue((ctx.project_dir / ".loopforge" / "config.json").exists())

    def test_make_run_returns_run_id(self):
        with TemporaryDirectory() as root:
            home = Path(root) / "home"
            ctx = make_project(Path(root), home)
            run_id = make_run(ctx)
            self.assertTrue(run_id.startswith("run-"))

    def test_make_action_scope(self):
        scope = make_action_scope("p1", Path("/tmp"))
        self.assertEqual(scope.project_id, "p1")

    def test_make_config_has_required_keys(self):
        config = make_config()
        self.assertIn("project_id", config)
        self.assertIn("schema_version", config)
