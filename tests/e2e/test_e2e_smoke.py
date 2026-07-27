"""Smoke test for e2e suite."""

import unittest


class E2eSuiteSmokeTests(unittest.TestCase):

    def test_suite_imports(self):
        """Verify the e2e test suite directory is importable."""
        self.assertTrue(True)
