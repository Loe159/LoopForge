"""Exhaustive lifecycle state machine tests for LoopForge Epic 28."""

import copy
import unittest
from loopforge.engine.lifecycle import (
    DEFAULT_STATE_MACHINE,
    EFFECTS,
    GUARDS,
    LifecycleEvent,
    LifecycleStateMachine,
    RunStage,
    StageStatus,
    TRANSITION_TABLE,
    TransitionResult,
)


def _make_run(stage: str = "task_draft", **overrides) -> dict:
    """Create a minimal run dict for testing."""
    run = {
        "run_id": "test-run",
        "current_stage": stage,
        "stage_statuses": {
            "task": "draft",
            "research": "pending",
            "plan": "pending",
            "implementation": "pending",
            "verification": "pending",
            "review": "pending",
            "publication": "pending",
        },
        "approval": {
            "approved": False,
            "source": "none",
            "approved_at": None,
        },
        "human_gates": {
            "initial_task_approval": {"required": True, "status": "pending"},
            "plan_approval": {"required": True, "status": "pending"},
            "review_approval": {"required": True, "status": "pending"},
        },
        "attempts": [],
        "base_commit": None,
        "risk": {"level": "low", "route": "A", "reasons": [], "required_gates": []},
        "acceptance_criteria": [],
        "verification_commands": [],
    }
    run.update(overrides)
    return run


class TestAllowedTransitions(unittest.TestCase):
    """Table-driven: every allowed transition succeeds."""

    ALLOWED_CASES = [
        # ── Task phase ──
        (
            "task_draft",
            LifecycleEvent.TASK_APPROVE,
            {
                "approval": {
                    "approved": True,
                    "source": "human",
                    "approved_at": "2024-01-01T00:00:00Z",
                },
            },
            "task_approved",
        ),
        ("task_draft", LifecycleEvent.TASK_REJECT, {}, "task_draft"),
        (
            "task_approved",
            LifecycleEvent.RESET_TO_DRAFT,
            {},
            "task_draft",
        ),
        # ── Research phase ──
        (
            "task_approved",
            LifecycleEvent.RESEARCH_START,
            {},
            "research_ready",
        ),
        (
            "research_ready",
            LifecycleEvent.RESEARCH_COMPLETE,
            {
                "stage_statuses": {
                    "task": "draft",
                    "research": "completed",
                    "plan": "pending",
                    "implementation": "pending",
                    "verification": "pending",
                    "review": "pending",
                    "publication": "pending",
                },
            },
            "research_completed",
        ),
        # ── Plan phase ──
        (
            "research_completed",
            LifecycleEvent.PLAN_START,
            {},
            "plan_ready",
        ),
        (
            "plan_ready",
            LifecycleEvent.PLAN_APPROVE,
            {
                "stage_statuses": {
                    "task": "draft",
                    "research": "pending",
                    "plan": "approved",
                    "implementation": "pending",
                    "verification": "pending",
                    "review": "pending",
                    "publication": "pending",
                },
            },
            "plan_approved",
        ),
        # ── Implementation phase ──
        (
            "plan_approved",
            LifecycleEvent.IMPLEMENTATION_START,
            {},
            "implementation_ready",
        ),
        (
            "implementation_ready",
            LifecycleEvent.IMPLEMENTATION_START,
            {},
            "implementation_in_progress",
        ),
        (
            "implementation_in_progress",
            LifecycleEvent.IMPLEMENTATION_COMPLETE,
            {
                "attempts": [{"returncode": 0, "status": "completed"}],
            },
            "implementation_ready",
        ),
        # ── Verification phase ──
        (
            "implementation_ready",
            LifecycleEvent.VERIFICATION_REQUEST,
            {
                "approval": {"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
                "stage_statuses": {
                    "task": "approved",
                    "research": "pending",
                    "plan": "approved",
                    "implementation": "pending",
                    "verification": "pending",
                    "review": "pending",
                    "publication": "pending",
                },
                "attempts": [{"returncode": 0, "status": "completed"}],
                "base_commit": "abc123",
            },
            "verification_ready",
        ),
        (
            "verification_ready",
            LifecycleEvent.VERIFICATION_PASS,
            {},
            "verification_complete",
        ),
        (
            "verification_ready",
            LifecycleEvent.VERIFICATION_FAIL,
            {},
            "verification_blocked",
        ),
        (
            "verification_blocked",
            LifecycleEvent.VERIFICATION_REQUEST,
            {
                "approval": {"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
                "stage_statuses": {
                    "task": "approved",
                    "research": "pending",
                    "plan": "approved",
                    "implementation": "pending",
                    "verification": "blocked",
                    "review": "pending",
                    "publication": "pending",
                },
                "attempts": [{"returncode": 0, "status": "completed"}],
                "base_commit": "abc123",
            },
            "verification_ready",
        ),
        # ── Review phase ──
        (
            "verification_complete",
            LifecycleEvent.REVIEW_START,
            {},
            "review_ready",
        ),
        (
            "review_ready",
            LifecycleEvent.REVIEW_APPROVE,
            {
                "stage_statuses": {
                    "task": "draft",
                    "research": "pending",
                    "plan": "pending",
                    "implementation": "pending",
                    "verification": "pending",
                    "review": "approved",
                    "publication": "pending",
                },
            },
            "review_approved",
        ),
        # ── Publication phase ──
        (
            "review_approved",
            LifecycleEvent.PUBLICATION_PREPARE,
            {},
            "draft_publication_ready",
        ),
    ]

    def test_all_allowed_transitions(self):
        """Every allowed transition succeeds."""
        for stage, event, preconditions, expected_next in self.ALLOWED_CASES:
            with self.subTest(stage=stage, event=event.value):
                run = _make_run(stage, **preconditions)
                result = DEFAULT_STATE_MACHINE.transition(run, event)
                self.assertTrue(
                    result.ok,
                    f"Transition from {stage} with {event.value} failed: [{', '.join(result.blockers)}]",
                )
                self.assertEqual(
                    result.new_stage,
                    expected_next,
                    f"Expected {expected_next} from {stage} via {event.value}, got {result.new_stage}",
                )
                self.assertIsNotNone(result.updated_run)
                self.assertEqual(
                    result.updated_run["current_stage"],
                    expected_next,
                )


class TestRefusedTransitions(unittest.TestCase):
    """Table-driven: every forbidden or guard-blocked transition is refused."""

    def test_refused_unknown_event_from_stage(self):
        """Transitions not in table return ok=False with 'No transition' message."""
        refused_cases = [
            ("task_draft", LifecycleEvent.RESEARCH_START),
            ("task_draft", LifecycleEvent.VERIFICATION_REQUEST),
            ("task_draft", LifecycleEvent.IMPLEMENTATION_START),
            ("task_approved", LifecycleEvent.TASK_APPROVE),
            ("task_approved", LifecycleEvent.VERIFICATION_REQUEST),
            ("research_completed", LifecycleEvent.RESEARCH_START),
            ("plan_approved", LifecycleEvent.RESEARCH_START),
            ("implementation_in_progress", LifecycleEvent.TASK_APPROVE),
            ("verification_complete", LifecycleEvent.VERIFICATION_REQUEST),
            ("review_approved", LifecycleEvent.TASK_APPROVE),
            ("draft_publication_ready", LifecycleEvent.RESEARCH_START),
        ]
        for stage, event in refused_cases:
            with self.subTest(stage=stage, event=event.value):
                run = _make_run(stage)
                result = DEFAULT_STATE_MACHINE.transition(run, event)
                self.assertFalse(result.ok)
                self.assertIsNone(result.new_stage)
                self.assertIn("No transition", result.blockers[0])

    def test_task_approve_blocked_by_guard(self):
        """TASK_APPROVE from task_draft blocked when not approved."""
        run = _make_run("task_draft", approval={"approved": False, "source": "none", "approved_at": None})
        result = DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.TASK_APPROVE)
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_approved_task" in b for b in result.blockers),
            f"Expected has_approved_task in blockers: {result.blockers}",
        )

    def test_research_complete_blocked_without_completed_status(self):
        """RESEARCH_COMPLETE blocked if research not marked completed."""
        run = _make_run(
            "research_ready",
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.RESEARCH_COMPLETE)
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_completed_research" in b for b in result.blockers),
            f"Expected has_completed_research in blockers: {result.blockers}",
        )

    def test_plan_approve_blocked_without_approval(self):
        """PLAN_APPROVE from plan_ready succeeds regardless of plan status (approval is the human decision)."""
        run = _make_run(
            "plan_ready",
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.PLAN_APPROVE)
        self.assertTrue(
            result.ok,
            f"PLAN_APPROVE from plan_ready should succeed; blockers: {result.blockers}",
        )
        self.assertEqual(result.updated_run["current_stage"], "plan_approved")

    def test_plan_approve_allowed_with_completed_status(self):
        """PLAN_APPROVE guard accepts 'completed' status as well as 'approved'."""
        run = _make_run(
            "plan_ready",
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "completed",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.PLAN_APPROVE)
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )

    def test_review_approve_blocked_without_review_approved(self):
        """REVIEW_APPROVE blocked when review stage_status is not 'approved'."""
        run = _make_run(
            "review_ready",
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.REVIEW_APPROVE)
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_approved_review" in b for b in result.blockers),
            f"Expected has_approved_review in blockers: {result.blockers}",
        )


class TestPreVerificationGates(unittest.TestCase):
    """AE3, AE4 and related verification gate tests."""

    def test_verify_on_draft_task_refused(self):
        """task_draft -> verify is refused (not in transition table)."""
        run = _make_run("task_draft")
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertIn("No transition", result.blockers[0])

    def test_verify_on_unapproved_plan_refused(self):
        """imp_ready -> verify with unapproved plan: guard blocks it."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_approved_plan" in b for b in result.blockers),
            f"Expected has_approved_plan in blockers: {result.blockers}",
        )

    def test_verify_without_implementation_candidate_refused(self):
        """VERIFICATION_REQUEST blocked without completed implementation attempt."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[],
            base_commit="abc123",
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_valid_implementation_candidate" in b for b in result.blockers),
            f"Expected has_valid_implementation_candidate in blockers: {result.blockers}",
        )

    def test_verify_without_base_commit_refused(self):
        """VERIFICATION_REQUEST blocked without base_commit."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0, "status": "completed"}],
            base_commit=None,
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_base_commit" in b for b in result.blockers),
            f"Expected has_base_commit in blockers: {result.blockers}",
        )

    def test_verify_without_task_approval_refused(self):
        """VERIFICATION_REQUEST blocked without task approval."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": False, "source": "none", "approved_at": None},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0, "status": "completed"}],
            base_commit="abc123",
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("has_approved_task" in b for b in result.blockers),
            f"Expected has_approved_task in blockers: {result.blockers}",
        )

    def test_verify_with_attempt_status_completed_succeeds(self):
        """Attempt with status=completed (no returncode) satisfies has_valid_implementation_candidate."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": -1, "status": "completed"}],
            base_commit="abc123",
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )

    def test_normalize_rejects_unknown_stage(self):
        """Unknown current_stage should be reset to task_draft."""
        from loopforge.engine import normalize_run_workflow_state

        run = {"current_stage": "invalid_stage_fake"}
        normalized = normalize_run_workflow_state(run)
        self.assertEqual(normalized.get("current_stage"), RunStage.TASK_DRAFT.value)

    def test_normalize_preserves_valid_stage(self):
        """Valid current_stage should be preserved by normalization."""
        from loopforge.engine import normalize_run_workflow_state

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

    def test_returncode_zero_satisfies_candidate_guard(self):
        """Attempt with returncode=0 satisfies has_valid_implementation_candidate."""
        run = _make_run(
            "implementation_in_progress",
            attempts=[{"returncode": 0}],
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.IMPLEMENTATION_COMPLETE
        )
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )


class TestRiskGates(unittest.TestCase):
    """Risk-based gate enforcement."""

    def test_risk_high_adds_plan_approval_gate(self):
        """risk=high requires plan_approval even in autonomous mode."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "high", "required_gates": ["plan_approval"]},
            human_gates={
                "initial_task_approval": {"required": True, "status": "approved"},
                "plan_approval": {"required": True, "status": "pending"},
                "review_approval": {"required": True, "status": "pending"},
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("plan_approval" in b.lower() for b in result.blockers),
            f"Expected plan_approval in blockers: {result.blockers}",
        )

    def test_risk_high_passes_when_plan_approved(self):
        """risk=high with plan_approval approved passes."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "high", "required_gates": ["plan_approval"]},
            human_gates={
                "initial_task_approval": {"required": True, "status": "approved"},
                "plan_approval": {"required": True, "status": "approved"},
                "review_approval": {"required": True, "status": "pending"},
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )

    def test_risk_critical_requires_review_before_verification(self):
        """risk=critical requires review_approval before verification."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "critical", "required_gates": ["review_approval"]},
            human_gates={
                "initial_task_approval": {"required": True, "status": "approved"},
                "plan_approval": {"required": True, "status": "approved"},
                "review_approval": {"required": True, "status": "pending"},
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("review_approval" in b.lower() for b in result.blockers),
            f"Expected review_approval in blockers: {result.blockers}",
        )

    def test_risk_critical_passes_when_review_approved(self):
        """risk=critical with review_approval approved passes verification check."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "critical", "required_gates": ["review_approval"]},
            human_gates={
                "initial_task_approval": {"required": True, "status": "approved"},
                "plan_approval": {"required": True, "status": "approved"},
                "review_approval": {"required": True, "status": "approved"},
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )

    def test_risk_high_and_critical_combined_gates(self):
        """risk=critical with both plan_approval and review_approval required."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={
                "level": "critical",
                "required_gates": ["plan_approval", "review_approval"],
            },
            human_gates={
                "initial_task_approval": {"required": True, "status": "approved"},
                "plan_approval": {"required": True, "status": "pending"},
                "review_approval": {"required": True, "status": "pending"},
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        blocker_text = " ".join(result.blockers).lower()
        self.assertIn("plan_approval", blocker_text)
        self.assertIn("review_approval", blocker_text)

    def test_risk_with_missing_human_gates_dict(self):
        """risk with required_gates but no human_gates dict: still blocked."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "high", "required_gates": ["plan_approval"]},
        )
        run.pop("human_gates", None)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("plan_approval" in b.lower() for b in result.blockers),
            f"Expected plan_approval in blockers: {result.blockers}",
        )

    def test_risk_with_required_gates_not_a_list(self):
        """required_gates that is not a list is treated as empty."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk={"level": "high", "required_gates": "not_a_list"},
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertTrue(
            result.ok,
            f"Transition failed: [{', '.join(result.blockers)}]",
        )


class TestStateMachineAPI(unittest.TestCase):
    """API-level tests."""

    def test_allowed_events_returns_correct_list(self):
        """allowed_events returns exact events for task_draft stage."""
        run = _make_run("task_draft")
        events = DEFAULT_STATE_MACHINE.allowed_events(run)
        event_names = [e.value for e in events]
        self.assertIn("task_approve", event_names)
        self.assertIn("task_reject", event_names)
        self.assertEqual(len(events), 2)

    def test_allowed_events_implementation_ready(self):
        """allowed_events for implementation_ready includes start, complete, verify."""
        run = _make_run("implementation_ready")
        events = DEFAULT_STATE_MACHINE.allowed_events(run)
        event_names = [e.value for e in events]
        self.assertIn("implementation_start", event_names)
        self.assertIn("verification_request", event_names)

    def test_allowed_events_unknown_stage(self):
        """allowed_events for unknown stage returns empty list."""
        run = _make_run("nonexistent_stage")
        events = DEFAULT_STATE_MACHINE.allowed_events(run)
        self.assertEqual(events, [])

    def test_transition_does_not_mutate_input(self):
        """Transition does not mutate the input run dict."""
        run = _make_run("task_draft")
        original = copy.deepcopy(run)
        DEFAULT_STATE_MACHINE.transition(run, LifecycleEvent.TASK_REJECT)
        self.assertEqual(run, original)

    def test_transition_result_has_expected_fields(self):
        """TransitionResult has all expected fields on success."""
        run = _make_run("task_draft")
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.TASK_REJECT
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.current_stage, "task_draft")
        self.assertEqual(result.new_stage, "task_draft")
        self.assertEqual(result.event, "task_reject")
        self.assertIsNotNone(result.updated_run)
        self.assertEqual(result.blockers, [])
        self.assertEqual(result.guard_results, {})

    def test_transition_result_has_guard_results_on_failure(self):
        """TransitionResult includes guard_results on failure."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": False, "source": "none", "approved_at": None},
            attempts=[],
            base_commit=None,
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertFalse(result.ok)
        self.assertTrue(len(result.guard_results) > 0)

    def test_validate_transition_table_no_warnings(self):
        """Validate transition table returns zero warnings."""
        sm = LifecycleStateMachine()
        warnings = sm.validate_transition_table()
        self.assertEqual(warnings, [])

    def test_generated_run_matches_input_stage(self):
        """_make_run produces a run with correct current_stage field."""
        run = _make_run("plan_approved")
        self.assertEqual(run["current_stage"], "plan_approved")

    def test_effects_mutate_updated_run_not_input(self):
        """Effects apply to result.updated_run, not the original."""
        run = _make_run(
            "task_draft",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
        )
        original = copy.deepcopy(run)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.TASK_APPROVE, {"source": "human", "timestamp": "2024-01-01T00:00:00Z"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(run, original)
        self.assertEqual(result.updated_run["current_stage"], RunStage.TASK_APPROVED.value)
        self.assertEqual(
            result.updated_run["stage_statuses"]["task"],
            StageStatus.APPROVED.value,
        )
        self.assertNotEqual(
            run["stage_statuses"]["task"],
            StageStatus.APPROVED.value,
        )


class TestEffectsDetail(unittest.TestCase):
    """Detailed effect behavior verification."""

    def test_mark_task_approved_sets_approval_fields(self):
        """effect_mark_task_approved sets approval fields on updated run."""
        run = _make_run(
            "task_draft",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run,
            LifecycleEvent.TASK_APPROVE,
            {"source": "human", "timestamp": "2024-01-01T00:00:00Z"},
        )
        self.assertTrue(result.ok)
        updated = result.updated_run
        self.assertTrue(updated["approval"]["approved"])
        self.assertEqual(updated["approval"]["source"], "human")
        self.assertEqual(updated["approval"]["approved_at"], "2024-01-01T00:00:00Z")
        self.assertEqual(updated["stage_statuses"]["task"], StageStatus.APPROVED.value)
        self.assertEqual(
            updated["human_gates"]["initial_task_approval"]["status"], "approved"
        )

    def test_reset_approval_resets_to_draft(self):
        """effect_reset_approval resets approval to draft state."""
        run = _make_run("task_approved")
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.RESET_TO_DRAFT
        )
        self.assertTrue(result.ok)
        updated = result.updated_run
        self.assertFalse(updated["approval"]["approved"])
        self.assertEqual(updated["approval"]["source"], "none")
        self.assertIsNone(updated["approval"]["approved_at"])
        self.assertEqual(updated["stage_statuses"]["task"], StageStatus.DRAFT.value)

    def test_mark_research_completed_sets_status(self):
        """effect_mark_research_completed sets research to completed."""
        run = _make_run(
            "research_ready",
            stage_statuses={
                "task": "draft",
                "research": "completed",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.RESEARCH_COMPLETE
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            result.updated_run["stage_statuses"]["research"],
            StageStatus.COMPLETED.value,
        )

    def test_mark_verification_blocked_sets_blocked_status(self):
        """effect_mark_verification_blocked sets verification to blocked."""
        run = _make_run("verification_ready")
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_FAIL
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            result.updated_run["stage_statuses"]["verification"],
            StageStatus.BLOCKED.value,
        )

    def test_mark_review_approved_sets_publish_eligibility(self):
        """effect_mark_review_approved sets publish_eligibility."""
        run = _make_run(
            "review_ready",
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "pending",
                "implementation": "pending",
                "verification": "pending",
                "review": "approved",
                "publication": "pending",
            },
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.REVIEW_APPROVE
        )
        self.assertTrue(result.ok)
        publish = result.updated_run.get("publish_eligibility", {})
        self.assertTrue(publish.get("eligible"), f"publish_eligibility: {publish}")

    def test_mark_publication_ready_sets_publication_completed(self):
        """effect_mark_publication_ready sets publication to completed."""
        run = _make_run("review_approved")
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.PUBLICATION_PREPARE
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            result.updated_run["stage_statuses"]["publication"],
            StageStatus.COMPLETED.value,
        )


class TestGuardEdgeCases(unittest.TestCase):
    """Edge case behaviors for individual guards."""

    def test_has_approved_task_with_non_dict_approval(self):
        """guard_has_approved_task returns False when approval is not a dict."""
        run = _make_run("task_draft", approval=None)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.TASK_APPROVE
        )
        self.assertFalse(result.ok)

    def test_has_completed_research_with_non_dict_stages(self):
        """guard_has_completed_research returns False when stage_statuses is not a dict."""
        run = _make_run("research_ready", stage_statuses=None)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.RESEARCH_COMPLETE
        )
        self.assertFalse(result.ok)

    def test_has_approved_plan_with_non_dict_stages(self):
        """PLAN_APPROVE from plan_ready succeeds (no guard) but effect may warn when stage_statuses is not a dict."""
        run = _make_run("plan_ready", stage_statuses=None)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.PLAN_APPROVE
        )
        self.assertTrue(
            result.ok,
            f"PLAN_APPROVE from plan_ready should succeed; blockers: {result.blockers}",
        )

    def test_has_approved_review_with_non_dict_stages(self):
        """guard_has_approved_review returns False when stage_statuses is not a dict."""
        run = _make_run("review_ready", stage_statuses=None)
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.REVIEW_APPROVE
        )
        self.assertFalse(result.ok)

    def test_has_valid_implementation_candidate_non_list_attempts(self):
        """guard_has_valid_implementation_candidate handles non-list attempts."""
        run = _make_run(
            "implementation_in_progress",
            attempts=None,
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.IMPLEMENTATION_COMPLETE
        )
        self.assertFalse(result.ok)

    def test_has_valid_implementation_candidate_empty_attempts(self):
        """guard_has_valid_implementation_candidate fails on empty attempts list."""
        run = _make_run(
            "implementation_in_progress",
            attempts=[],
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.IMPLEMENTATION_COMPLETE
        )
        self.assertFalse(result.ok)

    def test_has_valid_implementation_candidate_failed_attempts(self):
        """guard_has_valid_implementation_candidate fails when all attempts failed."""
        run = _make_run(
            "implementation_in_progress",
            attempts=[
                {"returncode": 1, "status": "failed"},
                {"returncode": 2, "status": "error"},
            ],
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.IMPLEMENTATION_COMPLETE
        )
        self.assertFalse(result.ok)

    def test_has_valid_implementation_candidate_ignores_non_dict_attempts(self):
        """guard_has_valid_implementation_candidate ignores non-dict entries."""
        run = _make_run(
            "implementation_in_progress",
            attempts=["not_a_dict", {"returncode": 0}],
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.IMPLEMENTATION_COMPLETE
        )
        self.assertTrue(result.ok)

    def test_risk_gates_non_dict_risk_passes(self):
        """guard_risk_gates_satisfied passes when risk is not a dict."""
        run = _make_run(
            "implementation_ready",
            approval={"approved": True, "source": "human", "approved_at": "2024-01-01T00:00:00Z"},
            stage_statuses={
                "task": "draft",
                "research": "pending",
                "plan": "approved",
                "implementation": "pending",
                "verification": "pending",
                "review": "pending",
                "publication": "pending",
            },
            attempts=[{"returncode": 0}],
            base_commit="abc123",
            risk=None,
        )
        result = DEFAULT_STATE_MACHINE.transition(
            run, LifecycleEvent.VERIFICATION_REQUEST
        )
        self.assertTrue(result.ok)


class TestTransitionTableIntegrity(unittest.TestCase):
    """Verify the transition table is internally consistent."""

    def test_no_duplicate_transition_keys(self):
        """TRANSITION_TABLE has no duplicate (stage, event) keys."""
        keys = list(TRANSITION_TABLE.keys())
        self.assertEqual(len(keys), len(set(keys)))

    def test_all_guard_names_registered(self):
        """All guard names in TRANSITION_TABLE exist in GUARDS."""
        for (stage, event), (_next, guards, _effects) in TRANSITION_TABLE.items():
            for guard_name in guards:
                self.assertIn(
                    guard_name,
                    GUARDS,
                    f"Guard '{guard_name}' in transition ({stage}, {event}) not in GUARDS",
                )

    def test_all_effect_names_registered(self):
        """All effect names in TRANSITION_TABLE exist in EFFECTS."""
        for (stage, event), (_next, _guards, effects) in TRANSITION_TABLE.items():
            for effect_name in effects:
                self.assertIn(
                    effect_name,
                    EFFECTS,
                    f"Effect '{effect_name}' in transition ({stage}, {event}) not in EFFECTS",
                )

    def test_all_run_stages_have_at_least_one_transition(self):
        """Every RunStage appears as a source in at least one transition."""
        all_sources = {src for (src, _evt) in TRANSITION_TABLE}
        for stage in RunStage:
            self.assertIn(
                stage.value,
                all_sources,
                f"Stage {stage.value} has no outgoing transitions",
            )

    def test_all_destination_stages_are_valid(self):
        """All destination stages are valid RunStage values."""
        valid_stages = {s.value for s in RunStage}
        for (_src, _evt), (dest, _guards, _effects) in TRANSITION_TABLE.items():
            self.assertIn(
                dest,
                valid_stages,
                f"Destination '{dest}' is not a valid RunStage",
            )

    def test_every_lifecycle_event_is_used(self):
        """Every LifecycleEvent appears in at least one transition."""
        all_events = {evt for (_src, evt) in TRANSITION_TABLE}
        for event in LifecycleEvent:
            self.assertIn(
                event.value,
                all_events,
                f"Event {event.value} is never used in TRANSITION_TABLE",
            )


if __name__ == "__main__":
    unittest.main()