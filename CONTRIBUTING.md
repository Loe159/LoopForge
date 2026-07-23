# Contributing to LoopForge

LoopForge is a portable CLI-first workflow engine. Contributions should keep the
tool deterministic, scriptable, and honest about autonomy.

## Local setup

```text
python -m pip install -e ".[dev]"
python -m unittest
python -m compileall -q src
git diff --check
```

Use `LOOPFORGE_HOME` in tests or experiments when you need runtime artifacts in a
temporary directory.

The full suite must pass with 0 failures and 0 errors. Run twice consecutively
to confirm no flaky tests.

## Dependencies

| Package | Minimum | Maximum | Notes |
|---|---|---|---|
| Python | 3.11 | — | Required by `pyproject.toml` |
| textual | 8.0 | <9 | TUI framework |
| prompt_toolkit | 3.0 | — | CLI prompt |
| rich | 13.0 | — | Terminal formatting |

## CLI changes

- Preserve stdout for machine-readable results and stderr for errors, progress,
  warnings, and adapter diagnostics.
- Add `--format json` coverage for new scriptable commands.
- Keep text output concise and include the next useful command on failures.
- Do not add hidden network calls, telemetry, publication, or destructive
  filesystem behavior.
- Add focused `unittest` coverage for new Python behavior.

## Non-regression policy

- No test may be permanently marked `@unittest.expectedFailure` or
  `@unittest.skip` except for platform-specific guards (e.g., Textual
  availability).
- Every commit must pass `python -m unittest`, `python -m compileall -q src`,
  and `git diff --check`.
- Flaky tests must be fixed, not skipped.

## Reporting CLI UX bugs

Include:

- `loopforge version`
- the exact command
- stdout
- stderr
- expected behavior
- actual behavior
