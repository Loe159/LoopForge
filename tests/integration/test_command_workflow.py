"""Integration test: full workflow via application commands."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.builders import temp_home, make_project, make_run
from loopforge.commands.base import execute_command


class CommandWorkflowTests(unittest.TestCase):

    def test_init_run_status_workflow(self):
        """Verify init -> run -> status works end to end."""
        with TemporaryDirectory() as root:
            home = Path(root) / "home"
            ctx = make_project(Path(root), home)
            run_id = make_run(ctx, task="Integration test task")

            status = execute_command("list_runs", ctx)
            self.assertTrue(status.ok)
            self.assertEqual(len(status.data["runs"]), 1)
