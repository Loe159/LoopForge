# Danger zones

## Public CLI contracts

Paths: `pyproject.toml`, `src/loopforge/cli.py`, `cli_app.py`,
`cli_parser.py`, `cli_models.py`, `cli_errors.py`.

`pyproject.toml` still points to `loopforge.cli:main`. The application
resolves helpers through the injected facade to preserve historical imports and
monkeypatches. Renaming or directly importing those helpers in handlers can
break compatibility even if manual commands still work.

Preserve command names/options/topics, the `interactive` alias, global-flag
placement before `--`, exit codes, single JSON payloads, CSV/table behavior,
and stdout/stderr separation. Run the full suite and
`tests/test_cli_structure.py` after changes.

## Engine state machine and persistent artifacts

Path: `src/loopforge/engine.py`.

The engine couples approval transitions, profile gates, run/workspace state,
memory, metrics, adapters, patch/risk/checks, review, and local draft
publication. A transition bug can bypass task/plan/review gates or make
verification look like publication authority.

The coupled persisted contract is `current_stage`, `stage_statuses`,
`human_gates`, and `publish_eligibility`. Preserve it through
`normalize_run_workflow_state` and the `apply_*_approval` helpers. In
particular, a passing `verify_run` must leave review pending and publication
ineligible until `approve_review` succeeds.

Read-only research/plan enforcement is detection-based: the engine snapshots
the workspace, blocks the stage when changes are observed, but does not restore
those changes automatically. Do not treat a blocked result as rollback; inspect
and recover the run workspace explicitly before continuing.

Use `write_json_atomic`, normalize historical records, isolate
`LOOPFORGE_HOME`, and test the changed transition plus the full suite and
`git diff --check`.

## Imported bootstrap contracts

Paths: `.agent/checks/`, `.agent/adapters/`, `.agent/policies/`,
`.agent/schemas/`, `.agent/templates/`, `.agent/prompts/`.

`engine.py` invokes these scripts/contracts for patch generation, diff/risk,
process isolation, adapter result validation, and legacy artifacts. Change
producer, policy/schema, and consumer together. Do not weaken shell
prohibitions, environment isolation, timeouts/capture, secret checks, or
network/publication result fields without an explicit product decision.

Uncertain inherited bindings: the disposable-worktree policy/check references
`prepare_disposable_worktree.py` and related preparation data that are absent;
`build_stage_context.py` references an absent `validate_prompts`. Verify
before using those inherited scripts directly.

## Packs and templates

Paths: `.loopforge/packs/`, `.loopforge/templates/`.

Packs are loaded dynamically, and a project-local pack overrides a bundled
homonym. Detection priority changes pack selection; checks and protected paths
change verification/risk. Keep JSON valid, commands shell-free, and test pack
list/detection plus relevant checks.

Native and legacy templates have frontmatter/section names consumed by parsers,
validators, and status. Migrate all producers, consumers, and tests together.

## Mutable project-local state

Paths: `.loopforge/config.json`, `.loopforge/memory.md`.

The tracked config contains mutable run id, timestamps, and a machine-specific
absolute run root. Avoid publishing accidental local-state churn. Durable
memory can be changed by `learn --approve`; never add secrets, credentials,
private provider text, or untrusted issue bodies.

## Process, network, and publication boundaries

Paths: `engine.py`, `cli.py`, `interactive.py`,
`.agent/adapters/`.

`continue` and pack checks execute local subprocesses. GitHub intake
explicitly calls local `git`/`gh`; it must retain the `agent:approved`
gate and untrusted-input treatment. Test with fixtures/mocks, not real
publication.

`prepare_draft_publication` writes only a local draft artifact after
verification and review approval. Do not add hidden push, PR creation,
deployment, telemetry, or network side effects.

The cockpit is the only current CLI path to plan approval, review approval,
and draft preparation (`cli.py`, `cli_workflow.py`). Preserve the condition
that `--no-input` reports state rather than crossing these gates.

## Machine output and optional terminal dependencies

Paths: `ui.py`, `cli.py`, `cli_app.py`, `interactive.py`.

Decorative output or progress on stdout breaks automation. Preserve no-input,
no-color, quiet, JSON/CSV, and debug behavior. The Rich/prompt_toolkit fallback
paths and dependency-complete paths both need focused tests when UI code
changes.

## Generated files

`src/loopforge.egg-info/`, `__pycache__/`, tool caches, `dist/`, and
`build/` are generated. Do not hand-edit or use them as the source of truth.
