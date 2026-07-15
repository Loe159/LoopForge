# LoopForge Agent Rules

LoopForge is a local, CLI-first Python workflow engine. Preserve bounded
autonomy: verification is evidence, never review or publication authority.

## Before coding

- Read `docs/agent/01-modules.md`, `03-coding-patterns.md`, and
  `04-reuse-catalog.md`.
- Before shell, terminal rendering, project navigation, or command UX work,
  read `docs/cli-ux-command-plan.md`.
- Reuse the public `loopforge.cli` facade, engine APIs, `CliContext`, handlers,
  `JsonStore`, `PackRegistry`, `MetricsService`, UI helpers, and packaged
  checks. Do not create parallel variants.
- Follow `05-how-to-add-feature.md`; commands are in `06-build-test-run.md`;
  sensitive contracts are in `07-danger-zones.md`.

## Boundaries

- Keep `loopforge.cli:main` stable. The facade is
  `src/loopforge/cli/__init__.py`; handlers live in `src/loopforge/cli/`.
- Keep one behavior path across top-level commands and slash commands. Reuse
  the renderer, workflow progress, guidance, and effective pack contract; do
  not add another command registry or live renderer.
- `src/loopforge/engine/__init__.py` owns workflow state. Use its normalizers
  and approval APIs; do not patch lifecycle fields from CLI code.
- Product checks, adapters, policies, schemas, templates, and bundled packs
  belong under `src/loopforge/`. `.agent/` contains compatibility launchers and
  inherited bootstrap material; keep launchers runnable.
- Do not add hidden network, publication, telemetry, or destructive behavior.
- Preserve unrelated working-tree changes and keep generated run artifacts
  outside the repository by default.

## Validation

For Python or CLI changes, run from the repository root:

```text
python -m unittest
git diff --check
```

Use `tests/test_cli_structure.py` for CLI boundaries and
`tests/test_engine_services.py` for storage, pack, metrics, and packaged-runtime
services. `src/loopforge.egg-info/` and `__pycache__/` are generated files.
