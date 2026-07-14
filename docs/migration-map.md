# Migration Map From ABL Workflow

This document records what was copied, what was intentionally left behind, and
what must be refactored.

## Copied As Bootstrap Core

| Old path | New path | Why |
| --- | --- | --- |
| `.agent/checks/diff_policy.py` | `src/loopforge/checks/diff_policy.py` | Deterministic patch policy; old path is a launcher |
| `.agent/checks/generate_complete_patch.py` | `src/loopforge/checks/generate_complete_patch.py` | Complete Git patch generation; old path is a launcher |
| `.agent/checks/classify_patch_risk.py` | `src/loopforge/checks/classify_patch_risk.py` | Risk routing; old path is a launcher |
| `.agent/checks/validate_artifacts.py` | `src/loopforge/checks/validate_artifacts.py` | Portable artifact validation; old path is a launcher |
| `.agent/checks/check_stage_readiness.py` | `.agent/checks/check_stage_readiness.py` | Stage prerequisite checks |
| `.agent/checks/build_stage_context.py` | `.agent/checks/build_stage_context.py` | Read-only context bundle builder |
| `.agent/checks/initialize_portable_run.py` | `.agent/checks/initialize_portable_run.py` | Legacy portable run initialization |
| `.agent/checks/isolated_process.py` | `src/loopforge/checks/isolated_process.py` | Bounded child process primitive; old path is a launcher |
| `.agent/checks/record_run_metrics.py` | `.agent/checks/record_run_metrics.py` | Metrics record prototype |
| `.agent/adapters/local_implementation_adapter.py` | `src/loopforge/adapters/local_implementation_adapter.py` | First generic adapter wrapper; old path is a launcher |
| `.agent/adapters/*.sh` | `.agent/adapters/*.sh` | Agent CLI entrypoints |
| `.agent/templates/` | `src/loopforge/templates/legacy/` | Legacy portable artifacts |
| `.agent/prompts/` | `.agent/prompts/` | Read-only research/plan/review prompts |
| `.agent/schemas/implementation-result.schema.json` | `src/loopforge/contracts/schemas/implementation-result.schema.json` | Result schema used by the local adapter |

## Generalized During Copy

- `risk-rules.json` no longer names ABL parser paths.
- `diff-policy.json` now uses generic protected paths and test path patterns.
- `research.md` no longer routes ABL behavior to Proparse research.
- `prompt-contract.json` now points research at `.loopforge/skills/`.

## Reintroduced In General Form

- Task approval is now part of run creation: GitHub issues require the
  `agent:approved` label, and manual tasks require local confirmation.
- Read-only research and planning are now run-cockpit stages that write
  `research.md` and `plan.md` from adapter output.
- Plan approval gates implementation, and review approval is distinct from
  deterministic verification.
- Draft PR publication is a local deterministic artifact preparation step. It
  does not push, open a network PR, or treat receipts and metrics as authority.

## Left Behind For Now

- GitHub issue queue and snapshot ingestion.
- Disposable worktree lifecycle receipts.
- Supervised runner receipt validation chain.
- Historical golden set.
- Multi-adapter comparison validator.
- ABL-specific skills and docs.
- Extensive proof fixtures.

These are useful references, but they are too heavy for the first general
product milestone.

## Refactor Targets

1. Move remaining reusable Python code from `.agent/checks` into `loopforge.checks`.
2. Keep thin compatibility wrappers under `.agent/checks`.
3. Replace numeric `issue` with generic `task_id`.
4. Replace hard-coded policy equality checks with versioned product contracts.
5. Move policy fragments into project packs.
6. Add a CLI layer that hides low-level script choreography.
7. Build tests around product commands, not only individual guardrail scripts.

## Compatibility Rule

Do not delete `.agent/**` wholesale. The migrated active scripts are thin
compatibility wrappers; the remaining inherited material stays available until
it has a product-owned replacement.
