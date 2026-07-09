# Contributing to LoopForge

LoopForge is a portable CLI-first workflow engine. Contributions should keep the
tool deterministic, scriptable, and honest about autonomy.

## Local setup

```text
python -m pip install -e .
python -m unittest
```

Use `LOOPFORGE_HOME` in tests or experiments when you need runtime artifacts in a
temporary directory.

## CLI changes

- Preserve stdout for machine-readable results and stderr for errors, progress,
  warnings, and adapter diagnostics.
- Add `--format json` coverage for new scriptable commands.
- Keep text output concise and include the next useful command on failures.
- Do not add hidden network calls, telemetry, publication, or destructive
  filesystem behavior.
- Add focused `unittest` coverage for new Python behavior.

## Reporting CLI UX bugs

Include:

- `loopforge version`
- the exact command
- stdout
- stderr
- expected behavior
- actual behavior
