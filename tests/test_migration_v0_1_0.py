from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loopforge.engine.models.migrations import (
    migrate_run,
    migrate_config,
    migrate_registry,
    migrate_index,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "v0_1_0"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


class V010ConfigMigrationTests(unittest.TestCase):
    def test_migrate_config_adds_schema_version_2(self) -> None:
        config = _load_fixture("config.json")
        self.assertNotIn("schema_version", config)

        result = migrate_config(dict(config))

        self.assertEqual(result["schema_version"], 2)
        for key in config:
            self.assertIn(key, result)
            self.assertEqual(result[key], config[key])

    def test_migrate_config_is_idempotent(self) -> None:
        config = _load_fixture("config.json")
        first = migrate_config(dict(config))
        second = migrate_config(dict(first))

        self.assertEqual(first, second)


class V010RegistryMigrationTests(unittest.TestCase):
    def test_migrate_registry_adds_schema_version_2(self) -> None:
        registry = _load_fixture("registry.json")
        self.assertNotIn("schema_version", registry)

        result = migrate_registry(dict(registry))

        self.assertEqual(result["schema_version"], 2)
        for key in registry:
            self.assertIn(key, result)
            self.assertEqual(result[key], registry[key])

    def test_migrate_registry_is_idempotent(self) -> None:
        registry = _load_fixture("registry.json")
        first = migrate_registry(dict(registry))
        second = migrate_registry(dict(first))

        self.assertEqual(first, second)


class V010IndexMigrationTests(unittest.TestCase):
    def test_migrate_index_adds_schema_version_2(self) -> None:
        index = _load_fixture("index.json")
        self.assertNotIn("schema_version", index)

        result = migrate_index(dict(index))

        self.assertEqual(result["schema_version"], 2)
        for key in index:
            self.assertIn(key, result)
            self.assertEqual(result[key], index[key])

    def test_migrate_index_is_idempotent(self) -> None:
        index = _load_fixture("index.json")
        first = migrate_index(dict(index))
        second = migrate_index(dict(first))

        self.assertEqual(first, second)


class V010RunMigrationTests(unittest.TestCase):
    def test_migrate_run_adds_schema_version_2(self) -> None:
        run = _load_fixture("run.json")
        self.assertNotIn("schema_version", run)

        result = migrate_run(dict(run))

        self.assertEqual(result["schema_version"], 2)
        for key in run:
            self.assertIn(key, result)
            self.assertEqual(result[key], run[key])

    def test_migrate_run_preserves_nested_structures(self) -> None:
        run = _load_fixture("run.json")
        result = migrate_run(dict(run))

        self.assertEqual(result["workspace"]["mode"], "shared-checkout")
        self.assertEqual(result["profile_policy"]["name"], "supervised")
        self.assertEqual(result["pack_contract"]["name"], "generic-code")
        self.assertEqual(result["stage_statuses"]["task"], "draft")
        self.assertEqual(result["human_gates"]["initial_task_approval"]["status"], "pending")
        self.assertEqual(result["loop_contract"]["version"], 1)
        self.assertEqual(result["memory"]["pending_proposals"], 0)

    def test_migrate_run_is_idempotent(self) -> None:
        run = _load_fixture("run.json")
        first = migrate_run(dict(run))
        second = migrate_run(dict(first))

        self.assertEqual(first, second)


class V010MigrationWithTempDirTests(unittest.TestCase):
    def test_roundtrip_config_write_read_migrate(self) -> None:
        config = _load_fixture("config.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")

            from loopforge.engine import read_json
            reloaded = read_json(path)

            self.assertNotIn("schema_version", reloaded)
            migrated = migrate_config(dict(reloaded), file_path=path)
            self.assertEqual(migrated["schema_version"], 2)

    def test_roundtrip_run_write_read_migrate(self) -> None:
        run = _load_fixture("run.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "run.json"
            path.write_text(json.dumps(run), encoding="utf-8")

            from loopforge.engine import read_json
            reloaded = read_json(path)

            self.assertNotIn("schema_version", reloaded)
            migrated = migrate_run(dict(reloaded), file_path=path)
            self.assertEqual(migrated["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()