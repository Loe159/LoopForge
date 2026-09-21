# Repository layout

LoopForge has one product implementation and one documentation tree.

| Path | Purpose |
| --- | --- |
| `src/loopforge/` | Packaged Python product: CLI, Textual TUI, engine, adapters, checks, contracts, packs, templates |
| `tests/` | Executable unit, integration, and Textual Pilot tests and their fixtures |
| `docs/` | Maintained documentation, dated plans, decisions, benchmarks, and audit reports |
| `tools/` | Developer utilities such as the TUI benchmark |
| `.agent/checks/`, `.agent/adapters/` | Thin compatibility entry points delegating to the packaged product |
| `.github/` | GitHub issue templates |
| `.impeccable/` | Versioned Impeccable tooling configuration and derived design metadata; `DESIGN.md` remains the design source of truth |
| `.git/` | Git history and repository metadata; never delete as cleanup |

`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `DESIGN.md`, and `PRODUCT.md`
are the root entry points for use, contribution, agent rules, design, and
product direction. `pyproject.toml` declares the Python package and dependencies.

## Local directories are not product sources

- `.loopforge/` stores this checkout's project identity, selected adapter,
  current run pointer, memory, and optional overrides. Deleting it is a project
  reset, not a harmless source cleanup. It is ignored in this repository;
  fixtures under `tests/` are unaffected by the root-only ignore rule.
- `.venv/` is the local Python environment, ignored by Git.
- `.idea/` contains local IDE settings and may include shelved uncommitted
  changes. It is ignored and no longer versioned; existing files and shelved
  changes are preserved on disk.
- `__pycache__/` and `*.egg-info/` are generated Python files, not sources.

Run data and workspaces belong outside the repository, under `LOOPFORGE_HOME`
or the platform data directory. Test runs use temporary directories.

## Removed structure

- `doc/`: exact duplicate of `docs/agent/08-flows.md`; keep only `docs/`.
- `qa/agentic-e2e/`: historical specifications for an unimplemented campaign
  runner, not executable QA coverage. Current tests live in `tests/`; the
  remaining E2E coverage gap is still tracked by issue #44.
- `legacy/`, `policies/`, `schemas/`, `.agents/`, `.codex/`, and `$`: empty
  directories. Product policies and schemas are in `src/loopforge/contracts/`.
- `.agent` bootstrap scripts and duplicate data: no runtime callers in the
  product; retain only the compatibility launchers exercised by tests.
- `agent.md`: obsolete prototype contract, not an entry point; use `AGENTS.md`
  and the packaged workflow contracts.
- `node_modules/`: unused vendored SQL.js files, with no Node project or runtime
  dependency. Python dependencies are declared in `pyproject.toml`.
- `artifacts/`: historical local campaign output, moved outside the checkout.

Historical plans and audit reports describe the layout at their publication
date; they are not instructions to recreate retired paths.

The September 21 structural cleanup first archived the actual working-tree
contents, including local modifications, outside the repository. Recovery
details and final validation are recorded in the cleanup audit report.

At the user's request, `.impeccable/` was restored from that backup and remains
versioned. Its metadata was not regenerated as part of the cleanup.
