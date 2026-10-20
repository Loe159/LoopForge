from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == "posix", "Installer uses a POSIX shell")
class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "user bin"
        self.bin.mkdir()
        self.launcher = self.bin / "loopforge"
        self.venv_bin = self.root / "environment with spaces" / "bin"
        self.venv_bin.mkdir(parents=True)
        for name, content in (
            ("python", '#!/bin/sh\nexit "${INSTALL_TEST_EXIT:-0}"\n'),
            ("loopforge", "#!/bin/sh\nexit 0\n"),
        ):
            executable = self.venv_bin / name
            executable.write_text(content, encoding="utf-8")
            executable.chmod(0o755)
        self.env = {
            **os.environ,
            "LOOPFORGE_PYTHON": sys.executable,
            "LOOPFORGE_INSTALL_DIR": str(self.venv_bin.parent),
            "LOOPFORGE_BIN_DIR": str(self.bin),
            "INSTALL_TEST_EXIT": "0",
        }
        self.old_launcher = "#!/usr/bin/python3\nfrom loopforge.cli import main\nimport sys\nsys.exit(main())\n"

    def install(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(Path(__file__).resolve().parents[1] / "install.sh")],
            cwd=self.root,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_broken_pip_launcher_is_backed_up_and_replaced(self) -> None:
        self.launcher.write_text(self.old_launcher, encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launcher.resolve(), self.venv_bin / "loopforge")
        backups = list(self.bin.glob("loopforge.backup.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), self.old_launcher)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(len(list(self.bin.glob("loopforge.backup.*"))), 1)

    def test_failed_install_keeps_the_original_launcher(self) -> None:
        self.launcher.write_text(self.old_launcher, encoding="utf-8")
        result = self.install(INSTALL_TEST_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.launcher.is_symlink())
        self.assertEqual(self.launcher.read_text(encoding="utf-8"), self.old_launcher)
        self.assertEqual(list(self.bin.glob("loopforge.backup.*")), [])

    def test_unrecognized_command_is_preserved(self) -> None:
        self.launcher.write_text("another command", encoding="utf-8")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(self.launcher.read_text(encoding="utf-8"), "another command")

    def test_first_install_creates_the_command_link(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launcher.resolve(), self.venv_bin / "loopforge")
