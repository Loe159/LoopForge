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
- Runtime dependencies are `textual`, `prompt_toolkit`, and `rich`
  (`pyproject.toml`).
- Interactive TTY sessions open the Textual full-screen console by default
  (`cli/tui.py`). `shell --command` and `--script` remain headless;
  `--plain` uses the prompt-based compatibility surface.
- Tests are `unittest` suites under `tests/`; no database, HTTP server,
  container definition, Makefile, or GitHub Actions workflow was found.
- `.github/` contains an issue template only. Release/deployment automation is
  therefore not documented by repository evidence.

## Layout

| Path | Current role |
| --- | --- |
| `src/loopforge/cli/` | CLI facade, parser, handlers, shared presentation/actions, TUI, evidence, operations, and rendering |
| `src/loopforge/engine/` | Workflow API plus JSON storage, project registry, pack registry, and metrics service |
| `src/loopforge/checks/`, `adapters/` | Packaged deterministic checks and local implementation adapter |
| `src/loopforge/contracts/`, `packs/` | Policies/schemas and bundled packs with skills, agents, permissions, workflows, checks, and protected paths |
| `.agent/` | Compatibility launchers for migrated scripts and remaining inherited bootstrap material |
| `tests/` | CLI integration, CLI-boundary, and engine-service coverage |
| `docs/agent/` | Maintained audit and future-agent instructions |

## Runtime data

Projects hold `.loopforge/config.json` and `.loopforge/memory.md`.
`LOOPFORGE_HOME` redirects external run/workspace data; otherwise the engine
uses platform-aware locations (`loopforge_home` in `engine/__init__.py`).
Project-local packs under `.loopforge/packs/` override bundled packs in
`src/loopforge/packs/`.

Each configuration has a generated `project_id`. `engine/projects.py` stores
registered project metadata under `LOOPFORGE_HOME`; run and workspace roots are
keyed by that id. Legacy basename-keyed roots are migrated non-destructively by
the engine. `projects`, `open`, and `runs --all-projects` expose global views.

## Generated and uncertain material

`src/loopforge.egg-info/`, `__pycache__/`, `build/`, and `dist/` are generated
or ignored. In particular, the existing `egg-info/SOURCES.txt` still lists the
former flat module paths and is not source of truth after the package refactor.
Some non-migrated `.agent/checks/` scripts import helpers absent from this
repository; they are not established runtime paths.
