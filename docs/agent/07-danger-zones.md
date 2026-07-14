# Danger zones

## Public CLI compatibility

**Paths:** `pyproject.toml`, `src/loopforge/cli/__init__.py`, `cli/app.py`,
`cli/parser.py`, `cli/models.py`, `cli/errors.py`.

`pyproject.toml` exposes `loopforge.cli:main`; the application deliberately
resolves dependencies through the injected facade. Changing re-exports, global
flag handling, parser topics/options, exit codes, or stdout/stderr discipline
can break scripts and monkeypatch-based tests. Run the full suite and
`tests/test_cli_structure.py`.

## Persisted workflow and artifacts

**Path:** `src/loopforge/engine/__init__.py`.

The engine couples approvals, workspace data, memory, adapters, verification,
metrics, and local draft preparation. Keep `current_stage`, `stage_statuses`,
`human_gates`, and `publish_eligibility` normalized together. In particular,
verification must leave review pending and publication ineligible. Use atomic
JSON writes and test state plus artifacts with isolated `LOOPFORGE_HOME`.

## Process isolation and deterministic contracts

**Paths:** `src/loopforge/checks/`, `adapters/`, `contracts/`, and matching
`.agent/checks/`/`.agent/adapters/` launchers.

These modules enforce process environment, patch/risk policy, output limits,
and adapter-result validation. Change producers, policies/schemas, consumers,
and compatibility launchers together. Do not weaken shell prohibition,
timeouts, capture limits, secret checks, or network/publication fields without
an explicit product decision.

## Packs and templates

**Paths:** `src/loopforge/packs/`, `src/loopforge/templates/`, and project
`.loopforge/packs/`.

Pack detection changes selected skills/checks/risk. A project-local homonym
overrides a bundled pack. Template names, frontmatter, and headings are parsed
by engine/check modules, so migrate producers, consumers, and tests together.

## External effects and generated files

Git, `gh`, agent executables, and local adapters are process boundaries.
`prepare_draft_publication` must remain local-only. Avoid hidden network,
push, PR creation, or destructive behavior. Do not edit
`src/loopforge.egg-info/`, `__pycache__/`, `build/`, or `dist/`; they are
generated. Validate with `python -m unittest` and `git diff --check`.
