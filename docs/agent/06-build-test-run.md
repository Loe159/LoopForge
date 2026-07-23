# Build, test, and run

Run commands from the repository root.

| Command | Purpose | Evidence/caveat |
| --- | --- | --- |
| `python -m pip install -e ".[dev]"` | Install an editable package with dev dependencies | Documented in `CONTRIBUTING.md`. |
| `python -m unittest` | Run the full supported suite | Must produce 0 failures, 0 errors. Run twice consecutively to confirm no flaky tests. |
| `python -m compileall -q src` | Check all Python sources for syntax errors | No errors permitted. |
| `git diff --check` | Check whitespace/conflict-marker issues | Required by `AGENTS.md`; bundled packs also use it. |
| `$env:PYTHONPATH='src'; python -m unittest discover -s tests` | Test source tree without editable installation | PowerShell fallback; the test layout is `tests/`. |
| `loopforge --help` / `loopforge help <command>` | Discover installed CLI | Entry point is declared in `pyproject.toml`. |
| `loopforge init`, `run`, `status`, `continue`, `verify`, `learn` | Exercise the normal local workflow | Commands and examples are documented in `README.md`. |
| `loopforge` / `loopforge shell` | Open the default full-screen interactive console | Requires a TTY plus `textual`; `--plain` opts into the prompt-based shell. |
| `loopforge shell --command "/status"` | Exercise one slash command without a TUI prompt | Supported in scripts/tests and does not allow interactive confirmation. |
| `loopforge shell --script commands.loopforge` | Execute UTF-8 slash-command lines | Blank lines and `#` comments are skipped (`cli/interactive.py`). |

## Non-regression policy

- No test may be permanently marked `@unittest.expectedFailure` or `@unittest.skip`
  except for platform-specific guards (e.g., Textual availability).
- Every commit must pass the full suite. Flaky tests must be fixed, not skipped.

## Environment and tooling

- Python 3.11+ is required by `pyproject.toml`.
- `textual`, `prompt_toolkit`, and `rich` are runtime dependencies.
- Git is used for worktrees, patches, and bundled checks.
- `gh` is only needed for GitHub issue intake.
- `LOOPFORGE_HOME` redirects run/workspace data; use a temporary value in tests.
- `NO_COLOR`, `LOOPFORGE_NO_COLOR`, `TERM=dumb`, `FORCE_COLOR`,
  `LOOPFORGE_DEBUG`, and `DEBUG=loopforge*` affect CLI rendering/debugging.
- TUI/UX changes need focused coverage in `tests/test_cli.py`,
  `tests/test_cli_tui.py`, and facade/dispatch coverage in
  `tests/test_cli_structure.py`. The TUI contracts cover 60-column clipping,
  ASCII glyphs, and bounded rendering of large run lists.

## Not established by repository evidence

No canonical Ruff/pytest command or development dependency is declared. No
Docker, Makefile, database/migration command, build backend, or CI/deployment
workflow was found. `src/loopforge.egg-info/` is generated, not a packaging
command source.
