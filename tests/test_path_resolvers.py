from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loopforge.engine.path_resolvers import (
    resolve_artifact,
    resolve_confined,
    resolve_run_dir,
    validate_identifier,
)


class PathResolversTests(unittest.TestCase):
    def test_validate_identifier_rejects_traversal(self):
        for value in ("..", "../foo", "foo/bar", "foo\\bar", "foo:bar",
                       "foo*bar", "", "  ", "-foo", ".foo"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_identifier(value, "test")

    def test_validate_identifier_accepts_valid(self):
        for value in ("project-abc123", "run-2026", "my_project", "test-id-001"):
            with self.subTest(value=value):
                self.assertEqual(validate_identifier(value, "test"), value)

    def test_resolve_confined_blocks_outside(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sub = root / "sub"
            sub.mkdir()
            with self.assertRaises(ValueError):
                resolve_confined(sub, "..", "etc")

    def test_resolve_confined_allows_within(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sub = root / "sub"
            sub.mkdir()
            resolved = resolve_confined(root, "sub", "file.txt")
            self.assertEqual(resolved, root / "sub" / "file.txt")

    def test_resolve_run_dir_rejects_bad_id(self):
        with self.assertRaises(ValueError):
            resolve_run_dir(Path("/tmp"), "../escape")

    def test_resolve_artifact_blocks_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sub = root / "sub"
            sub.mkdir()
            with self.assertRaises(ValueError):
                resolve_artifact(sub, "../outside.txt")

    def test_resolve_artifact_allows_within(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sub = root / "sub"
            sub.mkdir()
            (sub / "data.txt").write_text("hello", encoding="utf-8")
            resolved = resolve_artifact(sub, "data.txt")
            self.assertEqual(resolved, sub / "data.txt")


if __name__ == "__main__":
    unittest.main()