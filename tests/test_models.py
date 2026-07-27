"""Tests for typed, versioned data models at LoopForge boundaries.

Covers Subtask 1 of Epic 3: validation, round-trip serialization, and strict
rejection of unknown keys for every model in ``loopforge.engine.models``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from loopforge.engine.models import (
    ActionScope,
    AppCommandError,
    AppCommandResult,
    EffectivePackContract,
    LifecycleTransition,
    ProjectConfig,
    RunState,
    StageArtifact,
    VerificationResult,
)
from loopforge.engine.models.schema import CURRENT_CONFIG_SCHEMA, CURRENT_RUN_SCHEMA


class ActionScopeTests(unittest.TestCase):

    def test_to_dict_round_trip(self) -> None:
        scope = ActionScope(
            project_id="proj-123",
            project_path=Path("/tmp/project"),
            run_id="run-abc",
            revision=2,
            snapshot="ok",
        )
        data = scope.to_dict()
        restored = ActionScope.from_dict(data)
        self.assertEqual(restored.project_id, scope.project_id)
        self.assertEqual(restored.run_id, scope.run_id)
        self.assertEqual(restored.revision, scope.revision)
        self.assertEqual(restored.snapshot, scope.snapshot)
        self.assertEqual(Path(data["project_path"]), scope.project_path)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ActionScope.from_dict({
                "project_id": "p1",
                "project_path": "/tmp/p",
                "bogus": True,
            })
        self.assertIn("bogus", str(ctx.exception))

    def test_from_dict_minimal(self) -> None:
        scope = ActionScope.from_dict({
            "project_id": "p1",
            "project_path": "/tmp/p",
        })
        self.assertEqual(scope.project_id, "p1")
        self.assertIsNone(scope.run_id)
        self.assertIsNone(scope.revision)
        self.assertIsNone(scope.snapshot)


class EffectivePackContractTests(unittest.TestCase):

    def _sample(self) -> dict:
        return {
            "name": "generic-code",
            "version": 1,
            "description": "test pack",
            "checks": [],
            "checks_content_hash": "abc",
            "protected_paths": [],
            "protected_paths_content_hash": "",
            "memory_rules": "",
            "memory_rules_hash": "",
            "permissions": {},
            "agents": [],
            "workflow": [],
            "skills": [],
            "detection": "auto",
            "detection_score": 5,
            "contract_hash": "h1",
            "skills_content_hash": "",
            "frozen_at": "2026-01-01T00:00:00Z",
            "source": "bundled",
            "inherited_from": ["base"],
        }

    def test_to_dict_round_trip(self) -> None:
        contract = EffectivePackContract.from_dict(self._sample())
        data = contract.to_dict()
        restored = EffectivePackContract.from_dict(data)
        self.assertEqual(restored.name, contract.name)
        self.assertEqual(restored.version, contract.version)
        self.assertEqual(restored.permissions, contract.permissions)

    def test_to_dict_emits_permission_sets_alias(self) -> None:
        contract = EffectivePackContract.from_dict(self._sample())
        data = contract.to_dict()
        self.assertIn("permission_sets", data)
        self.assertEqual(data["permission_sets"], data["permissions"])

    def test_from_dict_rejects_unknown_keys(self) -> None:
        sample = self._sample()
        sample["totally_bogus"] = 42
        with self.assertRaises(ValueError) as ctx:
            EffectivePackContract.from_dict(sample)
        self.assertIn("totally_bogus", str(ctx.exception))

    def test_from_dict_tolerates_permission_sets_alias(self) -> None:
        """Persisted data contains the permission_sets alias; from_dict must not reject it."""
        sample = self._sample()
        sample["permission_sets"] = {}
        # Should NOT raise
        contract = EffectivePackContract.from_dict(sample)
        self.assertEqual(contract.permissions, {})


class ProjectConfigTests(unittest.TestCase):

    def _sample(self) -> dict:
        return {
            "schema_version": int(CURRENT_CONFIG_SCHEMA),
            "project_id": "proj-abc",
            "project_name": "my-project",
            "profile": "supervised",
            "run_root": "/home/loopforge/projects/proj-abc/runs",
            "current_run_id": None,
            "default_adapter": "codex",
            "default_adapter_args": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    def test_to_dict_round_trip(self) -> None:
        config = ProjectConfig.from_dict(self._sample())
        restored = ProjectConfig.from_dict(config.to_dict())
        self.assertEqual(restored, config)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        sample = self._sample()
        sample["unexpected_field"] = True
        with self.assertRaises(ValueError) as ctx:
            ProjectConfig.from_dict(sample)
        self.assertIn("unexpected_field", str(ctx.exception))


class RunStateTests(unittest.TestCase):

    def _sample(self) -> dict:
        return {
            "schema_version": int(CURRENT_RUN_SCHEMA),
            "run_id": "run-001",
            "task_id": "run-001",
            "task": "Fix the bug",
            "project_root": "/tmp/project",
            "status": "loop_contract_draft",
            "profile": "supervised",
            "pack": "generic-code",
            "created_at": "2026-01-01T00:00:00Z",
            "workspace": {"mode": "shared-checkout"},
            "pack_contract": {"name": "generic-code"},
            "current_stage": "task_draft",
            "stage_statuses": {"task": "draft"},
            "success_checks": ["tests pass"],
            "acceptance_criteria": ["tests pass"],
            "verification_commands": [],
            "limits": {"max_attempts": 3, "timeout_seconds": 1800},
            "attempt_count": 0,
            "attempts": [],
            "blockers": [],
            "artifacts": {},
            "memory": {"pending_proposals": 0},
        }

    def test_to_dict_round_trip(self) -> None:
        run = RunState.from_dict(self._sample())
        data = run.to_dict()
        restored = RunState.from_dict(data)
        self.assertEqual(restored.run_id, run.run_id)
        self.assertEqual(restored.task, run.task)
        self.assertEqual(restored.status, run.status)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        sample = self._sample()
        sample["nonexistent_key"] = 123
        with self.assertRaises(ValueError) as ctx:
            RunState.from_dict(sample)
        self.assertIn("nonexistent_key", str(ctx.exception))

    def test_from_dict_accepts_optional_fields(self) -> None:
        """Real run.json files have extra fields; these must be tolerated."""
        sample = self._sample()
        sample["base_commit"] = "abc123"
        sample["human_gates"] = {}
        sample["approval"] = {}
        sample["updated_at"] = "2026-01-02T00:00:00Z"
        sample["archived"] = False
        run = RunState.from_dict(sample)
        self.assertEqual(run.base_commit, "abc123")


class LifecycleTransitionTests(unittest.TestCase):

    def test_to_dict_round_trip(self) -> None:
        transition = LifecycleTransition(
            event="task_approve",
            from_stage="task_draft",
            to_stage="task_approved",
            ok=True,
            timestamp="2026-01-01T00:00:00Z",
            source="local",
            blockers=[],
        )
        restored = LifecycleTransition.from_dict(transition.to_dict())
        self.assertEqual(restored, transition)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LifecycleTransition.from_dict({
                "event": "task_approve",
                "from_stage": "task_draft",
                "to_stage": "task_approved",
                "ok": True,
                "timestamp": "2026-01-01T00:00:00Z",
                "source": "local",
                "blockers": [],
                "extra": True,
            })
        self.assertIn("extra", str(ctx.exception))


class VerificationResultTests(unittest.TestCase):

    def _sample(self) -> dict:
        return {
            "status": "passed",
            "checks_passed": 5,
            "checks_total": 5,
            "finished_at": "2026-01-01T00:10:00Z",
            "stagnated": False,
            "patch": {"path": "/tmp/patch.diff", "size_bytes": 1024},
            "details": {},
        }

    def test_to_dict_round_trip(self) -> None:
        result = VerificationResult.from_dict(self._sample())
        restored = VerificationResult.from_dict(result.to_dict())
        self.assertEqual(restored.status, result.status)
        self.assertEqual(restored.checks_passed, result.checks_passed)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        sample = self._sample()
        sample["bogus_field"] = "nope"
        with self.assertRaises(ValueError) as ctx:
            VerificationResult.from_dict(sample)
        self.assertIn("bogus_field", str(ctx.exception))


class AppCommandResultTests(unittest.TestCase):

    def test_to_dict_round_trip(self) -> None:
        error = AppCommandError(
            code="BLOCKED",
            message="Plan not approved",
            remediation="Approve the plan first",
            recoverable=True,
        )
        result = AppCommandResult(
            command="start_run",
            ok=False,
            target=None,
            new_revision=None,
            data={},
            errors=[error],
            next_actions=[],
            effects=[],
        )
        restored = AppCommandResult.from_dict(result.to_dict())
        self.assertEqual(restored.command, "start_run")
        self.assertFalse(restored.ok)
        self.assertEqual(len(restored.errors), 1)
        self.assertEqual(restored.errors[0].code, "BLOCKED")
        self.assertEqual(restored.errors[0].message, "Plan not approved")

    def test_from_dict_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AppCommandResult.from_dict({
                "command": "test",
                "ok": True,
                "target": None,
                "new_revision": None,
                "data": {},
                "errors": [],
                "next_actions": [],
                "effects": [],
                "mystery_key": 42,
            })
        self.assertIn("mystery_key", str(ctx.exception))


class AppCommandErrorTests(unittest.TestCase):

    def test_to_dict_round_trip(self) -> None:
        error = AppCommandError(
            code="NOT_FOUND",
            message="Run not found",
            remediation="Create a run first",
            recoverable=True,
        )
        restored = AppCommandError.from_dict(error.to_dict())
        self.assertEqual(restored, error)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AppCommandError.from_dict({
                "code": "ERR",
                "message": "msg",
                "remediation": "fix",
                "recoverable": False,
                "unexpected": True,
            })
        self.assertIn("unexpected", str(ctx.exception))


class StageArtifactTests(unittest.TestCase):

    def test_to_dict_round_trip(self) -> None:
        artifact = StageArtifact(
            name="research.md",
            frontmatter={"status": "complete"},
            body="# Research\n\nDone.",
            path="/tmp/run/research.md",
        )
        restored = StageArtifact.from_dict(artifact.to_dict())
        self.assertEqual(restored, artifact)

    def test_from_dict_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            StageArtifact.from_dict({
                "name": "plan.md",
                "frontmatter": {},
                "body": "",
                "path": None,
                "bogus": 123,
            })
        self.assertIn("bogus", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
