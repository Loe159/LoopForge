"""Migration system tests for LoopForge Epic 28."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from loopforge.engine.models.schema import SchemaVersion
from loopforge.engine.models.migrations import (
    migrate_run,
    migrate_config,
    migrate_registry,
    migrate_index,
    migrate_v1_run_to_v2,
    migrate_v1_config_to_v2,
    migrate_v1_registry_to_v2,
    migrate_v1_index_to_v2,
    MIGRATIONS,
    _detect_version,
    _backup_file,
    _chain_migrations,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "v0_1_0"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestDetectVersion(unittest.TestCase):
    def test_missing_schema_version_defaults_to_1(self):
        self.assertEqual(_detect_version({}), 1)

    def test_present_schema_version_returned(self):
        self.assertEqual(_detect_version({"schema_version": 5}), 5)
        self.assertEqual(_detect_version({"schema_version": 2}), 2)

    def test_custom_default(self):
        self.assertEqual(_detect_version({}, default=3), 3)


class TestMigrateFixtures(unittest.TestCase):
    def test_migrate_run_fixture(self):
        run = _load_fixture("run")
        self.assertNotIn("schema_version", run)

        migrated = migrate_run(run)
        self.assertEqual(migrated["schema_version"], SchemaVersion.V2)
        self.assertIn("run_id", migrated)
        self.assertIn("current_stage", migrated)
        self.assertIn("stage_statuses", migrated)
        self.assertIn("pack_contract", migrated)

    def test_migrate_config_fixture(self):
        config = _load_fixture("config")
        self.assertNotIn("schema_version", config)

        migrated = migrate_config(config)
        self.assertEqual(migrated["schema_version"], SchemaVersion.V2)
        self.assertIn("project_id", migrated)
        self.assertIn("profile", migrated)

    def test_migrate_registry_fixture(self):
        registry = _load_fixture("registry")
        self.assertNotIn("schema_version", registry)
        self.assertIn("registry_version", registry)

        migrated = migrate_registry(registry)
        self.assertEqual(migrated["schema_version"], SchemaVersion.V2)
        self.assertIn("registry_version", migrated)
        self.assertEqual(len(migrated["projects"]), 2)

    def test_migrate_index_fixture(self):
        index = _load_fixture("index")
        self.assertNotIn("schema_version", index)
        self.assertIn("index_version", index)

        migrated = migrate_index(index)
        self.assertEqual(migrated["schema_version"], SchemaVersion.V2)
        self.assertEqual(len(migrated["runs"]), 2)


class TestMigrationIdempotency(unittest.TestCase):
    def test_run_migration_idempotent(self):
        run = _load_fixture("run")
        m1 = migrate_run(run)
        m2 = migrate_run(m1)
        self.assertEqual(m1, m2)

    def test_config_migration_idempotent(self):
        config = _load_fixture("config")
        m1 = migrate_config(config)
        m2 = migrate_config(m1)
        self.assertEqual(m1, m2)

    def test_registry_migration_idempotent(self):
        registry = _load_fixture("registry")
        m1 = migrate_registry(registry)
        m2 = migrate_registry(m1)
        self.assertEqual(m1, m2)

    def test_index_migration_idempotent(self):
        index = _load_fixture("index")
        m1 = migrate_index(index)
        m2 = migrate_index(m1)
        self.assertEqual(m1, m2)


class TestMigrationWithBackup(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_migration_creates_backup(self):
        src = Path(self.temp.name) / "config.json"
        config = _load_fixture("config")
        src.write_text(json.dumps(config), encoding="utf-8")

        migrate_config(config, file_path=src)

        backup_files = list(Path(self.temp.name).glob("*.bak"))
        self.assertEqual(len(backup_files), 1)
        self.assertTrue(backup_files[0].name.startswith("config.json.v"))

    def test_migration_with_missing_file_no_backup_error(self):
        src = Path(self.temp.name) / "nonexistent.json"
        config = _load_fixture("config")
        migrated = migrate_config(config, file_path=src)
        self.assertIsNotNone(migrated)


class TestMigrationRoundtrip(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_config(self):
        from loopforge.engine.storage import DEFAULT_JSON_STORE
        path = Path(self.temp.name) / "config.json"

        config = _load_fixture("config")
        DEFAULT_JSON_STORE.write_object(path, config)

        raw = DEFAULT_JSON_STORE.read_object(path)
        self.assertNotIn("schema_version", raw)

        migrated = migrate_config(raw)
        self.assertEqual(migrated["schema_version"], SchemaVersion.V2)

        DEFAULT_JSON_STORE.write_object(path, migrated)

        final = DEFAULT_JSON_STORE.read_object(path)
        self.assertEqual(final["schema_version"], SchemaVersion.V2)


class TestChainMigrations(unittest.TestCase):
    def test_noop_when_already_current(self):
        data = {"schema_version": 2, "key": "value"}
        result = _chain_migrations(data, {}, target=2, context_name="test", file_path=None)
        self.assertEqual(data, result)

    def test_applies_migration_when_behind(self):
        data = {"old": True}
        v1_migrations: dict = {1: migrate_v1_config_to_v2}
        result = _chain_migrations(data, v1_migrations, target=2, context_name="test", file_path=None)
        self.assertEqual(result["schema_version"], 2)
        self.assertTrue(result.get("old"))


if __name__ == "__main__":
    unittest.main()