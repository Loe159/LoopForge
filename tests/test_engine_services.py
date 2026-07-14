from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loopforge.adapters import local_implementation_adapter
from loopforge.contracts import policy_path
from loopforge.checks import diff_policy
from loopforge.engine.metrics import MetricsService
from loopforge.engine.packs import PackRegistry
from loopforge.engine.storage import JsonStore


class JsonStoreTests(unittest.TestCase):
    def test_write_object_is_readable_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = JsonStore()

            store.write_object(path, {"name": "LoopForge", "version": 1})

            self.assertEqual(store.read_object(path), {"name": "LoopForge", "version": 1})
            self.assertEqual(list(path.parent.glob(".state.json.*.tmp")), [])

    def test_read_object_rejects_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                JsonStore().read_object(path)


class PackagedRuntimeLayoutTests(unittest.TestCase):
    def test_runtime_scripts_and_contracts_are_product_owned(self) -> None:
        package_root = Path(__file__).resolve().parents[1] / "src" / "loopforge"

        self.assertEqual(Path(diff_policy.__file__).resolve().parent, package_root / "checks")
        self.assertEqual(
            Path(local_implementation_adapter.__file__).resolve().parent,
            package_root / "adapters",
        )
        self.assertEqual(
            local_implementation_adapter.POLICY_PATH,
            policy_path("local-implementation-adapter.json"),
        )
        self.assertTrue(policy_path("diff-policy.json").is_file())


class PackRegistryTests(unittest.TestCase):
    def test_project_local_contract_overrides_bundled_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            bundled_root = root / "bundled"
            project_pack = project_dir / ".loopforge" / "packs" / "python"
            bundled_pack = bundled_root / ".loopforge" / "packs" / "python"
            project_pack.mkdir(parents=True)
            bundled_pack.mkdir(parents=True)
            (project_pack / "pack.json").write_text(
                json.dumps(
                    {
                        "name": "python",
                        "version": 1,
                        "description": "local",
                        "priority": 10,
                        "detection": {"files_any": ["local.marker"]},
                        "skills": ["local-skill"],
                    }
                ),
                encoding="utf-8",
            )
            (bundled_pack / "pack.json").write_text(
                json.dumps(
                    {
                        "name": "python",
                        "version": 1,
                        "description": "bundled",
                        "priority": 1,
                        "detection": {},
                        "skills": ["bundled-skill"],
                    }
                ),
                encoding="utf-8",
            )
            (project_dir / "local.marker").write_text("", encoding="utf-8")
            registry = PackRegistry(
                project_dir,
                bundled_root=bundled_root,
                store=JsonStore(),
            )

            self.assertEqual(registry.load_contract("python")["description"], "local")
            self.assertEqual(registry.detect()["name"], "python")
            self.assertEqual(registry.detect()["detection_score"], 30)
            self.assertEqual(registry.skill_entries(registry.detect()), ["local-skill"])

    def test_load_checks_and_protected_paths_normalizes_contract_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            pack_dir = project_dir / ".loopforge" / "packs" / "demo"
            pack_dir.mkdir(parents=True)
            (pack_dir / "checks.json").write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "name": "unit",
                                "command": ["python", "-m", "unittest"],
                                "env": {"MODE": "test"},
                                "timeout_seconds": 10,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "protected-paths.json").write_text(
                json.dumps(
                    {
                        "high_path_patterns": ["infra/**"],
                        "medium_path_patterns": ["docs/**"],
                    }
                ),
                encoding="utf-8",
            )
            registry = PackRegistry(
                project_dir,
                bundled_root=root / "bundled",
                store=JsonStore(),
            )

            self.assertEqual(registry.load_checks("demo")["checks"][0]["name"], "unit")
            self.assertEqual(
                registry.load_protected_paths("demo")["high_path_patterns"],
                ["infra/**"],
            )


class MetricsServiceTests(unittest.TestCase):
    def test_summary_keeps_unknown_values_out_of_averages(self) -> None:
        service = MetricsService(JsonStore())
        summary = service.build_summary(
            [
                {
                    "run_id": "one",
                    "timing": {"duration_seconds": 10},
                    "attempts": {"count": 1},
                    "patch": {"size_bytes": 20},
                    "verification": {"status": "passed"},
                    "final_disposition": {"status": "verified"},
                },
                {
                    "run_id": "two",
                    "timing": {"duration_seconds": None},
                    "attempts": {"count": 2},
                    "patch": {"size_bytes": None},
                    "verification": {"status": None},
                    "final_disposition": {"status": "pending"},
                },
            ]
        )

        self.assertEqual(summary["duration_seconds"]["average"], 10)
        self.assertEqual(summary["duration_seconds"]["unknown_count"], 1)
        self.assertEqual(summary["patch_size_bytes"]["sum"], 20)
        self.assertEqual(summary["verification_results"], {"passed": 1, "unknown": 1})


if __name__ == "__main__":
    unittest.main()
