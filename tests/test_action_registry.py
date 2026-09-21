"""Tests for action registry consistency.

Covers Subtask 3 of Epic 3: every action descriptor the CLI surfaces is
backed by a real executor, and every executor key traces back to an
action the engine can actually produce.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from loopforge.cli.actions import (
    ACTION_EXECUTORS,
    ActionDescriptor,
    action_descriptors,
    action_descriptor,
    primary_action,
)
from loopforge.engine import GuidedAction, GuidanceResult

# Action ids the engine is known to emit via guidance_from_status /
# workflow_stage_guidance. ACTION_EXECUTORS keys must be a subset of these.
KNOWN_ENGINE_ACTION_IDS = frozenset(
    {
        "init",
        "create-run",
        "complete-task",
        "approve-task",
        "run-research",
        "run-plan",
        "approve-plan",
        "continue",
        "retry-attempt",
        "verify",
        "run-review",
        "approve-review",
        "prepare-draft",
        "status",
        "choose-adapter",
        "inspect-verification",
        "inspect-attempt",
        "approve-memory",
        "show-plan",
        "check-contract",
        "review-contract",
        "review-autonomy-stop",
    }
)


def _guided_action(action_id: str) -> GuidedAction:
    return GuidedAction(
        id=action_id,
        label=action_id.replace("-", " ").title(),
        command=f"loopforge {action_id}",
        risk="low",
        requires_confirmation=False,
        why="test",
    )


def _guidance(actions: list[GuidedAction]) -> GuidanceResult:
    return GuidanceResult(
        project_dir=Path("/tmp"),
        state="test",
        summary="test",
        priority="low",
        diagnostics=[],
        recommended_actions=actions,
        blocked_reasons=[],
        evidence=[],
    )


class ActionExecutorRegistryTests(unittest.TestCase):

    def test_every_executor_key_is_non_empty_string(self) -> None:
        executor_keys = set(ACTION_EXECUTORS.values())
        self.assertTrue(executor_keys, "ACTION_EXECUTORS must not be empty")
        for key in executor_keys:
            self.assertIsInstance(key, str)
            self.assertTrue(key.strip(), "empty executor key found")

    def test_every_action_id_has_an_executor(self) -> None:
        for action_id in ACTION_EXECUTORS:
            self.assertIn(
                action_id,
                ACTION_EXECUTORS,
                f"action {action_id!r} missing from registry",
            )
            self.assertTrue(
                ACTION_EXECUTORS[action_id].strip(),
                f"action {action_id!r} maps to an empty executor",
            )

    def test_no_phantom_actions(self) -> None:
        """Every action id in ACTION_EXECUTORS must be producible by the engine."""
        registry_ids = set(ACTION_EXECUTORS.keys())
        unknown = registry_ids - KNOWN_ENGINE_ACTION_IDS
        self.assertFalse(
            unknown,
            f"phantom actions in registry (no engine producer): {sorted(unknown)}",
        )

    def test_known_engine_ids_cover_all_registry_keys(self) -> None:
        registry_ids = set(ACTION_EXECUTORS.keys())
        self.assertEqual(
            registry_ids,
            registry_ids & KNOWN_ENGINE_ACTION_IDS,
        )


class ActionDescriptorTests(unittest.TestCase):

    def test_action_descriptor_for_known_id_has_executor_key(self) -> None:
        for action_id in ACTION_EXECUTORS:
            with self.subTest(action_id=action_id):
                descriptor = action_descriptor(_guided_action(action_id))

                self.assertIsInstance(descriptor, ActionDescriptor)
                self.assertEqual(descriptor.id, action_id)
                self.assertTrue(descriptor.available)
                self.assertEqual(
                    descriptor.executor_key, ACTION_EXECUTORS[action_id]
                )

    def test_action_descriptor_falls_back_to_command_executor(self) -> None:
        descriptor = action_descriptor(_guided_action("unknown-action"))

        self.assertEqual(descriptor.executor_key, "command")
        self.assertFalse(descriptor.available)
        self.assertEqual(descriptor.command_fallback, "loopforge unknown-action")

    def test_action_descriptors_preserve_order_and_availability(self) -> None:
        actions = [
            _guided_action("init"),
            _guided_action("verify"),
            _guided_action("approve-plan"),
        ]
        guidance = _guidance(actions)

        descriptors = action_descriptors(guidance)

        self.assertEqual(len(descriptors), 3)
        self.assertEqual(
            [d.id for d in descriptors], ["init", "verify", "approve-plan"]
        )
        for descriptor in descriptors:
            self.assertTrue(descriptor.available, f"{descriptor.id} not available")
            self.assertTrue(descriptor.executor_key)

    def test_action_descriptors_passes_confirmation_through(self) -> None:
        action = GuidedAction(
            id="approve-plan",
            label="Approve Plan",
            command="loopforge run",
            risk="high",
            requires_confirmation=True,
            why="plan approval",
        )
        guidance = _guidance([action])

        descriptor = action_descriptors(guidance)[0]

        self.assertTrue(descriptor.requires_confirmation)
        self.assertEqual(descriptor.risk, "high")
        self.assertEqual(descriptor.description, "plan approval")
        self.assertEqual(descriptor.label, "Approve Plan")

    def test_primary_action_returns_first_or_none(self) -> None:
        self.assertIsNone(primary_action(_guidance([])))

        actions = [_guided_action("init"), _guided_action("verify")]
        primary = primary_action(_guidance(actions))
        self.assertIsNotNone(primary)
        self.assertEqual(primary.id, "init")


class ActionContractCoverageTests(unittest.TestCase):
    """Every engine action id must resolve to a real executor (no orphan)."""

    def test_all_known_engine_actions_resolve(self) -> None:
        descriptors = action_descriptors(
            _guidance([_guided_action(action_id) for action_id in sorted(KNOWN_ENGINE_ACTION_IDS)])
        )

        self.assertEqual(len(descriptors), len(KNOWN_ENGINE_ACTION_IDS))
        for descriptor in descriptors:
            self.assertTrue(
                descriptor.executor_key,
                f"engine action {descriptor.id!r} has no executor key",
            )


if __name__ == "__main__":
    unittest.main()
