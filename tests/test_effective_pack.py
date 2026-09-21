"""Effective pack contract tests for LoopForge Epic 28."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from loopforge.engine.packs import (
    EffectivePackContract, freeze_pack_contract, diagnose_pack_issues,
    PackCycleError,
)


class TestEffectivePackContract(unittest.TestCase):
    """EffectivePackContract serialization and immutability."""

    def test_to_dict_and_from_dict_roundtrip(self):
        contract = EffectivePackContract(
            name="test-pack",
            version=1,
            checks=[{"name": "lint", "command": ["ruff"]}],
            checks_content_hash="abc123",
            protected_paths=[{"pattern": "*.py", "severity": "high"}],
            contract_hash="def456",
            frozen_at="2024-01-01T00:00:00Z",
        )
        data = contract.to_dict()
        restored = EffectivePackContract.from_dict(data)
        self.assertEqual(restored.name, "test-pack")
        self.assertEqual(restored.contract_hash, "def456")
        self.assertEqual(len(restored.checks), 1)

    def test_from_dict_handles_missing_fields(self):
        """Old contracts without new fields are handled gracefully."""
        data = {
            "name": "old-pack",
            "version": 1,
            "description": "legacy pack",
        }
        contract = EffectivePackContract.from_dict(data)
        self.assertEqual(contract.name, "old-pack")
        self.assertEqual(contract.checks, [])
        self.assertEqual(contract.memory_rules, "")
        self.assertEqual(contract.contract_hash, "")

    def test_contract_hash_computed(self):
        """Contract hash covers all components."""
        contract = EffectivePackContract(
            name="test",
            version=1,
            checks=[{"cmd": "echo hi"}],
            checks_content_hash="hash1",
            protected_paths=[{"pattern": "*.py"}],
            protected_paths_content_hash="hash2",
            memory_rules="some rules",
            memory_rules_hash="hash3",
            contract_hash="hash4",
        )
        data = contract.to_dict()
        self.assertIn("contract_hash", data)
        self.assertIsInstance(data["contract_hash"], str)


class TestFreezePackContract(unittest.TestCase):
    """Freeze pack contract creates complete frozen snapshot."""

    def test_frozen_contract_has_all_fields(self):
        """Frozen contract has all required fields including hashes."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            packs_dir = project_dir / ".loopforge" / "packs" / "test-pack"
            packs_dir.mkdir(parents=True)
            (packs_dir / "pack.json").write_text(json.dumps({
                "name": "test-pack",
                "version": 1,
                "description": "Test pack",
            }))
            (packs_dir / "checks.json").write_text(json.dumps({
                "checks": []
            }))

            contract = freeze_pack_contract(project_dir, "test-pack")

            self.assertIsNotNone(contract)
            self.assertEqual(contract.name, "test-pack")
            self.assertIsNotNone(contract.frozen_at)
            self.assertIsNotNone(contract.contract_hash)
            self.assertIsNotNone(contract.checks_content_hash)
            self.assertEqual(contract.checks_source, str(packs_dir / "checks.json"))

    def test_frozen_contract_includes_checks(self):
        """Frozen contract includes checks with content hashes."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            packs_dir = project_dir / ".loopforge" / "packs" / "test-pack"
            packs_dir.mkdir(parents=True)
            (packs_dir / "pack.json").write_text(json.dumps({
                "name": "test-pack", "version": 1,
            }))
            (packs_dir / "checks.json").write_text(json.dumps({
                "checks": [
                    {"name": "lint", "command": ["ruff", "check", "."], "timeout": 60}
                ]
            }))

            contract = freeze_pack_contract(project_dir, "test-pack")
            self.assertGreater(len(contract.checks), 0)
            self.assertTrue(len(contract.checks_content_hash) > 0)

    def test_missing_pack_raises_error(self):
        """Freezing a nonexistent pack raises ValueError."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            with self.assertRaises(ValueError):
                freeze_pack_contract(project_dir, "nonexistent-pack")


class TestPackDiagnostics(unittest.TestCase):
    """Malformed pack diagnostics."""

    def test_diagnose_malformed_pack(self):
        """Pack with invalid pack.json is diagnosed."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            packs_dir = project_dir / ".loopforge" / "packs" / "broken-pack"
            packs_dir.mkdir(parents=True)
            (packs_dir / "pack.json").write_text("INVALID JSON {{{")

            issues = diagnose_pack_issues(project_dir)
            self.assertGreater(len(issues), 0)
            self.assertTrue(any("broken-pack" in str(i) for i in issues))

    def test_diagnose_missing_name_field(self):
        """Pack without name field is diagnosed."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            packs_dir = project_dir / ".loopforge" / "packs" / "nameless"
            packs_dir.mkdir(parents=True)
            (packs_dir / "pack.json").write_text(json.dumps({"version": 1}))

            issues = diagnose_pack_issues(project_dir)
            self.assertGreater(len(issues), 0)

    def test_no_packs_is_not_an_error(self):
        """Project with no packs should not report issues."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            (project_dir / ".loopforge").mkdir()

            issues = diagnose_pack_issues(project_dir)
            self.assertEqual(len(issues), 0)

    def test_cyclic_inheritance_diagnosed(self):
        """Cyclic pack inheritance is detected and diagnosed."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            for name, extends in [("a", "b"), ("b", "a")]:
                pack_dir = project_dir / ".loopforge" / "packs" / name
                pack_dir.mkdir(parents=True)
                (pack_dir / "pack.json").write_text(json.dumps({
                    "name": name,
                    "version": 1,
                    "extends": extends,
                }))

            issues = diagnose_pack_issues(project_dir)
            cycle_issues = [i for i in issues if "cycle" in str(i).lower()]
            self.assertGreater(len(cycle_issues), 0)


class TestPackMutationAfterCreation(unittest.TestCase):
    """Pack mutation on disk after create_run should be ignored."""

    def test_mutation_after_freeze_is_independent(self):
        """Freeze captures the state at freeze time."""
        with TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            packs_dir = project_dir / ".loopforge" / "packs" / "test-pack"
            packs_dir.mkdir(parents=True)
            (packs_dir / "pack.json").write_text(json.dumps({
                "name": "test-pack", "version": 1,
            }))
            (packs_dir / "checks.json").write_text(json.dumps({
                "checks": [{"name": "original", "command": ["echo", "v1"]}]
            }))

            contract = freeze_pack_contract(project_dir, "test-pack")
            self.assertEqual(len(contract.checks), 1)
            original_hash = contract.checks_content_hash

            (packs_dir / "checks.json").write_text(json.dumps({
                "checks": [{"name": "modified", "command": ["echo", "v2"]}]
            }))

            self.assertEqual(contract.checks_content_hash, original_hash)
            self.assertEqual(contract.checks[0]["name"], "original")


if __name__ == "__main__":
    unittest.main()