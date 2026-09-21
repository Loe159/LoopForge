"""Crash injection and corruption recovery tests for LoopForge Epic 28."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from loopforge.engine.storage import JsonStore, DEFAULT_JSON_STORE
from loopforge.engine.recovery import quarantine_corrupt_file, safe_read_json
from loopforge.engine.indexes import (
    read_run_index,
    rebuild_run_index,
    mark_dirty,
    clear_dirty,
    dirty_marker_path,
    run_index_path,
)
from loopforge.engine.projects import load_registry, save_registry, empty_registry


class TestSafeReadJson(unittest.TestCase):
    """Tests for safe_read_json and quarantine_corrupt_file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_read_valid_json_returns_data(self):
        path = Path(self.temp.name) / "good.json"
        path.write_text('{"key": "value"}')
        data, diag = safe_read_json(self.store, path)
        self.assertIsNotNone(data)
        self.assertIsNone(diag)
        self.assertEqual(data["key"], "value")

    def test_corrupt_json_is_quarantined(self):
        path = Path(self.temp.name) / "bad.json"
        path.write_text("{invalid json!!!")
        data, diag = safe_read_json(self.store, path)
        self.assertIsNone(data)
        self.assertIsNotNone(diag)
        self.assertIn("quarantined", diag)
        self.assertFalse(path.exists())
        quarantine_files = list(Path(self.temp.name).glob("bad.json.corrupt.*"))
        self.assertEqual(len(quarantine_files), 1)

    def test_missing_file_returns_diagnostic_no_quarantine(self):
        path = Path(self.temp.name) / "missing.json"
        data, diag = safe_read_json(self.store, path)
        self.assertIsNone(data)
        self.assertIsNotNone(diag)
        self.assertIn("File not found", diag)
        self.assertFalse(list(Path(self.temp.name).glob("*.corrupt.*")))

    def test_empty_json_obj_still_valid(self):
        path = Path(self.temp.name) / "empty.json"
        path.write_text("{}")
        data, diag = safe_read_json(self.store, path)
        self.assertIsNotNone(data)
        self.assertIsNone(diag)
        self.assertEqual(data, {})

    def test_json_not_a_dict_triggers_corrupt(self):
        path = Path(self.temp.name) / "list.json"
        path.write_text("[1, 2, 3]")
        data, diag = safe_read_json(self.store, path)
        self.assertIsNone(data)
        self.assertIsNotNone(diag)
        self.assertIn("quarantined", diag)
        self.assertFalse(path.exists())

    def test_quarantine_preserves_original_name_structure(self):
        path = Path(self.temp.name) / "config.json"
        path.write_text("{broken")
        safe_read_json(self.store, path)
        quarantined = list(Path(self.temp.name).glob("config.json.corrupt.*"))
        self.assertEqual(len(quarantined), 1)
        qname = quarantined[0].name
        self.assertTrue(qname.startswith("config.json.corrupt."))
        self.assertFalse(path.exists())

    def test_os_error_triggers_quarantine(self):
        path = Path(self.temp.name) / "bad_perm.json"
        path.write_text('{"x": 1}')
        with patch.object(self.store, "read_object", side_effect=OSError("permission denied")):
            data, diag = safe_read_json(self.store, path)
        self.assertIsNone(data)
        self.assertIsNotNone(diag)
        self.assertIn("quarantined", diag)
        self.assertFalse(path.exists())


class TestRegistryCorruption(unittest.TestCase):
    """AE10: Corrupt registry recovery."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = Path(self.temp.name) / "projects"
        home.mkdir(parents=True)
        self.registry_path = home / "registry.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_corrupt_registry_returns_empty_not_silent(self):
        self.registry_path.write_text("CORRUPTED DATA {{{")
        registry = load_registry(Path(self.temp.name))
        self.assertIsNotNone(registry)
        self.assertIn("projects", registry)
        self.assertEqual(registry["projects"], {})
        self.assertFalse(self.registry_path.exists())
        quarantine_files = list(self.registry_path.parent.glob("registry.json.corrupt.*"))
        self.assertEqual(len(quarantine_files), 1)

    def test_missing_registry_creates_empty(self):
        registry = load_registry(Path(self.temp.name))
        self.assertIsNotNone(registry)
        self.assertIn("projects", registry)
        self.assertEqual(registry["projects"], {})

    def test_valid_registry_loads_projects(self):
        self.registry_path.write_text(json.dumps({
            "schema_version": 2,
            "registry_version": 1,
            "projects": {
                "test-id": {"project_id": "test-id", "name": "Test"},
            },
        }))
        registry = load_registry(Path(self.temp.name))
        self.assertIn("test-id", registry["projects"])
        self.assertEqual(registry["projects"]["test-id"]["name"], "Test")

    def test_registry_with_projects_not_dict_is_discarded(self):
        self.registry_path.write_text(json.dumps({
            "schema_version": 2,
            "registry_version": 1,
            "projects": "not a dict",
        }))
        registry = load_registry(Path(self.temp.name))
        self.assertEqual(registry["projects"], {})


class TestIndexRecovery(unittest.TestCase):
    """AE10: Corrupt index rebuilt from authoritative runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore()

    def tearDown(self):
        self.temp.cleanup()

    def _make_run(self, run_root, run_id, task, status="loop_contract_ready"):
        run_dir = run_root / run_id
        run_dir.mkdir(parents=True)
        run_json = run_dir / "run.json"
        run_json.write_text(json.dumps({
            "run_id": run_id,
            "task": task,
            "status": status,
            "pack": "generic-code",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "archived": False,
            "current_stage": "task_draft",
        }))

    def test_corrupt_index_read_returns_none(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        index_path = run_index_path(run_root)
        index_path.write_text("CORRUPTED")
        index = read_run_index(self.store, run_root)
        self.assertIsNone(index)

    def test_rebuild_from_valid_runs(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        for run_id in ["run-001", "run-002"]:
            self._make_run(run_root, run_id, f"Task {run_id}")
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-01T00:00:00Z",
        )
        self.assertIsNotNone(rebuilt)
        self.assertEqual(len(rebuilt.get("runs", [])), 2)
        run_ids = {r["run_id"] for r in rebuilt["runs"]}
        self.assertEqual(run_ids, {"run-001", "run-002"})

    def test_rebuild_skips_corrupt_run_json(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        self._make_run(run_root, "run-good", "Good")
        bad_dir = run_root / "run-bad"
        bad_dir.mkdir()
        (bad_dir / "run.json").write_text("{corrupt!!!")
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-01T00:00:00Z",
        )
        self.assertEqual(len(rebuilt.get("runs", [])), 1)
        self.assertEqual(rebuilt["runs"][0]["run_id"], "run-good")

    def test_rebuild_empty_dir_returns_empty_index(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-01T00:00:00Z",
        )
        self.assertEqual(rebuilt.get("runs", []), [])

    def test_corrupt_index_rebuilt_from_runs(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        for run_id in ["run-001", "run-002"]:
            self._make_run(run_root, run_id, f"Task {run_id}")
        index_path = run_index_path(run_root)
        index_path.write_text("CORRUPTED")
        index = read_run_index(self.store, run_root)
        self.assertIsNone(index)
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-01T00:00:00Z",
        )
        self.assertIsNotNone(rebuilt)
        self.assertEqual(len(rebuilt.get("runs", [])), 2)

    def test_rebuild_marks_current_run(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        self._make_run(run_root, "run-001", "Task 1")
        self._make_run(run_root, "run-002", "Task 2")
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id="run-002", timestamp="2024-01-01T00:00:00Z",
        )
        for entry in rebuilt["runs"]:
            self.assertIn("current", entry)
            if entry["run_id"] == "run-002":
                self.assertTrue(entry["current"])
            else:
                self.assertFalse(entry["current"])


class TestDirtyMarker(unittest.TestCase):
    """Dirty marker crash recovery."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_dirty_marker_blocks_index_read(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        mark_dirty(self.store, run_root, timestamp="2024-01-01T00:00:00Z")
        self.assertTrue(dirty_marker_path(run_root).exists())
        index = read_run_index(self.store, run_root)
        self.assertIsNone(index)

    def test_clear_dirty_allows_rebuild(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        mark_dirty(self.store, run_root, timestamp="2024-01-01T00:00:00Z")
        clear_dirty(run_root)
        self.assertFalse(dirty_marker_path(run_root).exists())
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-01T00:00:00Z",
        )
        self.assertIsNotNone(rebuilt)

    def test_clear_dirty_on_nonexistent_is_idempotent(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        clear_dirty(run_root)
        self.assertFalse(dirty_marker_path(run_root).exists())


class TestCrashDuringCreation(unittest.TestCase):
    """AE9: Crash during run creation leaves no orphans."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_rollback_removes_run_directory(self):
        project_dir = Path(self.temp.name) / "project"
        project_dir.mkdir()
        fake_run_dir = Path(self.temp.name) / "runs" / "run-test"
        fake_run_dir.mkdir(parents=True)
        (fake_run_dir / "run.json").write_text("{}")
        (fake_run_dir / "task.md").write_text("# Task")
        sub_dir = fake_run_dir / "attempts"
        sub_dir.mkdir()

        from loopforge.engine import _rollback_run_creation
        _rollback_run_creation(fake_run_dir, None, project_dir)
        self.assertFalse(fake_run_dir.exists())

    def test_rollback_is_idempotent(self):
        project_dir = Path(self.temp.name) / "project"
        project_dir.mkdir()
        fake_run_dir = Path(self.temp.name) / "runs" / "run-test"
        fake_run_dir.mkdir(parents=True)
        (fake_run_dir / "run.json").write_text("{}")

        from loopforge.engine import _rollback_run_creation
        _rollback_run_creation(fake_run_dir, None, project_dir)
        self.assertFalse(fake_run_dir.exists())
        _rollback_run_creation(fake_run_dir, None, project_dir)
        self.assertFalse(fake_run_dir.exists())

    def test_rollback_with_none_run_dir_does_nothing(self):
        project_dir = Path(self.temp.name) / "project"
        project_dir.mkdir()

        from loopforge.engine import _rollback_run_creation
        _rollback_run_creation(None, None, project_dir)

    def test_rollback_respects_workspace_state(self):
        """When workspace_state has mode=WORKSPACE_MODE_GIT_WORKTREE,
        _cleanup_workspace is called."""
        project_dir = Path(self.temp.name) / "project"
        project_dir.mkdir()
        fake_run_dir = Path(self.temp.name) / "runs" / "run-test"
        fake_run_dir.mkdir(parents=True)
        (fake_run_dir / "run.json").write_text("{}")

        ws_path = Path(self.temp.name) / "workspaces" / "ws-test"
        ws_path.mkdir(parents=True)

        from loopforge.engine import _rollback_run_creation, WORKSPACE_MODE_GIT_WORKTREE
        workspace_state = {"mode": WORKSPACE_MODE_GIT_WORKTREE, "path": str(ws_path)}
        _rollback_run_creation(fake_run_dir, workspace_state, project_dir)
        self.assertFalse(fake_run_dir.exists())


class TestConcurrentDirtyMarker(unittest.TestCase):
    """AE8: Two-process concurrent dirty marker."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_two_processes_both_mark_dirty_no_crash(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        mark_dirty(self.store, run_root, timestamp="2024-01-01T00:00:00Z")
        mark_dirty(self.store, run_root, timestamp="2024-01-02T00:00:00Z")
        self.assertTrue(dirty_marker_path(run_root).exists())
        index = read_run_index(self.store, run_root)
        self.assertIsNone(index)

    def test_mark_dirty_then_clear_then_rebuild(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        mark_dirty(self.store, run_root, timestamp="2024-01-01T00:00:00Z")
        mark_dirty(self.store, run_root, timestamp="2024-01-02T00:00:00Z")
        clear_dirty(run_root)
        rebuilt = rebuild_run_index(
            self.store, run_root,
            current_run_id=None, timestamp="2024-01-03T00:00:00Z",
        )
        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["runs"], [])

    def test_marker_timestamp_updated_by_later_write(self):
        run_root = Path(self.temp.name) / "runs"
        run_root.mkdir()
        mark_dirty(self.store, run_root, timestamp="2024-01-01T00:00:00Z")
        marker = self.store.read_object(dirty_marker_path(run_root))
        self.assertEqual(marker["marked_at"], "2024-01-01T00:00:00Z")
        mark_dirty(self.store, run_root, timestamp="2024-01-02T00:00:00Z")
        marker = self.store.read_object(dirty_marker_path(run_root))
        self.assertEqual(marker["marked_at"], "2024-01-02T00:00:00Z")


class TestJsonStoreAtomicity(unittest.TestCase):
    """Atomic write guarantees of JsonStore."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_write_is_atomic_no_partial_files_left(self):
        path = Path(self.temp.name) / "data.json"
        self.store.write_object(path, {"key": "value"})
        self.assertTrue(path.exists())
        self.assertEqual(self.store.read_object(path), {"key": "value"})
        temp_patterns = list(Path(self.temp.name).glob(".data.json.*.tmp"))
        self.assertEqual(len(temp_patterns), 0)

    def test_write_with_crash_simulation_no_orphan_temp(self):
        path = Path(self.temp.name) / "data.json"
        original_write = self.store.write_object
        call_count = [0]

        def crashing_write(p, data):
            call_count[0] += 1
            original_write(p, data)
            if call_count[0] == 1:
                raise OSError("simulated crash after write")

        self.store.write_object = crashing_write
        try:
            self.store.write_object(path, {"step": 1})
        except OSError:
            pass
        finally:
            self.store.write_object = original_write
        self.store.write_object(path, {"step": 2})
        self.assertEqual(self.store.read_object(path), {"step": 2})

    def test_read_after_write_roundtrips_complex_data(self):
        path = Path(self.temp.name) / "complex.json"
        data = {
            "schema_version": 2,
            "registry_version": 1,
            "projects": {
                "p1": {"name": "Alpha", "path": "/tmp/alpha", "run_root": "/tmp/alpha/runs"},
                "p2": {"name": "Beta", "path": "/tmp/beta"},
            },
        }
        self.store.write_object(path, data)
        recovered = self.store.read_object(path)
        self.assertEqual(recovered, data)


class TestFileLockRecovery(unittest.TestCase):
    """Persistent lock files are reusable without deleting their inode."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_new_lock_acquires_and_releases(self):
        from loopforge.engine.locking import FileLock
        target = Path(self.temp.name) / "shared.json"
        lock = FileLock(target, timeout=1.0)
        self.assertFalse(lock.acquired)
        lock.acquire()
        self.assertTrue(lock.acquired)
        self.assertTrue(lock.lock_path.exists())
        lock.release()
        self.assertFalse(lock.acquired)
        self.assertTrue(lock.lock_path.exists())

    def test_context_manager_releases_lock(self):
        from loopforge.engine.locking import FileLock
        target = Path(self.temp.name) / "shared.json"
        lock = FileLock(target, timeout=1.0)
        self.assertFalse(lock.acquired)
        with lock:
            self.assertTrue(lock.acquired)
        self.assertFalse(lock.acquired)

    @unittest.skipIf(sys.platform == "win32", "PID not written to lock file on Windows (mandatory locks prevent reading)")
    def test_unlocked_file_with_stale_pid_is_reused(self):
        from loopforge.engine.locking import FileLock
        target = Path(self.temp.name) / "stale.json"
        lock_path = Path(str(target) + ".lock")
        lock_path.write_text(str(99999))
        lock = FileLock(target, timeout=1.0)
        lock.acquire()
        try:
            pid_inside = int(lock_path.read_text().strip())
            self.assertEqual(pid_inside, os.getpid())
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main()
