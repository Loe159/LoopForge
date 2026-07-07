from __future__ import annotations

import contextlib
import io
import unittest

from loopforge.cli import main


class CliTests(unittest.TestCase):
    def test_status_placeholder(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["status"]), 0)
        self.assertIn("LoopForge status is planned", output.getvalue())


if __name__ == "__main__":
    unittest.main()
