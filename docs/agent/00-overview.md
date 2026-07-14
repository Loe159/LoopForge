# Repository overview

## Purpose

LoopForge is a local, CLI-first engine for bounded agentic workflows. A run
moves from intake through read-only research and planning, approved
implementation, deterministic verification, explicit review, and preparation
of a local draft-publication artifact. Verification is evidence; it does not
approve review or authorize publication. See `README.md`, `agent.md`, and
`src/loopforge/engine.py`.

## Technology

- Python 3.11 or newer with a `src/` package layout
  (`pyproject.toml`, `src/loopforge/`).
- Public console entry point: `loopforge = loopforge.cli:main`.
- Runtime dependencies: `prompt_toolkit>=3.0` and `rich>=13.0`; the UI and
  shell retain reduced fallbacks when they are unavailable
  (`src/loopforge/ui.py`, `src/loopforge/interactive.py`).
- File-backed persistence using JSON and Markdown. No database, HTTP server,
  container definition, or CI workflow is present in the repository.
- Tests use `unittest` in `tests/test_cli.py`,
  `tests/test_cli_structure.py`, and `tests/test_engine_services.py`. Ruff
  and pytest have small configuration sections in `pyproject.toml`, but no
  canonical command or development dependency is documented for either.

## Repository structure

| Path | Purpose |
| --- | --- |
| `src/loopforge/` | Product package: CLI facade, parser, application handlers, engine, interactive shell, and terminal UI |
| `.loopforge/templates/` | Native run templates for loop, memory, scratch, and exchange artifacts |
| `.loopforge/packs/` | Bundled generic-code, Python, Node, documentation, and IntelliJ project packs |
| `.loopforge/skills/README.md` | Planned skill catalog; it is not an implemented reusable skill library yet |
| `.agent/` | Imported ABL bootstrap checks, policies, adapters, schemas, prompts, and legacy templates |
| `tests/` | Integrated CLI/engine/shell coverage and focused modular-CLI contracts |
| `docs/` | Product architecture, migration records, plans, and this agent-facing audit |

## Entry points and runtime data

- `loopforge.cli:main` is the installed entry point. It delegates to
  `LoopForgeCli` in `src/loopforge/cli_app.py`.
- `loopforge shell` and the `interactive` alias load
  `src/loopforge/interactive.py` lazily.
- Project configuration and durable memory live in
  `.loopforge/config.json` and `.loopforge/memory.md`.
- Runs default to
  `$LOOPFORGE_HOME/runs/<project>/<run-id>`, an existing
  `~/LoopForge`, or the platform data directory. Worktrees use the matching
  external `workspaces/<project>/` root
  (`loopforge_home`, `default_run_root`, and
  `default_workspace_root` in `src/loopforge/engine.py`).
- `.gitignore` excludes virtual environments, Python/tool caches,
  `dist/`, `build/`, `*.egg-info/`, and local run/artifact directories.
  Treat `src/loopforge.egg-info/` as generated packaging output.

## Current CLI refactor

The application dispatch, parser, shared models, and public error types are now
split into `cli_app.py`, `cli_parser.py`, `cli_models.py`, and
`cli_errors.py`. The public `cli.py` file remains a substantial
compatibility facade: it still owns GitHub/manual intake, global-option
preparsing, table/format helpers, payload builders, cockpit rendering, and
historical monkeypatch lookup points. Future extraction should preserve those
lookup points or replace them with explicit injected interfaces and migration
tests.

A second extraction isolates `JsonStore`, `PackRegistry`, and
`MetricsService` behind the engine's existing public functions. The CLI now
also has dedicated context, GitHub, intake, and workflow-handler modules.
Those wrappers deliberately preserve the existing `loopforge.engine` and
`loopforge.cli` function contracts while the large facades are reduced
incrementally.

## Current workflow contract

`run.json` now records both a coarse `status` and normalized workflow state:
`current_stage`, `stage_statuses`, `human_gates`, and
`publish_eligibility` (`src/loopforge/engine.py`). The stages are task,
research, plan, implementation, verification, review, and publication.
Research and planning are read-only adapter stages; plan approval gates
implementation, review approval gates local draft preparation, and neither
verification nor metrics authorizes network publication.

## Known uncertainties

- `pyproject.toml` has no explicit `[build-system]`; do not infer a wheel
  backend or release workflow.
- `.github/` contains an issue template but no workflow definition. CI status,
  release automation, and deployment shape are therefore not visible in this
  repository.
- Some inherited bootstrap scripts reference absent helpers:
  `.agent/checks/build_stage_context.py` imports `validate_prompts`, while
  `.agent/checks/validate_disposable_worktree.py` imports
  `prepare_disposable_worktree`. They are not on the main observed CLI path,
  but autonomous use of those scripts is uncertain.
- Read-only research and plan execution currently accepts the deterministic
  `local-adapter-fixture` path in `execute_readonly_stage`; broader product
  plans should not be mistaken for implemented adapter support there.
