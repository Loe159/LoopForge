# Coding patterns

## CLI boundaries

- Keep `loopforge.cli:main` in `cli/__init__.py`. It creates
  `LoopForgeCli` with the facade injected; preserve its re-exports and late
  lookup points.
- Parse only in `CliParserBuilder`; `LoopForgeArgumentParser.error()` raises
  `CliUsageError` rather than exiting (`cli/parser.py`).
- A handler returns `None` for an unowned command and an integer after handling
  it. Put command-specific orchestration in that handler (`cli/app.py`,
  `cli/workflow.py`).
- Pass per-invocation streams, renderer, parser, options, and project path via
  frozen `CliContext`, not mutable globals (`cli/context.py`).

## Results, errors, and output

- Engine operations return frozen `*Result` dataclasses from
  `engine/__init__.py`; expected refusals use `ok`, `message`, and `blockers`.
- Persisted configuration and run data remain JSON objects. Normalize old data
  before adding fields; write with `write_json_atomic`/`JsonStore`.
- Use `CliError`, `CliUsageError`, and `CliRuntimeError` for public failures.
  Usage errors exit 2; runtime errors default to 1 (`cli/errors.py`).
- Text errors use stderr. Machine output is one JSON object via
  `print_json_payload`; table commands share the facade’s table helpers.
- Use `TerminalRenderer` and `render_*` helpers in `cli/ui.py`; preserve
  quiet, no-color, JSON/CSV, and stdout/stderr behavior.

## Lifecycle and processes

- Treat `current_stage`, `stage_statuses`, `human_gates`, and
  `publish_eligibility` as one contract. Use `apply_*_approval`,
  `approve_plan`, `approve_review`, and `prepare_draft_publication`.
- Read-only stages are detection-based: a mutation blocks the stage but is not
  automatically rolled back (`execute_readonly_stage`).
- Pass `Path` objects, UTF-8 text, and subprocess argument lists. Reuse
  `run_with_isolated_process`, `run_streaming_process`, and pack placeholder
  expansion instead of shell command strings.

## Tests and naming

- Use `unittest`, `TemporaryDirectory`, `unittest.mock`, `StringIO`, and
  direct `main(argv)` calls (`tests/test_cli.py`).
- Add facade/parser/dispatch coverage in `tests/test_cli_structure.py`; add
  storage/pack/metrics/runtime-layout coverage in `tests/test_engine_services.py`.
- Public result types end in `Result`; engine actions use snake_case;
  interactive methods use `cmd_<slash_command>`.
