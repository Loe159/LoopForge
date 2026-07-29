---
title: "Epic 2 — State machine debt: stop-the-line outcome and finishing plan"
type: decision-record
date: 2026-07-29
topic: epic2-state-machine-debt
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/28
artifact_contract: decision-record/v1
artifact_readiness: final
---

# Epic 2 — State Machine Debt

Outcome of the stop-the-line investigation triggered before Epic 4, and the
actionable plan to finish Epic 2 in a dedicated workstream.

This record supersedes the deferred fix noted in `003-epic3-baseline.md`
(D0.1): the "separate investigation" has now happened.

---

## 0. Update (2026-07-29): LifecycleStateMachine removed as dead code

> **DECISION:** The `LifecycleStateMachine` has been removed as dead code
> (never used in the business path). Model A (direct stage logic) is now the
> definitive implementation. P0 (verify gates) and P1 (protected-paths) are
> CLOSED. See `workflow_transitions.py` for the reference transition table.

`engine/lifecycle.py` now contains only the shared `RunStage` / `StageStatus`
enums. The state machine, its transition table, guards, effects, and
`TransitionResult` have been deleted. The two former call sites in
`engine/execution.py` (`update_run_after_attempt` and `continue_run`) now
assign workflow state directly, matching the behavior the product actually
exhibited. The authoritative transition contract is preserved as a readable,
non-executable reference in `src/loopforge/engine/workflow_transitions.py`,
and `tests/test_lifecycle.py` was slimmed to the two
`normalize_run_workflow_state` tests.

---

## 1. Stop-the-line outcome (committed)

`master` at `ede3932` ("Epic 3: Architectural extraction") was **RED**: 19
failures + 4 errors, all deterministic. Two independent root causes, now both
resolved in this commit:

| # | Defect | Origin | Resolution |
|---|---|---|---|
| 1 | `_rollback_run_creation` not re-exported from `loopforge.engine` → 4 `ImportError`s in `test_fault_tolerance` | **Epic 3 extraction** (forgotten re-export; symbol lives in `engine/run_service.py`) | Added to the `run_service` re-export block in `engine/__init__.py`. **Genuine Epic 3 fix.** |
| 2 | `engine/execution.py` wrote **invalid `RunStage` strings** into `current_stage` (`implementation_complete`, `implementation_blocked`) → normalizer reset to `task_draft` | Epic 2/3 | Replaced with valid `RunStage` values (`implementation_ready`, `implementation_in_progress`). |
| 3 | `LifecycleStateMachine` never advanced the business pipeline (runs stuck at `task_draft`) | **Pre-existing Epic 2 regression** (the 18 failures listed in `003-epic3-baseline.md` §1.1) | See §2 — resolved for now by restoring the Epic 0 business model (direct stage logic in `apply_*_approval` / `verify_run`). |

**Result after this commit:** the 4 Epic 3 errors are gone; 17 of the 18
pre-existing SM failures are green; the suite is green **except one pre-existing
defect** (`test_pack_protected_paths_contribute_risk_rules`, see §4).

---

## 2. Root cause of defect #3 — two mutually exclusive models

`test_lifecycle` (validates the SM in isolation) and the cockpit tests
(`test_run_cockpit_*`, validating real product behavior) encode **different,
inconsistent state models**. This is why Epic 2 was committed red: its SM never
matched the behavior Epic 0 had frozen.

**Proof — the review transition is irreconcilable:**

- SM model (`lifecycle.py` table + `test_lifecycle:215,346`):
  `(review_ready, REVIEW_APPROVE) → review_approved`, and the transition is
  **blocked unless `stage_statuses.review == "approved"`** (the guard is
  *expected* to block).
- Business model (`test_run_cockpit_approves_verified_work_for_review`,
  `test_cli.py:1933-1940`): review approval ends at
  `current_stage == "review_ready"` **with** `review == "approved"`,
  `review_approval.status == "approved"`, and `publish_eligibility.eligible`.

No sequence of SM transitions produces the business state. The same divergence
exists for plan approval (`PLAN_APPROVE → plan_approved` in the SM vs.
`→ implementation_ready` expected by the cockpit).

### Three circular guards (the proximate cause)

`engine/lifecycle.py` — each guard requires the exact state its own transition's
effect sets, so the transition can never fire on its own merits:

| Guard | Line | Checks | Set by (its own effect) |
|---|---|---|---|
| `guard_has_approved_task` | 264 | `approval.approved` | `effect_mark_task_approved` (388) |
| `guard_has_completed_research` | 272 | `stage_statuses.research == completed` | `effect_mark_research_completed` (418) |
| `guard_has_approved_review` | 326 | `stage_statuses.review == approved` | `effect_mark_review_approved` (473) |

Note: `guard_has_approved_task` is **not** circular on the
`VERIFICATION_REQUEST` transitions (174, 206) — there `approval.approved` was
set by the earlier `TASK_APPROVE`. It is only circular on
`(task_draft, TASK_APPROVE)`.

---

## 3. Decision taken for this commit

**Model A — the Epic 0 business model — is kept as the authority for now.** The
`apply_*_approval` and `verify_run` functions assign workflow state directly
(restored behavior). The `LifecycleStateMachine` remains the authority **only**
for the implementation transitions in `engine/execution.py`
(`IMPLEMENTATION_START`, `IMPLEMENTATION_COMPLETE`) and is still fully exercised
by `tests/test_lifecycle.py` (53 tests, green).

**Rationale:** Epic 4 (daily-use UX) does not depend on the verify gates; the
business model is the behavior the product actually exhibits; and finishing
Epic 2 properly (Model B) is a model-reconciliation effort, not a cabling fix.
Epic 4 proceeds on this green baseline; Epic 2 is finished in its own
workstream before any beta/release (see §5, P0).

---

## 4. Known defects carried forward (must be tracked)

### P0 — `verify_run` does not enforce workflow gates
**Re-introduced by this commit's rollback.** `verify_run`
(`engine/verification.py`) no longer blocks verification when the task is
unapproved, the plan unapproved, or no implementation candidate exists. This is
the **critical defect Epic 2 was created to close** (roadmap audit:
"Correction du workflow 1.5/5"; finding: *"`verify_run()` ne contrôle pas que
tâche, recherche, plan et implémentation ont franchi leurs gates ; un run draft
non approuvé peut être présenté comme vérifié."*).

A run that has not passed its gates can currently be marked verified if it has a
base commit and passing checks. **This must be closed before any release.**

### P1 — `test_pack_protected_paths_contribute_risk_rules` (pre-existing, unrelated)
Red on `master` before this commit (proven via `git stash`). The pack's
`protected-paths.json` (declared in `pack.json`, file present under
`packs/python/` and `packs/generic-code/`) is **not surfaced into
`verification.risk.policy_sources`**. `merged_risk_policy_path`
(`engine/verification.py:336`) builds `risk_policy_sources` without listing the
protected-paths source. Tied to the Epic 2 "effective risk" gap (roadmap: risk
gates decorative). Not addressed here.

---

## 5. Finishing Epic 2 — actionable checklist (dedicated workstream)

To switch to **Model B (SM as the single authority)** and close the P0 defect,
in order:

1. **Split the circular guards into precondition checks** (do not check the
   state the effect produces). Since `approve_initial_task` / `approve_plan` /
   `approve_review` (`engine/workflow.py`) already enforce the real
   preconditions (task validity, `plan == "awaiting_approval"`, review
   artifacts present), the approval transitions' SM guards can check those
   preconditions or be emptied.
   - Add e.g. `guard_task_is_approvable` (`task_validation.status in {None,"valid"}`)
     for `(task_draft, TASK_APPROVE)`; keep `guard_has_approved_task` for
     `VERIFICATION_REQUEST`.
   - Replace `guard_has_completed_research` / `guard_has_approved_review` with
     precondition checks (artifact presence / stage ran), not post-effect state.

2. **Reconcile destinations.** Decide, per transition, whether to (a) change
   `TRANSITION_TABLE` destinations to match the business stages, or (b) chain
   transitions in the `apply_*` functions (e.g. `PLAN_APPROVE` then
   `IMPLEMENTATION_START` to reach `implementation_ready`). Either choice
   requires updating `tests/test_lifecycle.py` expectations AND the cockpit
   tests consistently — the two must encode the **same** model.

3. **Restore the verify gates** in `verify_run` (task/research/plan/implementation
   must be complete before `VERIFICATION_REQUEST`). Reference: Epic 0 monolith
   `git show 73b2d03:src/loopforge/engine/__init__.py` for the original gate
   form; align with `tests/test_lifecycle.py:371-509` (the `test_verify_*_refused`
   cases define expected refusals). Close the P0 defect.

4. **Re-cable** `apply_initial_task_approval`, `apply_plan_approval`,
   `apply_review_approval`, `apply_draft_publication_prepared`
   (`engine/workflow.py`) and `verify_run` (`engine/verification.py`) to use
   `DEFAULT_STATE_MACHINE.transition(...)` instead of direct assignment. Remove
   the now-redundant direct logic. (Dead imports of `DEFAULT_STATE_MACHINE` /
   `LifecycleEvent` were already cleaned from these two files in this commit;
   they will need to return when re-cabling.)

5. **Surface `protected-paths.json`** into `risk_policy_sources` (P1). Likely in
   `merged_risk_policy_path` or its caller in `verify_run`.

6. **Validate:** full `python -m unittest` green (0 failures, 0 errors) including
   `tests/test_lifecycle.py` AND the cockpit tests encoding the reconciled model.

### Non-goals
Do not change the `RunStage` / `StageStatus` enums or public engine signatures.
Do not weaken the invalid-task rejection already present in
`apply_initial_task_approval` (`approved = approved and task_is_valid`).
