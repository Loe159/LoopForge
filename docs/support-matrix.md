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
| `--plain` | Compatible | 0.1.0 | Plain CLI output; interactive TTY sessions still open Textual |
| `shell --command` | Supported | 0.1.0 | Single-command execution |
| `shell --script` | Supported | 0.1.0 | Script file execution |
| Textual TUI | Supported | Textual >=8.0,<9 | Default for interactive TTY sessions |
| `--json` output | Supported | 0.1.0 | Machine-readable output, progress on stderr |
| `--quiet` output | Supported | 0.1.0 | Minimal output |

## `.agent/checks/` Launcher Classification

| Launcher | Classification | Rationale |
|---|---|---|
| `classify_patch_risk.py` | Compatibility | Wrapper around the packaged risk check |
| `diff_policy.py` | Compatibility | Wrapper around the packaged diff policy check |
| `generate_complete_patch.py` | Compatibility | Wrapper around packaged patch generation |
| `isolated_process.py` | Compatibility | Import-only shim, not a CLI |
| `validate_artifacts.py` | Compatibility | Wrapper around `loopforge.checks` |
| `validate_implementation_result.py` | Compatibility | Wrapper around `loopforge.checks` |

All CLI launchers must respond to `--help` with exit code 0. The import-only
`isolated_process.py` shim is checked by importing its packaged implementation.
The adapter launcher under `.agent/adapters/` follows the same rule; shell
adapters delegate to it.

The standalone `build_stage_context.py`, `check_stage_readiness.py`,
`initialize_portable_run.py`, `record_run_metrics.py`, and
`validate_disposable_worktree.py` prototypes were removed on September 21,
2026. They had no product callers and were not the engine's implementations.
Their policies, schemas, templates, and prompts were removed with them.

## Engine API Boundaries

| Surface | Status | Notes |
|---|---|---|
| `loopforge.cli:main` | Supported | Stable public entry point |
| `loopforge.engine` module | Supported | Internal API; versioned through CLI contract |
| `loopforge.checks` module | Supported | Process isolation and validation |
| `loopforge.packs` module | Supported | Pack detection and resolution |
| `loopforge.templates` module | Supported | Template rendering |
