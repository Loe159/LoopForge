"""Regression tests for the run context cockpit and its trust boundaries."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from loopforge.adapters.event_store import EventRecorder, EventStore, read_events
from loopforge.cli.run_projection import project_events
from loopforge.cli.run_reading import RunReading, load_reading, save_reading
from loopforge.cli.run_context import load_run_context
from loopforge.cli.run_changes import load_run_changes
from loopforge.cli.run_evidences import load_run_evidences
from loopforge.engine.context_capture import capture_prompt_context
from loopforge.engine.workspace_capture import capture_workspace_state, execution_changes


class ProjectionTests(unittest.TestCase):
    def test_tool_start_finish_merged_with_identity_and_read_group(self):
        events = (
            {"kind": "tool", "title": "Read", "call_id": "r1", "category": "read", "body": "a.py", "status": "running", "order": 0},
            {"kind": "tool", "title": "Read", "call_id": "r1", "category": "read", "body": "content a", "status": "completed", "order": 1},
            {"kind": "tool", "title": "Read", "call_id": "r2", "category": "read", "body": "content b", "status": "completed", "order": 2},
            {"kind": "message", "title": "Agent", "body": "Need to fix tests", "order": 3},
            {"kind": "tool", "title": "Bash", "call_id": "bad", "status": "failed", "body": "exit 4", "order": 4},
        )
        all_items = project_events(events, mode="All", session_closed=True)
        self.assertEqual(len(all_items), 4)
        self.assertEqual(all_items[0].status, "completed")
        focused = project_events(events, mode="Focused", session_closed=True)
        self.assertEqual(len(focused), 3)
        self.assertEqual(focused[0].kind, "group")
        self.assertIn("Read 2 files", focused[0].title)
        self.assertEqual(focused[-1].status, "failed")

    def test_pending_becomes_unknown_not_completed_and_plain_info_never_classified(self):
        result = project_events((
            {"kind": "tool", "title": "Shell", "call_id": "p", "status": "running", "body": "Read a.py", "order": 0},
            {"kind": "info", "title": "Agent output", "body": "Read b.py", "order": 1},
        ), session_closed=True)
        self.assertEqual(result[0].status, "unknown")
        self.assertEqual(result[1].kind, "info")

    def test_native_protocol_fixture_is_safe_and_parseable(self):
        path = Path(__file__).parent / "fixtures/run_observation/native_events.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        from loopforge.adapters.event_store import normalize_event
        for adapter in ("codex", "claude", "kilo", "opencode", "hooks"):
            produced = tuple(event for source in fixture[adapter] for event in normalize_event(source))
            self.assertTrue(produced, adapter)
            self.assertTrue(all(e.get("source") == "harness" for e in produced))

    def test_paged_event_stream_is_local_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = EventRecorder(root, structured=True)
            recorder.feed(b'{"type":"item.started","item":{"id":"a","type":"command_execution","status":"in_progress"}}\n')
            recorder.feed(b'{"type":"item.completed","item":{"id":"a","type":"command_execution","status":"completed"}}\n')
            recorder.close()
            items = read_events(root)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["order"], 0)
            self.assertEqual(items[1]["order"], 1)
            self.assertEqual(len(read_events(root, before=1)), 1)


class ArtifactTests(unittest.TestCase):
    def test_reading_roundtrip_does_not_change_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = RunReading(view="Context", stage_id="research", session_id="a", mode="All",
                                  following=False, scroll_y=24.0)
            save_reading(root, expected)
            self.assertEqual(load_reading(root), expected)

    def test_legacy_reading_defaults_to_follow_and_rejects_nonfinite_scroll(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ui-reading.json").write_text(
                json.dumps({"schema_version": 1, "view": "Live", "scroll_y": "NaN"}),
                encoding="utf-8",
            )
            restored = load_reading(root)
            self.assertTrue(restored.following)
            self.assertEqual(restored.scroll_y, 0.0)
            (root / "ui-reading.json").write_text(
                json.dumps({"schema_version": 1, "following": False, "scroll_y": "Infinity"}),
                encoding="utf-8",
            )
            restored = load_reading(root)
            self.assertFalse(restored.following)
            self.assertEqual(restored.scroll_y, 0.0)

    def test_context_capture_verified_and_tamper_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            execution = run_dir / "attempts/attempt-001"
            execution.mkdir(parents=True)
            capture_prompt_context(run_dir=run_dir, execution_dir=execution,
                run={"run_id": "r1"}, stage_id="implementation", session_id="one",
                attempt_id="one", harness="codex", prompt="## Objective\nFix tests\n",
                execution_mode="api", timeout_seconds=30)
            ctx = load_run_context(run_dir, "attempts/attempt-001")
            self.assertEqual(ctx.capture_state, "complete")
            self.assertTrue(ctx.hash_valid)
            self.assertIn("Fix tests", ctx.raw_prompt)
            (execution / "context-raw-prompt.md").write_text("tampered", encoding="utf-8")
            invalid = load_run_context(run_dir, "attempts/attempt-001")
            self.assertFalse(invalid.hash_valid)
            self.assertEqual(invalid.capture_state, "invalid")

    def test_capture_changes_distinguishes_dirty_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "a.txt").write_text("base\n")
            subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t",
                            "commit", "-qm", "base"], cwd=repo, check=True)
            (repo / "a.txt").write_text("already dirty\n")
            before = capture_workspace_state(repo)
            (repo / "a.txt").write_text("second change\n")
            (repo / "new.txt").write_text("new\n")
            after = capture_workspace_state(repo)
            changes = execution_changes(before, after)
            self.assertEqual(changes["capture_state"], "complete")
            self.assertEqual({c["path"] for c in changes["files"]}, {"a.txt", "new.txt"})
            self.assertIn("-already dirty", next(c["diff"] for c in changes["files"]
                                                   if c["path"] == "a.txt"))
            self.assertNotIn("-base", next(c["diff"] for c in changes["files"]
                                           if c["path"] == "a.txt"))

    def test_evidence_verification_stale_not_agent_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "attempts/attempt-001/result.json"
            result.parent.mkdir(parents=True)
            result.write_text('{"status":"completed"}', encoding="utf-8")
            run = {"run_id": "r1", "current_stage": "review", "candidate_revision": 2,
                   "attempts": [{"number": 1, "result_path": "attempts/attempt-001/result.json",
                                 "result_origin": "agent"}],
                   "verification": {"status": "passed", "candidate_revision": 1,
                                    "checks": [{"name": "unit tests", "status": "passed"}]},
                   "human_gates": {"review_approval": {"status": "approved",
                                    "candidate_revision": 1, "source": "operator"}}}
            status = SimpleNamespace(run_dir=root, run=run)
            session = SimpleNamespace(session_id="attempts/attempt-001", attempt_number=1,
                                      stage_id="implementation")
            snapshot = load_run_evidences(status, session)
            checks = next(item.body for item in snapshot.sections if item.key == "checks")
            decisions = next(item.body for item in snapshot.sections if item.key == "decisions")
            contracts = next(item.body for item in snapshot.sections if item.key == "contracts")
            self.assertIn("STALE", checks)
            self.assertIn("NOT attributed", checks)
            self.assertIn("STALE", decisions)
            self.assertIn("not deterministic verification", contracts)


if __name__ == "__main__":
    unittest.main()
