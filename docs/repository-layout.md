# Repository layout

LoopForge keeps the product, tests, and maintained documentation in a small set of explicit directories.

| Path | Purpose |
| --- | --- |
| `src/loopforge/` | Packaged Python product: CLI, Textual TUI, engine, adapters, checks, contracts, packs, templates |
| `tests/` | Executable unit, integration, regression, E2E, and Textual Pilot coverage plus fixtures |
| `docs/` | Maintained architecture, support, contributor, active roadmap, and decision documentation |
| `tools/` | Developer utilities and benchmarks |
| `.agent/checks/`, `.agent/adapters/` | Thin compatibility entry points delegating to the packaged product |
| `.github/` | GitHub metadata and issue templates |
| `.impeccable/` | Versioned Impeccable configuration and derived design metadata |

Root entry points:

- `README.md`: install, use, and understand LoopForge.
- `CONTRIBUTING.md`: contributor workflow.
- `AGENTS.md`: repository rules for coding agents.
- `DESIGN.md`: interface and design source of truth.
- `PRODUCT.md`: product direction.
- `pyproject.toml`: Python package and dependency definition.

## Local state

These directories are not product sources and must not be committed:

- `.loopforge/`: project-local identity, configuration, memory, and current run pointer.
- `.venv/`: local Python environment.
- `.idea/`: local IDE configuration.
- `__pycache__/`, `*.egg-info/`: generated Python artifacts.

Run data and workspaces live outside the checkout under `LOOPFORGE_HOME` or the platform data directory. Tests use temporary directories.

## Cleanup rule

Do not keep placeholder tests, duplicate compatibility implementations, generated artifacts, completed implementation plans, or historical audit snapshots in the active documentation tree. Keep tests only when they assert product behavior or repository invariants. Keep roadmap and decision documents only while they describe active work or a still-relevant architectural constraint.
