# Repository overview

## Purpose

LoopForge is a local Python CLI for bounded agentic workflow runs. A run moves
from approved intake through read-only research and planning, implementation,
deterministic verification, explicit review, and preparation of a local draft
artifact. The persisted workflow and its approval gates live in
`src/loopforge/engine/__init__.py`.

## Inventory

- Python 3.11+ package in `src/loopforge/`; project metadata and the console
  entry point are in `pyproject.toml`.
- `loopforge = loopforge.cli:main`; the public facade is
  `src/loopforge/cli/__init__.py`.
- Runtime dependencies are `prompt_toolkit` and `rich` (`pyproject.toml`),
  both with reduced fallbacks in the CLI UI/shell.
- The interactive registry currently contains 64 supported slash commands and
  30 recognized unsupported names (`src/loopforge/cli/interactive.py`). The
  shell is a `PromptSession` REPL with a Rich-aware renderer, not a full-screen
  multi-project application.
- Tests are `unittest` suites under `tests/`; no database, HTTP server,
  container definition, Makefile, or GitHub Actions workflow was found.
- `.github/` contains an issue template only. Release/deployment automation is
  therefore not documented by repository evidence.

## Layout

| Path | Current role |
| --- | --- |
| `src/loopforge/cli/` | CLI facade, parser, command handlers, interactive shell, intake, and rendering |
| `src/loopforge/engine/` | Workflow API plus JSON storage, pack registry, and metrics service |
| `src/loopforge/checks/`, `adapters/` | Packaged deterministic checks and local implementation adapter |
| `src/loopforge/contracts/`, `templates/`, `packs/` | Policies/schemas, legacy templates, and bundled packs with skills, agents, permissions, workflows, checks, and protected paths |
| `.agent/` | Compatibility launchers for migrated scripts and remaining inherited bootstrap material |
| `tests/` | CLI integration, CLI-boundary, and engine-service coverage |
| `docs/agent/` | Maintained audit and future-agent instructions |

## Runtime data

Projects hold `.loopforge/config.json` and `.loopforge/memory.md`.
`LOOPFORGE_HOME` redirects external run/workspace data; otherwise the engine
uses platform-aware locations (`loopforge_home` in `engine/__init__.py`).
Project-local packs under `.loopforge/packs/` override bundled packs in
`src/loopforge/packs/`.

Run and workspace roots currently use only `project_dir.name`
(`default_run_root`/`default_workspace_root` in `engine/__init__.py`). There is
no global project registry, and `list_runs`/`dashboard_snapshot` inspect only
the current project. This is a concrete limitation for same-named repositories
and a multi-project shell.

## Generated and uncertain material

`src/loopforge.egg-info/`, `__pycache__/`, `build/`, and `dist/` are generated
or ignored. In particular, the existing `egg-info/SOURCES.txt` still lists the
former flat module paths and is not source of truth after the package refactor.
Some non-migrated `.agent/checks/` scripts import helpers absent from this
repository; they are not established runtime paths.
