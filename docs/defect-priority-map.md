---
title: "LoopForge Defect Priority Map"
type: defect-priority-map
date: 2026-07-23
topic: epic0-green-baseline
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/26
artifact_contract: defect-priority-map/v1
artifact_readiness: final
---

# Defect Priority Map

Each known defect from the hardening plan is classified according to the
LoopForge priority scale. P0 items are scheduled for Epic 1; P1 for Epic 2;
P2 for Epics 3-5.

## Priority Scale

| Priority | Definition |
|---|---|
| P0 | Data loss, unreliable execution, wrong target, gate bypass, incorrect machine output |
| P1 | Incorrect behavior with user impact but no corruption or loss |
| P2 | UX polish, performance, documentation |

## Classification Table

| # | Defect | Priority | Target Epic | Rationale |
|---|---|---|---|---|
| 1 | Snapshot workspace: `LOOPFORGE_HOME` placed in project counts as workspace modification; no-op adapter can be classed `completed`. | P1 | Epic 2 | Incorrect behavior (spurious modifications, false completion) but no data loss or corruption. |
| 2 | Project switch: `select_project()` changes path without atomically reloading adapter and arguments; `/cd` may leave store on old project. | P1 | Epic 2 | User-visible incorrect state after project switch; no corruption or loss of persisted data. |
| 3 | Adapter settings: switching adapter retains arguments from old adapter when no new arguments provided. | P1 | Epic 2 | Incorrect argument propagation with user impact; no loss or corruption. |
| 4 | Shell init: `/init` ignores a `project_id` registration conflict that the top-level refuses. | P1 | Epic 2 | Inconsistent enforcement between shell and top-level init; no data loss. |
| 5 | Shell parsing: slash parsers use `sys.stderr` directly; argument errors and functional refusals bypass shell streams. | P1 | Epic 2 | Error output routed incorrectly, user misses diagnostics; no corruption. |
| 6 | Operation errors: worker exception is retained but TUI poll only shows operation label. | P1 | Epic 2 | Degraded error visibility for users; no data corruption or loss. |
| 7 | Guided actions: `inspect-verification`, `approve-memory`, `inspect-attempt`, `retry-verify`, `compact`, `review` can be displayed without an executor. | P1 | Epic 2 | Actions shown when non-functional, misleading to user; no corruption. |
| 8 | Fork: `/fork` only copies pack and `success_checks`, not skills, permissions, rubric, source, or announced limits. | P1 | Epic 2 | Fork contract is incomplete, user gets an incomplete clone; no loss of original data. |
| 9 | Archive: archive retains `current_run_id` on an archived run, keeping an unexpected current target. | P1 | Epic 2 | Incorrect focus after archival; no data destruction. |
| 10 | Git worktree: `GitStateService` does not correctly track `commondir`; `head` can be `None` in a real worktree. | P1 | Epic 2 | Incorrect Git state in worktree context, affects verification; no data loss. |
| 11 | Pack discovery: malformed pack is silently ignored and can cause unexpected fallback. | P1 | Epic 2 | Silent degradation path, user unaware of fallback; no corruption. |
| 12 | JSON checks: timeout or missing executable in `run_json_check()` does not uniformly become blocked evidence. | P1 | Epic 2 | Inconsistent check behavior, evidence may pass when it should block; no data loss. |
| 13 | Metrics contract: extractors look for `model`, `tokens`, `cost` but result contract rejects these extra fields. | P1 | Epic 2 | Schema mismatch produces incorrect metrics output; no data loss. |
| 14 | Non-Git: `shared-checkout` mode accepts work but verification later requires `base_commit`. | P1 | Epic 2 | Inconsistent gating, user starts work that later fails on missing base; no corruption. |
| 15 | Screen state: project filter reused on runs, Settings always returns to Run, recent runs are decorative. | P2 | Epic 3 | UX polish: navigation state restoration and screen separation. |
| 16 | Evidence viewer: preview without pagination, non-virtualized lists, export flattens names with possible overwrite. | P2 | Epic 4 | Performance and UX: rendering performance for large lists plus export safety. |
| 17 | Accessibility: `LOOPFORGE_ASCII`, no-color, and mono do not match documented behavior. | P2 | Epic 3 | UX polish: terminal capability handling does not honor user preferences. |
| 18 | Context commands: `/add-dir`, `/mention`, `/title` are cosmetic only; keymap does not reconfigure existing session. | P2 | Epic 3 | UX polish: commands advertised but non-functional. |
| 19 | Permissions: `/permissions` displays hardcoded catalog instead of effective pack contract. | P2 | Epic 3 | UX polish: displayed permissions do not reflect runtime reality. |
| 20 | Diff: `/diff` returns success when Git is unavailable. | P2 | Epic 3 | UX polish: misleading success on a failed operation. |
| 21 | TUI idle: 120ms timer remains active at rest despite documented idle budget. | P2 | Epic 4 | Performance: unnecessary polling wastes CPU contrary to spec. |
| 22 | Versioning: version is duplicated and major bounds of `prompt_toolkit` and `rich` are not pinned. | P2 | Epic 5 | Documentation and dependency hygiene; no runtime defect. |
| 23 | Diagnostics: top-level `doctor` and `/doctor` test different things. | P2 | Epic 3 | UX polish: divergent behavior between CLI and TUI diagnostics. |
| 24 | Legacy launchers: four `.agent/checks/` launchers break before `--help` due to missing imports. | P2 | Epic 5 | Documentation and cleanup: classify, repair supported perimeter, archive rest. |
| 25 | Bug reporting: `version` exposes paths that the template asks not to publish. | P2 | Epic 5 | Documentation and safety: version output leaks paths against reporting guidance. |

## Epic Assignment

| Epic | Priorities | Focus |
|---|---|---|
| Epic 1 | P0 | Critical hardening: path confinement, process isolation, TUI safety |
| Epic 2 | P1 | Lifecycle robustness: state machines, verification, orphan prevention |
| Epic 3 | P2 (UX) | Command ergonomics, output formatting |
| Epic 4 | P2 (Performance) | Startup time, rendering performance |
| Epic 5 | P2 (Docs) | Documentation, examples, contributor guides |