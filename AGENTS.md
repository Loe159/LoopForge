# LoopForge Agent Rules

LoopForge is a general-purpose agentic workflow engine. Keep the project
portable, ergonomic, and honest about autonomy.

## Direction

- Prefer a small working CLI over a large policy framework.
- Keep reusable engine code separate from project-specific packs.
- Treat imported `.agent/**` files as bootstrap core until they are refactored
  into the LoopForge package.
- Preserve deterministic checks for patch generation, risk classification,
  process isolation, artifacts, and metrics.
- Do not turn receipts, validation, or metrics into publication authority.

## Before coding

- Read `docs/agent/01-modules.md`, `docs/agent/03-coding-patterns.md`, and
  `docs/agent/04-reuse-catalog.md` before creating code.
- Reuse the engine APIs, CLI handlers/parser/models/errors, UI helpers, pack
  loaders, atomic JSON helpers, and imported deterministic checks. Do not
  duplicate them.
- Follow `docs/agent/05-how-to-add-feature.md`; commands are in
  `docs/agent/06-build-test-run.md`; sensitive contracts are in
  `docs/agent/07-danger-zones.md`.

## Architecture

- `agent.md`: operator-facing system contract.
- `docs/agent/00-overview.md`: repository and runtime orientation.
- `docs/agent/01-modules.md`: module map and extension points.
- `docs/agent/02-architecture.md`: current runtime and data flows.
- `src/loopforge/cli.py`: public compatibility facade; keep
  `loopforge.cli:main` stable.
- `src/loopforge/cli_app.py`: application context and command handlers.
- `src/loopforge/engine.py`: reusable workflow behavior and persistence.
- Lifecycle changes must use `normalize_run_workflow_state` and engine
  transition APIs; verification does not replace review approval.
- `.loopforge/templates/`: product templates for loop, memory, scratch, and
  exchange files.
- `.loopforge/packs/`: project-specific rules and verification adapters.
- `.loopforge/skills/`: home for reusable task skills; currently only the
  planned catalog in `README.md` is present.
- `.agent/`: imported bootstrap implementation from the ABL workflow.

## Change Rules

- Keep imported scripts runnable while refactoring.
- Add focused tests when changing Python behavior.
- Avoid hidden network, publication, or destructive filesystem actions.
- Keep generated run artifacts outside the repository by default.
- Preserve unrelated working-tree changes.

## Required validation

- From the repository root, run `python -m unittest` and
  `git diff --check` for Python/CLI changes.
- Add focused `unittest` coverage for changed behavior.
- Use `tests/test_cli_structure.py` for facade/parser/dispatch changes and
  `tests/test_engine_services.py` for JSON, packs, or metrics services.
- Ruff and pytest are not required until their development dependencies and
  canonical commands are documented.
