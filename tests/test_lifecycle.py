"""Workflow-state normalization tests.

These cover ``normalize_run_workflow_state`` from ``engine.workflow``. The
former ``LifecycleStateMachine`` and its exhaustive transition tests have been
removed as dead code (the SM was never used in the business path).
"""

import unittest

from loopforge.engine import normalize_run_workflow_state
from loopforge.engine.lifecycle import RunStage


class TestNormalizeWorkflowState(unittest.TestCase):
    def test_review_complete_survives_normalization(self):
        run = {"current_stage": "review_complete", "stage_statuses": {"review": "complete"}}
        normalized = normalize_run_workflow_state(run)
        self.assertEqual(normalized["current_stage"], RunStage.REVIEW_COMPLETE.value)
        self.assertEqual(normalized["stage_statuses"]["review"], "complete")

    def test_normalize_rejects_unknown_stage(self):
        """Unknown current_stage should be reset to task_draft."""
        run = {"current_stage": "invalid_stage_fake"}
        normalized = normalize_run_workflow_state(run)
        self.assertEqual(normalized.get("current_stage"), RunStage.TASK_DRAFT.value)

    def test_normalize_preserves_valid_stage(self):
        """Valid current_stage should be preserved by normalization."""
        run = {
            "current_stage": RunStage.PLAN_APPROVED.value,
            "stage_statuses": {
                "task": "approved",
                "research": "completed",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        }
        normalized = normalize_run_workflow_state(run)
        self.assertEqual(normalized.get("current_stage"), RunStage.PLAN_APPROVED.value)


if __name__ == "__main__":
    unittest.main()
