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

Effective pack contracts also compose `extends`, skills directories, agents,
permission sets, and workflow stages (`engine/packs.py` and
`packs/generic-code/`). A UI that displays a stage, actor, or permission must
use the hydrated effective contract; a second hard-coded catalog can become
incorrect when a child or project-local pack overrides data.

## Project identity and external run roots

**Path:** `src/loopforge/engine/__init__.py` (`project_name`,
`default_run_root`, `default_workspace_root`, `new_config`, `list_runs`,
`resume_run`).

External data is currently keyed by project directory basename. Changing this
layout can orphan existing runs, collide same-named repositories, or make
`current_run_id` point at a different root. Any project registry/id migration
must be non-destructive, preserve legacy discovery, cover moved/cloned
projects, and test two repositories with the same basename.

## Interactive rendering and duplicated command paths

**Paths:** `src/loopforge/cli/ui.py`, `interactive.py`, `app.py`, `workflow.py`,
and `tests/test_cli.py`.

The shell combines a `prompt_toolkit` prompt with Rich output and has a second
`cmd_*` dispatch surface. Top-level and slash commands do not always use the
same orchestration (`run` is the clearest example). A full-screen TUI can
flicker, corrupt scrollback, break redirected output, or diverge from CLI
behavior if it adds another renderer/action implementation. Preserve headless
`--command`/`--script`, JSON/CSV/plain behavior, TTY detection, confirmation
rules, Ctrl-C semantics, and semantic no-color fallbacks.

## External effects and generated files

Git, `gh`, agent executables, and local adapters are process boundaries.
`prepare_draft_publication` must remain local-only. Avoid hidden network,
push, PR creation, or destructive behavior. Do not edit
`src/loopforge.egg-info/`, `__pycache__/`, `build/`, or `dist/`; they are
generated. Validate with `python -m unittest` and `git diff --check`.
