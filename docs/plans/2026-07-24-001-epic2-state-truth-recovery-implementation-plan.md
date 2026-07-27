---
title: Epic 28 - State truth and recovery - Implementation plan
type: implementation
date: 2026-07-24
topic: loopforge-state-truth-recovery
artifact_contract: implementation-plan/v1
source_epic: https://github.com/Loe159/LoopForge/issues/28
parent_roadmap: docs/plans/2026-07-22-001-refactor-loopforge-product-hardening-plan.md
roadmap_phase: 2
---

# Epic #28 — State Truth and Recovery: Implementation Plan

## Context

This plan covers **Phase 2** of the LoopForge 1.0 hardening roadmap. It depends
on Epics 0 and 1 already being completed, and implements requirements R3–R5 and
R10–R15 from the product plan, plus acceptance examples AE3, AE4, AE8, AE9,
AE10.

### Current state gaps (v0.1.0)

- **No `schema_version`** on `run.json`, `config.json`, `registry.json`
- **No inter-process locking** on concurrent writes (unprotected read-modify-write)
- **No compensable transactions** for `create_run` (directories/worktree created before full validation)
- **No centralized state machine** — transitions scattered across `apply_*_approval()` and `verify_run()`
- **`verify_run()` does not check gates** — a `task_draft` run can be verified if a `base_commit` exists
- **Direct pack re-reads** in `verify_run()` instead of using the frozen run contract
- **Silent corruption** — `load_registry()` returns an empty registry on unreadable JSON
- **No quarantine** for corrupt files
- **Non-effective risk** — `risk=low` forced for implementation sessions; risk-based gates never applied

---

## Wave 1 — Preparation: Fixtures, schema_version, data model (Days 1–4)

**Goal:** Freeze 0.1.0 formats, introduce `schema_version` on all persisted
structures, create forward migrations, and prepare the ground for later waves.

### 1.1 Create 0.1.0 format fixtures

- [ ] `tests/fixtures/v0_1_0/` — Representative fixtures for all current formats:
  - `run.json` — full run with task, plan, implementation, verification
  - `config.json` — standard project config
  - `registry.json` — registry with 2–3 projects
  - `index.json` — run index
  - `trusted_packs.json` — trust store
  - `preferences.json` — user preferences
- [ ] `tests/test_migration_v0_1_0.py` — Load each fixture, verify 0.1.0 → 1.0.0 migration produces expected fields

### 1.2 Introduce `schema_version` on all structures

- [ ] `src/loopforge/engine/models/__init__.py` — Package init
- [ ] `src/loopforge/engine/models/schema.py` — New module defining:
  - `SchemaVersion` and constants `CURRENT_RUN_SCHEMA = 2`, `CURRENT_CONFIG_SCHEMA = 2`,
    `CURRENT_REGISTRY_SCHEMA = 2`, `CURRENT_INDEX_SCHEMA = 2`
- [ ] Modify `create_run()` — Add `"schema_version": CURRENT_RUN_SCHEMA` to `run_data`
- [ ] Modify `new_config()` — Add `"schema_version": CURRENT_CONFIG_SCHEMA`
- [ ] Modify registry writes — Add `schema_version` (alongside existing `registry_version`)
- [ ] Modify `indexes.py` — Add `schema_version` (alongside existing `index_version`)

### 1.3 Migration system

- [ ] `src/loopforge/engine/models/migrations.py` — New module with:
  - `MIGRATIONS: dict[int, Callable]` — `source_version → migration_function` mapping
  - `migrate_run(run: dict) -> dict` — Detect version, chain migrations, return current version
  - `migrate_config(config: dict) -> dict`
  - `migrate_registry(registry: dict) -> dict`
  - Each migration function creates a backup (`{file}.v{schema_version}.bak`) before modifying
- [ ] Migration 1→2 — Add `schema_version: 2`; preserve all existing fields
- [ ] Integrate `migrate_run()` into `normalize_run_workflow_state()`
- [ ] Integrate `migrate_config()` into `normalize_config()`
- [ ] Integrate `migrate_registry()` into `load_registry()`

### 1.4 Quarantine for corrupt files

- [ ] `src/loopforge/engine/recovery.py` — New module with:
  - `quarantine_corrupt_file(path: Path) -> Path` — Rename to `{path}.corrupt.{timestamp}`, log error
  - `safe_read_json(store, path) -> tuple[dict | None, str | None]` — Attempt read, quarantine on failure, return `(None, diagnostic)`
- [ ] Modify `load_registry()` — Use `safe_read_json` instead of silent `except: return empty_registry()`
- [ ] Modify `read_run_index()` — Use `safe_read_json`
- [ ] Modify `PackTrustStore._read()` — Use `safe_read_json`

---

## Wave 2 — Locking and transactions (Days 5–8)

**Goal:** Replace unprotected read-modify-write with repositories that provide
inter-process locking and revision tracking. Make `create_run` transactional.

### 2.1 Inter-process lock

- [ ] `src/loopforge/engine/locking.py` — New module:
  - `FileLock` — context manager using `msvcrt.locking()` (Windows) or `fcntl.lockf()` (POSIX)
    on a `{target}.lock` file
  - Configurable timeout (default 5s)
  - Stale lock detection (dead PID)
  - `LockTimeoutError` exception

### 2.2 Repositories with revision

- [ ] `src/loopforge/engine/repositories.py` — New module:
  - `RunRepository` — Encapsulate `read_run_json`, `write_run_json`, `update_run_json` with:
    - Lock on `run.json.lock`
    - `revision` field incremented on each write
    - `update_run_json(run_id, update_fn)` — atomic read-lock-modify-write
    - Compare-and-swap: refuse write if read revision ≠ current revision
  - `ConfigRepository` — Same pattern for `config.json`
  - `RegistryRepository` — Same pattern for `registry.json`
  - `IndexRepository` — Same pattern for `index.json`
- [ ] Adapt `persist_run_json()` to use `RunRepository`
- [ ] Adapt `persist_project_config()` to use `ConfigRepository`
- [ ] Adapt `register_project()` / `save_registry()` to use `RegistryRepository`
- [ ] Adapt `update_run_index()` / `rebuild_run_index()` to use `IndexRepository`

### 2.3 Compensable transactions for `create_run`

- [ ] Refactor `create_run()` into 3 phases:
  1. **Validation** — Validate all inputs (task, pack, config, project_id, base_commit) before any side effect
  2. **Creation** — Create directories, worktree, run.json in a transaction
  3. **Compensation** — On failure during phase 2, remove ALL created artifacts (run_dir, worktree, index entry)
- [ ] Add `_rollback_run_creation(run_dir, workspace_state)` — Idempotent cleanup
- [ ] Test: missing pack failure → no orphan run, worktree, or index entry

### 2.4 Concurrency tests

- [ ] `tests/test_concurrency.py` — New file:
  - `test_two_processes_updating_same_run` — Two threads modify same run.json, verify no lost updates
  - `test_concurrent_create_run_and_list` — One thread creates a run while another lists
  - `test_concurrent_archive_and_continue` — Concurrent archive + continue
  - `test_lock_timeout` — Timeout after 5s if lock is held
  - `test_stale_lock_recovery` — Dead PID lock is recovered
  - `test_dirty_marker_race` — Two processes mark dirty simultaneously

---

## Wave 3 — Lifecycle state machine (Days 9–13)

**Goal:** Replace scattered transitions with a single, typed, exhaustively tested
state machine. Fix `verify_run()` to require all gates.

### 3.1 Define the state machine

- [ ] `src/loopforge/engine/lifecycle.py` — New module:
  - `RunStage` — Typed enum: `TASK_DRAFT`, `TASK_APPROVED`, `RESEARCH_READY`, `RESEARCH_COMPLETED`,
    `PLAN_READY`, `PLAN_APPROVED`, `IMPLEMENTATION_READY`, `IMPLEMENTATION_IN_PROGRESS`,
    `VERIFICATION_READY`, `VERIFICATION_BLOCKED`, `VERIFICATION_COMPLETE`,
    `REVIEW_READY`, `REVIEW_APPROVED`, `PUBLICATION_READY`
  - `StageStatus` — Enum: `PENDING`, `DRAFT`, `IN_PROGRESS`, `APPROVED`, `COMPLETED`, `BLOCKED`, `FAILED`
  - `LifecycleEvent` — Event enum: `TASK_APPROVE`, `TASK_REJECT`, `RESEARCH_START`, `RESEARCH_COMPLETE`,
    `PLAN_START`, `PLAN_APPROVE`, `IMPLEMENTATION_START`, `IMPLEMENTATION_COMPLETE`,
    `VERIFICATION_REQUEST`, `VERIFICATION_PASS`, `VERIFICATION_FAIL`,
    `REVIEW_START`, `REVIEW_APPROVE`, `PUBLICATION_PREPARE`, `RESET_TO_DRAFT`
  - `TransitionTable` — `dict[(current_stage, event) -> (next_stage, guards, effects)]`
  - `LifecycleStateMachine` — Class with:
    - `transition(run, event, context) -> TransitionResult`
    - `allowed_events(run) -> list[LifecycleEvent]`
    - Guards: `has_approved_task`, `has_completed_research`, `has_approved_plan`,
      `has_valid_implementation_candidate`, `has_base_commit`,
      `has_pack_trust`, `has_executable_evidence`
  - `TransitionResult` — Dataclass with `ok`, `new_stage`, `updated_run`, `blockers`

### 3.2 Integrate the state machine

- [ ] Replace `apply_initial_task_approval()` with `state_machine.transition(run, TASK_APPROVE, ctx)`
- [ ] Replace `apply_plan_approval()` with `state_machine.transition(run, PLAN_APPROVE, ctx)`
- [ ] Replace `apply_review_approval()` with `state_machine.transition(run, REVIEW_APPROVE, ctx)`
- [ ] Replace inline transitions in `verify_run()` with state machine calls
- [ ] Replace inline transitions in `continue_run()` with state machine calls
- [ ] Update `normalize_run_workflow_state()` — Reject unknown stages instead of preserving them
- [ ] Add validation: unknown `current_stage` → explicit error, not silent fallback

### 3.3 Fix `verify_run()` — Require all gates

- [ ] Add pre-verification guards:
  - `task` must be `approved` (not `draft`)
  - `plan` must be `approved`
  - `implementation` must have a valid candidate (at least one completed attempt with `returncode == 0` or `implementation_ready`)
  - `base_commit` must exist
  - Pack checks must be accessible and trusted
- [ ] Test AE3: `task_draft` → `verify` is refused, no check commands executed
- [ ] Test AE4: non-empty patch, diff OK, but test fails → `verification_blocked` with link to criterion

### 3.4 Separate `acceptance_criteria` from `verification_commands`

- [ ] Modify `run.json` schema — Add:
  - `acceptance_criteria: list[str]` — Human-defined textual criteria
  - `verification_commands: list[dict]` — Executable commands with criterion mapping
- [ ] Adapt `create_run()` to populate both fields separately
- [ ] Adapt `verify_run()` to execute `verification_commands` and link each result to a criterion
- [ ] Adapt `render_verification_markdown()` to display criterion→result mapping

---

## Wave 4 — Frozen effective pack contract (Days 14–17)

**Goal:** Hydrate and freeze the complete pack contract in the run. Remove all
direct re-reads of the mutable pack during run execution.

### 4.1 Extend frozen contract in `run.json`

- [ ] Modify `create_run()` — The stored `pack_contract` must include:
  - `checks` — Complete check list with commands, env, timeouts, and `content_hash`
  - `protected_paths` — High/medium patterns with `content_hash`
  - `memory_rules` — Content of `memory-rules.md`
  - `permissions` — Complete permission_sets
  - `agents` — Agents with resolved prompts
  - `workflow` — Complete stages
  - `contract_hash` — Global hash of the complete contract
  - `skills_content_hash` — Hash of skills content
  - `frozen_at` — Freeze timestamp
- [ ] `EffectivePackContract` — Typed dataclass instead of free dict

### 4.2 Remove direct re-reads

- [ ] `verify_run()` — Read checks from `run["pack_contract"]["checks"]` instead of calling `load_pack_checks()`
- [ ] `continue_run()` — Read permissions/protected_paths from frozen contract
- [ ] `merged_risk_policy_path()` — Read protected_paths from frozen contract
- [ ] Add test: modify pack on disk after `create_run` → verify that `verify_run` uses the old frozen contract

### 4.3 Diagnose malformed or ignored packs

- [ ] `PackRegistry` — Stop silently ignoring malformed packs in `discover_contracts()`
- [ ] `doctor` — Add detection: pack listed in `.loopforge/packs/` but `pack.json` invalid → diagnostic
- [ ] `doctor` — Add detection: pack ignored due to cyclic inheritance → diagnostic

---

## Wave 5 — Effective risk, recovery, and non-Git behavior (Days 18–21)

**Goal:** Make risk a persisted datum that actually influences gates. Extend
`doctor`. Apply the non-Git decision.

### 5.1 Effective risk

- [ ] Modify `execute_attempt()` — Stop forcing `risk=low`; use actual classified risk
- [ ] Modify `classify_patch_risk` — Also return additional gates required by risk level
- [ ] Apply gates in state machine:
  - `risk=high` → `plan_approval` required even in `autonomous` mode
  - `risk=critical` → `review_approval` required before verification
- [ ] Persist risk in `run.json` after each classification
- [ ] Test: run with `risk=high` → additional gates applied

### 5.2 Extend `doctor`

- [ ] `DoctorService` — Extract diagnostic logic into `src/loopforge/engine/doctor.py`
  (currently duplicated between top-level and slash)
- [ ] Added diagnostics:
  - Corrupt files → quarantine, diagnostic, proposed action
  - Stale indexes → rebuild proposed with preview
  - Orphan worktrees → detection and proposed cleanup
  - Invalid roots (outside LOOPFORGE_HOME) → diagnostic
  - Ignored packs (malformed) → diagnostic
  - Incompatible schemas → migration proposed
  - `current_run_id` pointing to nonexistent run → reset proposed
- [ ] Unify `/doctor` and `loopforge doctor` — Call the same `DoctorService`
- [ ] Make repairs idempotent with preview before action

### 5.3 Non-Git policy

- [ ] Reject `shared-checkout` early — In `create_run()`, if no Git repo → refuse with clear message
  (unless snapshot backend is enabled)
- [ ] Or: implement a snapshot backend — Create `NonGitSnapshotService` to copy workspace into isolated directory
- [ ] Test: non-Git project → `create_run` refuses with clear diagnostic before any creation

### 5.4 Git worktree HEAD

- [ ] Fix `GitStateService` — Use `git rev-parse --git-common-dir` for correct worktree handling
- [ ] Test with real Git worktree (`git worktree add`)

---

## Wave 6 — Integration and end-to-end tests (Days 22–25)

**Goal:** Integrate all components, validate the full test matrix required by the
epic, and verify the exit gate.

### 6.1 Transition table tests

- [ ] `tests/test_lifecycle.py` — New file:
  - `test_all_allowed_transitions` — Table-driven: every allowed transition succeeds
  - `test_all_refused_transitions` — Table-driven: every forbidden transition is refused
  - `test_verify_on_draft_task` — Refused (AE3)
  - `test_verify_on_unapproved_plan` — Refused
  - `test_verify_without_implementation_candidate` — Refused
  - `test_verify_on_empty_patch` — Behavior per defined policy
  - `test_verify_without_base_commit` — Refused
  - `test_normalize_rejects_unknown_stage` — Error, not fallback
  - `test_risk_high_adds_gates` — Additional gates
  - `test_risk_critical_requires_review` — Review required

### 6.2 Crash and corruption tests

- [ ] `tests/test_fault_tolerance.py` — New file:
  - `test_crash_during_run_creation` — Simulate OSError after directory creation → no orphan artifacts (AE9)
  - `test_crash_during_migration` — Backup preserved, idempotent resume
  - `test_corrupt_registry_recovery` — Original file quarantined, index rebuilt (AE10)
  - `test_corrupt_run_json_recovery` — Diagnostic, no silent replacement
  - `test_corrupt_index_rebuilt_from_authoritative_runs` — Rebuild OK
  - `test_two_process_lost_update` — CAS detects conflict, no data loss (AE8)
  - `test_concurrent_dirty_marker` — No index corruption

### 6.3 Migration tests

- [ ] `tests/test_migration.py` — New file:
  - `test_migrate_v0_1_0_run_to_current` — 0.1.0 fixture auto-migrated
  - `test_migrate_v0_1_0_config_to_current`
  - `test_migrate_v0_1_0_registry_to_current`
  - `test_migration_is_idempotent` — Double migration does not corrupt
  - `test_migration_with_old_and_new_roots` — Both roots present
  - `test_clone_identity_regeneration_with_current_run` — Regeneration + current_run_id preserved

### 6.4 Effective pack tests

- [ ] `tests/test_effective_pack.py` — New file:
  - `test_frozen_contract_used_for_verification` — Disk modification ignored
  - `test_effective_pack_inheritance` — Correct additive inheritance
  - `test_effective_pack_override` — Correct override
  - `test_malformed_pack_diagnosed` — Diagnostic instead of silent fallback
  - `test_pack_mutation_after_run_creation_ignored` — Frozen contract is authoritative

### 6.5 Update existing tests

- [ ] Fix the 2 existing failures + 1 error in the suite
- [ ] Adapt `test_cli.py` — Replace direct JSON mutations with engine API calls
- [ ] Adapt `test_engine_services.py` — Add quarantine, migration, lock tests

---

## Required Test Matrix (from the epic)

| Category | Tests | Target file |
|---|---|---|
| Allowed/refused transitions | Every event × every stage | `tests/test_lifecycle.py` |
| Verify on invalid states | draft, unapproved, no-candidate, empty-patch | `tests/test_lifecycle.py` |
| Two-process concurrency | Lost-update, dirty-marker race | `tests/test_concurrency.py` |
| Crash injection | After every transactional boundary | `tests/test_fault_tolerance.py` |
| Corruption recovery | config, run, registry, index | `tests/test_fault_tolerance.py` |
| Migration | old/new roots, clone identity, current run | `tests/test_migration.py` |
| Effective pack | inheritance, mutation after creation | `tests/test_effective_pack.py` |
| Git worktree | Real worktree, non-Git policy | `tests/test_engine_services.py` (extend existing) |

---

## Exit Gate (final verifications)

- [ ] `python -m unittest` — 100% green, zero regressions
- [ ] Verification cannot pass without **all** required gates and executable evidence
- [ ] No two-process test loses an authoritative update
- [ ] Failed creation/migration leaves **zero** orphan resources
- [ ] Corruption preserves original data and produces an actionable diagnosis
- [ ] 0.1.0 fixtures migrate automatically and idempotently
- [ ] The frozen pack contract shown to the user is exactly what executes
- [ ] `git diff --check` passes

---

## Files to create

| File | Role |
|---|---|
| `src/loopforge/engine/models/__init__.py` | Models package |
| `src/loopforge/engine/models/schema.py` | SchemaVersion, constants |
| `src/loopforge/engine/models/migrations.py` | Migration system |
| `src/loopforge/engine/locking.py` | Cross-platform FileLock |
| `src/loopforge/engine/repositories.py` | Repositories with lock + revision |
| `src/loopforge/engine/lifecycle.py` | State machine |
| `src/loopforge/engine/recovery.py` | Quarantine, safe_read |
| `src/loopforge/engine/doctor.py` | Unified DoctorService |
| `tests/fixtures/v0_1_0/*.json` | 0.1.0 format fixtures |
| `tests/test_lifecycle.py` | Transition table tests |
| `tests/test_concurrency.py` | Concurrency tests |
| `tests/test_fault_tolerance.py` | Crash/corruption tests |
| `tests/test_migration.py` | Migration tests |
| `tests/test_effective_pack.py` | Effective pack tests |

## Files to modify substantially

| File | Changes |
|---|---|
| `src/loopforge/engine/__init__.py` | `create_run` → add `schema_version` + full `pack_contract` + pre-validation + compensation. `verify_run` → mandatory gates + frozen contract. `normalize_run_workflow_state` → strict validation + migration |
| `src/loopforge/engine/storage.py` | Optional lock integration (via `repositories.py`) |
| `src/loopforge/engine/projects.py` | `load_registry` → safe_read_json + migration + schema_version |
| `src/loopforge/engine/indexes.py` | `read_run_index` → safe_read_json + schema_version |
| `src/loopforge/engine/packs.py` | `PackTrustStore._read` → safe_read_json. Malformed pack diagnostics |
| `src/loopforge/engine/git_state.py` | Fix `commondir` for real worktrees |
| `tests/test_engine_services.py` | Additions for recovery, worktree, non-Git |
| `tests/test_cli.py` | Adapt to new contracts |

---

## Out of scope (deferred to Epics 3–5)

- Broad engine facade decomposition into domain modules (Epic 3)
- TUI/presentation unification and UX polish (Epic 4)
- CI/CD, release automation, license (Epic 5)
- Remote pack marketplace, multi-user, cloud sync
- Non-Git snapshot backend (unless decided as v1 scope)