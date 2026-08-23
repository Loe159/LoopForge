from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from loopforge.checks.generate_complete_patch import generate_and_validate
from loopforge.contracts import policy_path


class CompletePatchPathTests(unittest.TestCase):
    def test_complete_patch_accepts_file_with_spaces(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            self._git(repo, "init")
            self._git(repo, "config", "user.name", "LoopForge Tests")
            self._git(repo, "config", "user.email", "loopforge@example.invalid")
            (repo / "README.md").write_text("baseline\n", encoding="utf-8")
            self._git(repo, "add", "README.md")
            self._git(repo, "commit", "-m", "baseline")
            base_commit = self._git(repo, "rev-parse", "HEAD").stdout.strip()

            for content, expected_changed_lines in ((b"", 0), (b"hello\n", 1)):
                with self.subTest(content=content):
                    (repo / "Hello World.txt").write_bytes(content)
                    result = generate_and_validate(
                        repo,
                        base_commit,
                        root / "complete.patch",
                        policy_path("diff-policy.json"),
                        force=True,
                    )

                    self.assertTrue(result["allowed"], result["violations"])
                    self.assertEqual(result["facts"]["paths"], ["Hello World.txt"])
                    self.assertEqual(
                        result["facts"]["changed_lines"],
                        expected_changed_lines,
                    )

    @staticmethod
    def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
