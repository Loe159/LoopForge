# Coding patterns

## CLI boundaries

- `src/loopforge/cli.py` is the stable public facade. It re-exports extracted
  models/errors/parser types; `build_parser()` delegates to
  `CliParserBuilder`, and `main()` injects the facade into `LoopForgeCli`.
- `CliContext` in `src/loopforge/cli_context.py` is an immutable
  per-invocation container for facade, options, parser, renderer, project
  directory, and streams. Specialized handlers can share it without importing
  the application boundary.
- Command handlers own a cohesive command set. Their `handle()` method
  returns `None` when the command is outside that set and an integer exit code
  after handling it. Keep the top-level exception boundary in `LoopForgeCli`.
- Handler dependencies are resolved through `context.api`. This intentional
  late lookup preserves facade monkeypatches and compatibility imports.
- `CliParserBuilder` owns command declarations, options, aliases, examples,
  and the `_loopforge_topics` map. `LoopForgeArgumentParser.error()` turns
  argparse failures into `CliUsageError`.
- Keep `run`, `continue`, `verify`, and `learn` in their dedicated
  handler classes in `cli_workflow.py`. Provider access belongs in
  `GitHubIssueClient`; prompt orchestration belongs in `RunIntakeService`.

## Models and operation results

- Shared CLI DTOs are dataclasses in `cli_models.py`; immutable value objects
  use `@dataclass(frozen=True)`.
- Engine operations return immutable result dataclasses from the result block
  near the top of `engine.py` rather than ad-hoc tuples. Expected refusals
  carry `ok`, `message`, and `blockers`.
- Persisted run/config data remains `dict[str, Any]` JSON. Add historical
  defaults through normalizers such as `normalize_config` and
  `normalize_run_workflow_state`.
- Treat `current_stage`, `stage_statuses`, `human_gates`, and
  `publish_eligibility` as one lifecycle contract. Apply transitions through
  `apply_initial_task_approval`, `apply_plan_approval`,
  `apply_review_approval`, or `apply_draft_publication`, rather than changing
  individual fields in a CLI handler.
- Read-only research and plan stages use `execute_readonly_stage`: it validates
  required Markdown sections and compares workspace snapshots before and
  after adapter execution. A detected mutation is a blocked result, not an
  automatic rollback.

## Errors and exit codes

- Public errors use `CliError`, `CliUsageError`, or `CliRuntimeError`
  from `cli_errors.py`, with stable code/title/detail/fix/url fields.
- Usage errors exit 2, runtime errors 1 by default, and interruption 130.
- Text errors go to stderr. JSON errors are a single
  `{"ok": false, "error": ...}` payload.
- Unexpected exceptions are converted to `LF_INTERNAL`; debug mode writes a
  cache log through `write_debug_log`.

## Terminal and structured output

- Use `TerminalRenderer` and `render_success`, `render_blocked`, or
  `render_summary_table` from `ui.py` for human output.
- Use `add_format_args` and `add_table_args` from `cli_parser.py`.
  `normalize_format` enforces command support.
- Use `print_json_payload` for a single JSON object. Table commands share
  `TABLE_DEFAULT_COLUMNS`, `apply_table_options`, and `print_table_rows`
  in `cli.py` for text/JSON/CSV parity.
- `--quiet` suppresses successful human output, not machine payloads or
  failures. Keep results on stdout and errors/progress/diagnostics on stderr.
- Honor `NO_COLOR`, `LOOPFORGE_NO_COLOR`, `TERM=dumb`,
  `FORCE_COLOR`, and the explicit no-color option.

## Paths, JSON, and subprocesses

- Pass `Path` objects and read/write UTF-8.
- Reuse `read_json` and `write_json_atomic`; do not replace persistent JSON
  with direct, non-atomic writes. They adapt `JsonStore`, the concrete
  persistence service.
- Reuse `PackRegistry` for pack discovery, checks, and protected paths, and
  `MetricsService` for record loading/aggregation. Keep public engine
  wrappers when changing these services.
- Resolve runtime roots through `loopforge_home`,
  `platform_data_home`, `platform_cache_home`,
  `default_run_root`, and `default_workspace_root`.
- Pack checks and adapter commands are argument lists with explicit timeouts,
  not shell command strings. Pack check placeholders are expanded centrally.

## Test style

- Use `unittest`, `TemporaryDirectory`, `unittest.mock`,
  `io.StringIO`, and direct `main(argv)` calls.
- Reuse `working_directory`, `fixture_python`, the valid research/plan
  fixtures, and approval helpers in `tests/test_cli.py`.
- Isolate runtime state with `LOOPFORGE_HOME`; assert the exit code, output
  channel/payload, and persisted artifacts together.
- Add boundary tests to `tests/test_cli_structure.py` when changing facade
  exports, parser ownership, delegation, or dispatch.
- Add focused service tests in `tests/test_engine_services.py` when changing
  `JsonStore`, `PackRegistry`, or `MetricsService`; retain integration coverage
  in `tests/test_cli.py` for lifecycle gates.

## Naming

- Public result types end in `Result`; handler methods use
  `_handle_<command>`; shell methods use `cmd_<slash_command>`.
- Engine functions use action-oriented snake_case names such as
  `create_run`, `continue_run`, `verify_run`, and `learn_run`.
- JSON contracts include a positive integer `version` when versioned by a
  pack/policy/schema.
