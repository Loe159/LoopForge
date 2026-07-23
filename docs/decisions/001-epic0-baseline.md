---
title: "Epic 0 — Blocking Decisions"
type: decision-record
date: 2026-07-23
topic: epic0-green-baseline
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/26
artifact_contract: decision-record/v1
artifact_readiness: final
---

# Epic 0 — Blocking Decisions

Decisions recorded as part of Epic 0: Stop the Line. These were resolved before
any code changes.

## D1 — License

- **Decision:** MIT
- **Rationale:** Maximizes adoption, compatible with the Python ecosystem,
  minimal restrictions. LoopForge is a developer tool intended for broad reuse.
- **Action:** Add `LICENSE` file (MIT) to the repository root.

## D2 — Non‑Git Projects

- **Decision:** Refuse early in v1 with a clear message, plus a v2 enhancement
  ticket.
- **Rationale:** LoopForge depends on Git for workspace snapshots, diff
  generation, and patch creation. Supporting non‑Git projects requires a
  real snapshot backend that is out of scope for v1.
- **Action:** Ensure `initialize_project()` and `verify_run()` gate on
  `git rev-parse --show-toplevel` and produce a user‑friendly error
  referencing the v2 ticket. Create the v2 ticket on GitHub.

## D3 — `install` / `update` Commands

- **Decision:** Redefine without the `git pull` assumption.
- **Rationale:** The current commands assume a cloned Git repository for
  self‑update, which is incompatible with pip‑installed distributions. The
  commands must be redesigned to work with pip or PyPI without self‑modification
  risk.
- **Action:** Redesign `install` and `update` to delegate to `pip install
  --upgrade loopforge` (or equivalent). Document the new behavior.

## D4 — Divergent CLI Assertions (Prompt Artifact Paths)

- **Decision:** Embed artifact content inline in prompts rather than
  exposing absolute filesystem paths.
- **Rationale:** Absolute paths are a security leak per risk R34 (information
  disclosure). Inline content keeps prompts self‑contained and portable.
- **Action:** Update the prompt‑generation code to embed artifact content
  instead of writing absolute paths. Update the corresponding test assertions
  (`test_run_cockpit_executes_plan_with_fixture_adapter`) to verify inline
  content.

## D5 — No‑op Adapter + `LOOPFORGE_HOME` Inside Project

- **Decision:** Exclude the real runtime root (`LOOPFORGE_HOME`,
  `.loopforge/`) from workspace snapshots.
- **Rationale:** The runtime storage directory should never appear in
  snapshots, patches, or prompts. It contains internal state that must
  remain isolated from the project workspace.
- **Action:** Update snapshot/workspace logic to filter out
  `LOOPFORGE_HOME` and `.loopforge/` paths. Classify the no‑op adapter
  correctly (supported when `--adapter` is omitted).