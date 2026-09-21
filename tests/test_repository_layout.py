"""Keep compatibility paths thin and executable after repository cleanup."""

from pathlib import Path
import runpy
import subprocess
import sys
import unittest

from loopforge.checks import isolated_process


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_LAUNCHERS = (
    "classify_patch_risk.py",
    "diff_policy.py",
    "generate_complete_patch.py",
    "validate_artifacts.py",
    "validate_implementation_result.py",
)


class RepositoryLayoutTests(unittest.TestCase):
    def test_agent_directory_contains_only_compatibility_sources(self):
        compatibility = REPO_ROOT / ".agent"
        self.assertEqual(
            {path.name for path in compatibility.iterdir() if path.is_dir()},
            {"checks", "adapters"},
        )
        self.assertEqual(
            {path.name for path in (compatibility / "checks").glob("*.py")},
            {*CHECK_LAUNCHERS, "isolated_process.py"},
        )
        for path in compatibility.rglob("*.py"):
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn("from loopforge.", source)
                self.assertNotIn("def ", source, "Product behavior belongs in src/loopforge")

    def test_compatibility_clis_start_without_removed_bootstrap_data(self):
        launchers = [REPO_ROOT / ".agent" / "checks" / name for name in CHECK_LAUNCHERS]
        launchers.append(REPO_ROOT / ".agent" / "adapters" / "local_implementation_adapter.py")
        for launcher in launchers:
            with self.subTest(launcher=launcher.name):
                result = subprocess.run(
                    [sys.executable, str(launcher), "--help"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("usage:", result.stdout.lower())

    def test_process_shim_reuses_packaged_function(self):
        shim = runpy.run_path(str(REPO_ROOT / ".agent" / "checks" / "isolated_process.py"))
        self.assertIs(shim["run"], isolated_process.run)

    def test_documentation_and_contract_have_no_duplicate_root_entry(self):
        self.assertTrue((REPO_ROOT / "docs" / "agent" / "08-flows.md").is_file())
        self.assertTrue((REPO_ROOT / "AGENTS.md").is_file())
        self.assertFalse((REPO_ROOT / "doc" / "08-flows.md").exists())
        self.assertFalse((REPO_ROOT / "agent.md").exists())
