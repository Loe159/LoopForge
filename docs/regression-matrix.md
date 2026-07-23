---
title: "LoopForge P0 Regression Matrix"
type: regression-matrix
date: 2026-07-23
topic: epic0-green-baseline
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/26
artifact_contract: regression-matrix/v1
artifact_readiness: final
---

# P0 Regression Matrix

Each regression case is designed to **fail** on the current green baseline. These
tests will be made green in Epic 1 (Critical Hardening) and Epic 2 (Lifecycle
Robustness). Every entry includes a minimal reproducer description, target epic,
and acceptance condition.

## P0-1 — Path Confinement

- **Domain:** Security
- **Setup:** Configure a project with `project_id=../../escape`
- **Trigger:** Call `initialize_project()`
- **Expected:** Raises `ValueError` before any disk access; no path traversal
- **Target Epic:** Epic 1
- **Acceptance:** Unit test that asserts `ValueError` is raised with the
  malicious project_id

## P0-2 — Pack Trust

- **Domain:** Security
- **Setup:** Place an untrusted local pack inside `.loopforge/packs`
- **Trigger:** Call `verify_run()` in non-interactive mode
- **Expected:** Exit code ≠ 0; no check execution takes place; error message
  identifies the untrusted pack
- **Target Epic:** Epic 1
- **Acceptance:** Unit test verifying non-zero exit and absence of check
  execution artifacts

## P0-3 — Verify Bypass

- **Domain:** Lifecycle integrity
- **Setup:** Create a run in `task_draft` stage with all stages `pending`
- **Trigger:** Call `verify_run()`
- **Expected:** Run state is unchanged; no commands are executed; result
  message states verification is unavailable
- **Target Epic:** Epic 2
- **Acceptance:** Unit test confirming no state mutation and no subprocess
  launch

## P0-4 — Success Checks Without Evidence

- **Domain:** Verification integrity
- **Setup:** Create a run with `success_checks=["Tests pass"]` but no check
  has been executed
- **Trigger:** Call `verify_run()`
- **Expected:** Status returns `verification_blocked`; missing evidence is
  listed in blockers
- **Target Epic:** Epic 2
- **Acceptance:** Unit test asserting status and blocker message content

## P0-5 — Infinite Output and Child Processes

- **Domain:** Process isolation
- **Setup:** Configure an adapter that forks a child process writing
  continuously to stdout
- **Trigger:** Call `verify_run()` with a timeout
- **Expected:** Output is bounded to the configured limit; the process tree
  is killed; status is not `completed`
- **Target Epic:** Epic 1
- **Acceptance:** Unit test with a test adapter that simulates runaway output

## P0-6 — TUI Target vs Mutation Target

- **Domain:** Interactive UI
- **Setup:** Project with 2 runs; run B is highlighted in the TUI
- **Trigger:** Invoke the Archive action
- **Expected:** Confirmation dialog names run B; only run B is mutated after
  revalidation; run A is untouched
- **Target Epic:** Epic 1
- **Acceptance:** TUI integration test with snapshot comparison

## P0-7 — Post-Commit Cancellation

- **Domain:** Transaction integrity
- **Setup:** An operation that commits changes, then raises `CancelledError`
- **Trigger:** Inspect `_operation_result()`
- **Expected:** Status is `commit_started` or `completed`; never `cancelled`
- **Target Epic:** Epic 1
- **Acceptance:** Unit test with a mock operation that cancels after commit

## P0-8 — JSON on TTY

- **Domain:** Output contract
- **Setup:** stdout is attached to a TTY
- **Trigger:** Execute `loopforge run --json`
- **Expected:** First byte written to stdout is `{`; all progress messages
  appear on stderr only
- **Target Epic:** Epic 1
- **Acceptance:** CLI test with captured stdout/stderr streams

## P0-9 — /raw Path Escape

- **Domain:** Security
- **Setup:** `run.json` is modified with `artifact_path=/etc/passwd`
- **Trigger:** Execute `/raw <artifact>` in the TUI or CLI
- **Expected:** Refusal; path is resolved only within the run directory;
  error message indicates confinement
- **Target Epic:** Epic 1
- **Acceptance:** Unit test with path-traversal fixture

## P0-10 — Orphaned Run Creation

- **Domain:** Lifecycle integrity
- **Setup:** Nonexistent pack after worktree preparation
- **Trigger:** Call `create_run()`
- **Expected:** No orphaned `run.json`, worktree directory, index, or pointer
  is left behind; error is raised
- **Target Epic:** Epic 2
- **Acceptance:** Unit test asserting no artifacts exist on filesystem after
  failure