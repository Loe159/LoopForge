---
title: "Epic 0 — Stop the line: implementation plan"
type: implementation-plan
date: 2026-07-23
topic: epic0-green-baseline
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/26
artifact_contract: implementation-plan/v1
artifact_readiness: final
execution: code
---

# Epic 0 — Stop the Line: Implementation Plan

## Goal Capsule

- **Objective:** établir une baseline verte et fiable de 229 tests, prendre les décisions bloquantes (licence, non-Git, install/update), classifier la surface supportée, et préparer une matrice de régressions P0.
- **Parent roadmap:** [LoopForge 1.0 product hardening](2026-07-22-001-refactor-loopforge-product-hardening-plan.md)
- **GitHub epic:** [#26](https://github.com/Loe159/LoopForge/issues/26)
- **Blocks:** tous les epics suivants (1 à 5)
- **Duration estimate:** 1 à 2 semaines

---

## Context

**Current state on `master`:**
- 229 tests: 2 failures + 1 error reproductible
- Failures at `tests/test_cli.py:1676`, `tests/test_cli.py:2719`, `tests/test_cli_textual_app.py:166`
- 40 tests pass in the focused suites (`test_engine_services`, `test_implementation_result_integrity`)
- No CI, no license, no release process
- Documented E2E runner and TUI benchmark are not executable

---

## Step 1 — Blocking Decisions (resolve before any code change)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | **License** | MIT, Apache 2.0, GPLv3 | MIT — maximizes adoption, compatible with Python ecosystem |
| D2 | **Non-Git projects** | Refuse in v1 OR fund a real snapshot backend | Refuse early in v1 with clear message + v2 ticket |
| D3 | **`install` / `update` commands** | Remove OR redefine without `git pull` assumption | Remove self-modifying commands; replace with `pip install` guidance |
| D4 | **Divergent CLI assertions** (plan prompt paths vs embedded artifacts) | Embed artifacts in prompt vs expose run-directory paths | Embed artifacts inline (absolute paths are a security leak per R34) |
| D5 | **No-op adapter + LOOPFORGE_HOME inside project** | Classify correctly | Exclude real runtime root (`LOOPFORGE_HOME`, `.loopforge/`) from workspace snapshot |

**Step 1 validation:** decisions recorded in `docs/decisions/001-epic0-baseline.md`.

---

## Step 2 — Fix the Test Suite to Green

### 2.1 Diagnosis of the 3 Known Failures

#### Failure 1 — `test_run_cockpit_executes_plan_with_fixture_adapter` (line 1676–1678)

**File:** `tests/test_cli.py`  
**Test method:** `test_run_cockpit_executes_plan_with_fixture_adapter` (line 1625)

The test asserts that `str(run_dir / "task.md")` and `str(run_dir / "research.md")` appear in the generated prompt. Decision D4 concludes that prompts should embed artifact *content*, not absolute filesystem paths.

**Action:**
- Modify the test to verify that the prompt embeds artifact content rather than absolute paths.
- If the current product code writes paths, update the assertion to reflect the expected behavior (artifact content inlined in the prompt).
- If absolute paths are kept for the baseline, use `os.path.relpath` or `run_dir.name` instead. However, D4 recommends inlining.

**Effort:** 45 min

#### Failure 2 — `test_global_flags_work_after_command_and_before_adapter_separator` (line 2719)

**File:** `tests/test_cli.py`  
**Test method:** `test_global_flags_work_after_command_and_before_adapter_separator` (line 2691)

The test calls `self.approve_current_run_for_implementation(repo, loopforge_home_dir)` which advances through task and plan approval gates, then runs `main(["continue", "--adapter", "local-adapter-fixture", "--", ...])` expecting exit code 1.

**Likely failure modes:**
- `approve_current_run_for_implementation` (around line 244) directly mutates `run.json` instead of using the public engine API
- The `continue` command returns a different exit code

**Action:**
- Inspect the `approve_current_run_for_implementation` helper method
- Correct mutations to use `approve_task`/`approve_plan` from the engine API
- If the product behavior changed (e.g., exit code 0 instead of 1), update the test assertion accordingly

**Effort:** 30 min

#### Failure 3 — `test_pilot_exits_the_textual_backend` (line 166)

**File:** `tests/test_cli_textual_app.py`  
**Test method:** `test_pilot_exits_the_textual_backend` (line 163)

The assertion `self.assertFalse(app.is_running)` after pressing `Ctrl+C` fails, likely due to Textual 8.x changes in `is_running` semantics or async timing.

**Action:**
- Replace with a public API assertion: check `app._exit` is True, use `app.return_code`, or add `await pilot.pause()` before the assertion
- Document the tested Textual version

**Effort:** 15 min

### 2.2 Fix Order

| Order | Test | File | Effort |
|---|---|---|---|
| 1 | `test_pilot_exits_the_textual_backend` | `tests/test_cli_textual_app.py:163` | 15 min |
| 2 | `test_global_flags_work_after_command_and_before_adapter_separator` | `tests/test_cli.py:2691` | 30 min |
| 3 | `test_run_cockpit_executes_plan_with_fixture_adapter` | `tests/test_cli.py:1625` | 45 min |

### 2.3 Post-Fix Verification

```bash
python -m unittest                          # must pass: 229+ OK, 0 fail, 0 error
python -m compileall -q src                 # no syntax errors
git diff --check                            # no whitespace or conflict markers
```

Run twice consecutively to confirm zero flaky tests.

---

## Step 3 — Supported Surface Matrix

Produce `docs/support-matrix.md`:

| Surface | Status | Tested version | Notes |
|---|---|---|---|
| Top-level CLI (`loopforge <cmd>`) | Supported | 0.1.0 | |
| `--plain` | Compatible | 0.1.0 | No TUI, headless |
| `shell --command` | Supported | 0.1.0 | |
| `shell --script` | Supported | 0.1.0 | |
| Textual TUI | Supported | Textual ≥8.0,<9 | |
| `.agent/checks/` launchers | See classification below | | |

### `.agent/checks/` Launcher Classification

| Launcher | Classification | Rationale |
|---|---|---|
| `build_stage_context.py` | Supported | Used by adapters |
| `check_stage_readiness.py` | Supported | Used by state machine |
| `classify_patch_risk.py` | Supported | Used by verify pipeline |
| `diff_policy.py` | Supported | Used by patch pipeline |
| `generate_complete_patch.py` | Supported | Patch generation |
| `initialize_portable_run.py` | Compatibility | Legacy path |
| `isolated_process.py` | Supported | Process isolation |
| `record_run_metrics.py` | Supported | Metrics |
| `validate_artifacts.py` | Compatibility | Wrapper around `loopforge.checks` |
| `validate_disposable_worktree.py` | Supported | Worktree validation |
| `validate_implementation_result.py` | Compatibility | Wrapper around `loopforge.checks` |

Add `--help` smoke tests for every **supported** launcher (compatibility-only launchers are exempt).

---

## Step 4 — P0 Regression Matrix with Reproducers

For each critical finding, design a **minimal regression test** that fails on the green baseline. Document in `docs/regression-matrix.md`. These tests will be made green in Epics 1 and 2.

| # | Domain | Test Design (setup → trigger → expected) | Target Epic |
|---|---|---|---|
| P0-1 | Path confinement | Setup: config with `project_id=../../escape` ; Trigger: `initialize_project()` ; Expected: `ValueError` before any disk access | Epic 1 |
| P0-2 | Pack trust | Setup: untrusted local pack in `.loopforge/packs` ; Trigger: `verify_run()` in non-interactive mode ; Expected: exit code ≠0, no check execution | Epic 1 |
| P0-3 | verify bypass | Setup: run in `task_draft` with all stages `pending` ; Trigger: `verify_run()` ; Expected: state unchanged, no commands executed | Epic 2 |
| P0-4 | success_checks without evidence | Setup: run with `success_checks=["Tests pass"]` but no check executed ; Trigger: `verify_run()` ; Expected: `verification_blocked`, missing evidence listed | Epic 2 |
| P0-5 | Infinite output + child processes | Setup: adapter that forks and writes in a loop ; Trigger: `verify_run()` with timeout ; Expected: output bounded, process tree killed, status ≠ `completed` | Epic 1 |
| P0-6 | TUI target vs mutation target | Setup: project with 2 runs, run B highlighted in TUI ; Trigger: Archive action ; Expected: confirmation names B, only B is mutated after revalidation | Epic 1 |
| P0-7 | Post-commit cancellation | Setup: operation that commits then raises `CancelledError` ; Trigger: `_operation_result()` ; Expected: status is `commit_started` or `completed`, never `cancelled` | Epic 1 |
| P0-8 | JSON on TTY | Setup: stdout attached to TTY ; Trigger: `loopforge run --json` ; Expected: first byte is `{`, all progress on stderr | Epic 1 |
| P0-9 | /raw path escape | Setup: `run.json` modified with `artifact_path=/etc/passwd` ; Trigger: `/raw <artifact>` ; Expected: refusal with confined resolution | Epic 1 |
| P0-10 | Orphaned run creation | Setup: nonexistent pack after worktree preparation ; Trigger: `create_run()` ; Expected: no orphaned run/worktree/index/pointer | Epic 2 |

---

## Step 5 — P0/P1/P2 Backlog Classification

Apply priority definitions:

- **P0:** data loss, unreliable execution, wrong target, gate bypass, incorrect machine output
- **P1:** incorrect behavior with user impact but no corruption/loss
- **P2:** UX polish, performance, documentation

Produce the full mapping in `docs/defect-priority-map.md` using the backlog from the hardening plan (lines 437–463 of `2026-07-22-001-refactor-loopforge-product-hardening-plan.md`).

---

## Step 6 — Update Contributor Commands

Update `docs/agent/06-build-test-run.md` and `CONTRIBUTING.md`:

```bash
python -m pip install -e ".[dev]"
python -m unittest
python -m compileall -q src
git diff --check
```

Include:
- Exact dependency versions tested (min/max)
- Non-regression policy: no test may be permanently marked `expectedFailure`

---

## Step 7 — Final Validation and Exit Gate

### Validation Commands

```bash
# 1. Green suite, two consecutive runs
python -m unittest && python -m unittest

# 2. Clean compilation
python -m compileall -q src

# 3. Whitespace
git diff --check

# 4. Textual tests on min AND max supported version
pip install textual==8.0.0 && python -m unittest tests.test_cli_textual_app
pip install "textual<9" && python -m unittest tests.test_cli_textual_app

# 5. Verify all supported launchers respond to --help
for f in .agent/checks/*.py; do python "$f" --help 2>&1; done
```

### Exit Gate Checklist

- [ ] Supported suite is green and non-flaky across 2 consecutive runs
- [ ] Every P0 has a reproducer, owner, target epic, and acceptance condition documented
- [ ] No support document references a missing command as executable
- [ ] License, non-Git, and install decisions recorded
- [ ] Supported surface matrix published
- [ ] `.agent/` launchers classified and tested (minimum `--help` for supported ones)
- [ ] Final comment on issue #26 listing commands, versions, outcomes, and PR links

---

## Execution Timeline (1–2 weeks)

| Week | Steps | Deliverables |
|---|---|---|
| W1 | D1–D5 (blocking decisions), 2.1–2.2 (fix 3 tests) | Green baseline, decisions document |
| W1–W2 | 3 (surface matrix), 4 (regression matrix), 5 (backlog classification) | Complete matrices |
| W2 | 6 (update contributor docs), 7 (gate validation) | Merged PRs, commented issue #26 |

---

## Test Plan

### Automated Tests (manual CI for now)

| Test | Command | Frequency | Success Criterion |
|---|---|---|---|
| Full suite | `python -m unittest` | Every commit | 229+ tests, 0 failures |
| Compilation | `python -m compileall -q src` | Every commit | No errors |
| Whitespace | `git diff --check` | Every commit | No errors |
| Textual min | `pip install textual==8.0.0 && python -m unittest tests.test_cli_textual_app` | Pre-merge | Green |
| Textual max | `pip install "textual<9" && python -m unittest tests.test_cli_textual_app` | Pre-merge | Green |
| Launcher smoke | `for f in .agent/checks/*.py; do python $f --help 2>&1; done` | Pre-merge | Exit 0 for each supported launcher |

### Manual Tests

| Test | Procedure | Success Criterion |
|---|---|---|
| Wheel + smoke from scratch | `pip install dist/*.whl` in a clean venv → `loopforge version`, `loopforge pack list`, `loopforge doctor` | Every command works without looking for `src/loopforge` |
| Double consecutive run | `python -m unittest` twice | Identical result (no flaky tests) |
| P0 reproducers | Run each reproducer from the regression matrix | Reproducible failure (will be fixed in Epic 1/2) |

---

## Source References

- Architecture and modules: `docs/agent/01-modules.md`, `docs/agent/02-architecture.md`, `docs/agent/04-reuse-catalog.md`
- Coding patterns: `docs/agent/03-coding-patterns.md`
- Build and test: `docs/agent/06-build-test-run.md`
- Danger zones: `docs/agent/07-danger-zones.md`
- UX contracts: `docs/cli-ux-command-plan.md`
- Parent roadmap: `docs/plans/2026-07-22-001-refactor-loopforge-product-hardening-plan.md`