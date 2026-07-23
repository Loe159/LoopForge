---
title: "LoopForge Supported Surface Matrix"
type: support-matrix
date: 2026-07-23
topic: epic0-green-baseline
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/26
artifact_contract: support-matrix/v1
artifact_readiness: final
---

# LoopForge Supported Surface Matrix

Classifies every user-facing entry point for LoopForge v1. Only entries marked
**Supported** or **Compatible** are covered by the regression suite.

## CLI Surfaces

| Surface | Status | Tested version | Notes |
|---|---|---|---|
| Top-level CLI (`loopforge <cmd>`) | Supported | 0.1.0 | |
| `--plain` | Compatible | 0.1.0 | No TUI, headless operation |
| `shell --command` | Supported | 0.1.0 | Single-command execution |
| `shell --script` | Supported | 0.1.0 | Script file execution |
| Textual TUI | Supported | Textual >=8.0,<9 | Default for interactive TTY sessions |
| `--json` output | Supported | 0.1.0 | Machine-readable output, progress on stderr |
| `--quiet` output | Supported | 0.1.0 | Minimal output |

## `.agent/checks/` Launcher Classification

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

Supported launchers must respond to `--help` with exit code 0.
Compatibility-only launchers are exempt from the `--help` smoke test.

## Engine API Boundaries

| Surface | Status | Notes |
|---|---|---|
| `loopforge.cli:main` | Supported | Stable public entry point |
| `loopforge.engine` module | Supported | Internal API; versioned through CLI contract |
| `loopforge.checks` module | Supported | Process isolation and validation |
| `loopforge.packs` module | Supported | Pack detection and resolution |
| `loopforge.templates` module | Supported | Template rendering |