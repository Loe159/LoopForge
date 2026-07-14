# Build, test, and run

Run commands from the repository root.

| Command | Purpose | Evidence/caveat |
| --- | --- | --- |
| `python -m pip install -e .` | Install an editable package and `loopforge` script | Documented in `CONTRIBUTING.md`. |
| `python -m unittest` | Run the full supported suite | Documented in `CONTRIBUTING.md`; covers CLI, engine services, adapter and compatibility behavior. |
| `$env:PYTHONPATH='src'; python -m unittest discover -s tests` | Test source tree without editable installation | Useful PowerShell fallback; the test layout is `tests/`. |
| `git diff --check` | Check whitespace/conflict-marker issues | Required by `AGENTS.md`; bundled packs also use it. |
| `loopforge --help` / `loopforge help <command>` | Discover installed CLI | Entry point is declared in `pyproject.toml`. |
| `loopforge init`, `run`, `status`, `continue`, `verify`, `learn` | Exercise the normal local workflow | Commands and examples are documented in `README.md`. |

## Environment and tooling

- Python 3.11+ is required by `pyproject.toml`.
- `prompt_toolkit` and `rich` are runtime dependencies.
- Git is used for worktrees, patches, and bundled checks.
- `gh` is only needed for GitHub issue intake.
- `LOOPFORGE_HOME` redirects run/workspace data; use a temporary value in tests.
- `NO_COLOR`, `LOOPFORGE_NO_COLOR`, `TERM=dumb`, `FORCE_COLOR`,
  `LOOPFORGE_DEBUG`, and `DEBUG=loopforge*` affect CLI rendering/debugging.

## Not established by repository evidence

No canonical Ruff/pytest command or development dependency is declared. No
Docker, Makefile, database/migration command, build backend, or CI/deployment
workflow was found. `src/loopforge.egg-info/` is generated, not a packaging
command source.
