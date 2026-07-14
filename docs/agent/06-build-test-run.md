# Build, test, and run

All commands below run from the repository root unless stated otherwise.

## Prerequisites

- Python 3.11 or newer (`pyproject.toml`).
- Runtime packages `prompt_toolkit>=3.0` and `rich>=13.0`.
- Git for base commits, worktrees, status/diff, patch generation, and bundled
  pack checks.
- `gh` only when reading/listing GitHub issues.
- Agent executables such as `codex`, `claude`, `aider`, `opencode`, or
  `mini-swe-agent` only for their corresponding adapters.

## Canonical developer commands

| Command | Purpose | When/caveat |
| --- | --- | --- |
| `python -m pip install -e .` | Editable local install and `loopforge` console script | Documented in `CONTRIBUTING.md`; writes to the selected Python environment |
| `python -m unittest` | Full test suite | Canonical test command from `CONTRIBUTING.md` |
| `$env:PYTHONPATH='src'; python -m unittest discover -s tests` | Test without an editable install on PowerShell | Historical fallback documented in `docs/implementation-plan.md` |
| `git diff --check` | Whitespace/conflict-marker check | Declared by every bundled pack; may report LF/CRLF warnings on Windows without failing |

The suite currently comprises `tests/test_cli.py`,
`tests/test_cli_structure.py`, and `tests/test_engine_services.py`. The latter
two are focused checks for the modular CLI seam and extracted engine services.
Run the full command above after a Python/CLI change; when diagnosing a narrow
change, run `python -m unittest tests.test_cli_structure` or
`python -m unittest tests.test_engine_services` first. Optional Rich and
prompt-toolkit paths are exercised by CLI tests, so install the declared
runtime dependencies before classifying a terminal-only failure.

## Pack checks

- All bundled packs run `git diff --check`.
- The Python pack also runs `python -m compileall -q .`.
- The Node pack validates `package.json` with Python JSON parsing.

`loopforge verify` executes selected pack checks without a shell. Commands may
use `{python}`, `{repo}`, `{run_dir}`, and `{patch}` placeholders.
`compileall` can create ignored `__pycache__` directories.

## Run the CLI

After editable installation:

```text
loopforge --help
loopforge version
loopforge init
loopforge run --task "Describe the task"
loopforge status
loopforge guide
loopforge dashboard
loopforge continue
loopforge verify
loopforge learn
loopforge runs
loopforge pack list
loopforge pack detect
loopforge metrics record
loopforge metrics summarize
loopforge shell
loopforge completion powershell
```

`loopforge run --no-input` only reports cockpit state; it does not approve a
gate or execute a stage. Commands that mutate state include initialization, run
creation/advancement, adapter execution, verification artifacts, approved
memory promotion, metrics recording, and mutating shell commands.

## Environment variables

- `LOOPFORGE_HOME`: redirects run/workspace data and, indirectly, debug cache.
- `NO_COLOR`, `LOOPFORGE_NO_COLOR`, `TERM=dumb`, `FORCE_COLOR`: terminal
  styling.
- `LOOPFORGE_DEBUG=1`, `DEBUG=loopforge*`: failure diagnostics/debug log.
- `LOCALAPPDATA`, `APPDATA`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`: platform
  data/cache resolution.

Use a temporary `LOOPFORGE_HOME` for tests and experiments.

## Missing commands/infrastructure

`pyproject.toml` configures only Ruff line length and pytest test discovery;
it does not document canonical Ruff/pytest commands or development
dependencies. There is no repository workflow under `.github/workflows/`,
Makefile, Dockerfile, documented wheel/sdist command, deployment process,
database service, or migration command. Do not invent them.

Generated/ignored outputs are listed in `.gitignore`: virtual environments,
Python and tool caches, `dist/`, `build/`, `*.egg-info/`, and local
run/artifact directories.
