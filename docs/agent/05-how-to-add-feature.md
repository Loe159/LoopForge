# How to add a feature

## Add a top-level CLI command

1. Add the parser, arguments, help/examples, and topic registration in
   `CliParserBuilder.build()`. Reuse common format/table helpers.
2. Add the command to the matching handler's `commands` set: discovery,
   project, and metrics handlers live in `cli_app.py`; `run`, `continue`,
   `verify`, and `learn` own dedicated handlers in `cli_workflow.py`. If the
   responsibility is genuinely new, create a cohesive handler and register it
   in `LoopForgeCli.__init__`.
3. Keep domain logic in `engine.py`. The handler should orchestrate, choose
   format/exit code, and render the engine result through `context.api`.
4. Use a single JSON payload containing `ok`, shared UI helpers for text, and
   structured CLI errors for operator failures.
5. Update hard-coded discovery surfaces when relevant:
   `print_grouped_help`, `completion_script`, and the interactive command
   registry. Keep `loopforge.cli:main` as the console entry point.
6. Extend `tests/test_cli_structure.py` for parser/delegation/dispatch
   boundaries and `tests/test_cli.py` for text, JSON, quiet, errors, and
   artifacts.

## Add a subcommand

Follow `pack` or `metrics`:

- declare a required argparse subparser with a dedicated destination;
- register parent and child topic tuples;
- branch only inside the owning handler;
- keep a defensive `CliUsageError` for an unknown parsed value.

## Add an engine operation

1. Add an immutable result dataclass near the existing engine result types.
2. Accept an explicit `project_dir: Path`; reuse status, profile, pack, and
   root helpers.
3. Return a blocked result for expected workflow refusal. Reserve exceptions
   for invalid inputs or unexpected filesystem/process failures.
4. Normalize old persisted state before adding fields. Use UTF-8 and
   `write_json_atomic`.
5. Test in a temporary project with isolated `LOOPFORGE_HOME`, then verify
   both the result and files.

## Change the run lifecycle or an approval gate

1. Start with `initial_workflow_state` and
   `normalize_run_workflow_state` in `engine.py`; older run records must gain
   safe defaults.
2. Use or extend the matching transition helper (`apply_*_approval`) and
   return a `StageResult` for an expected refusal.
3. Keep the engine transition separate from its cockpit prompt in
   `RunCockpitService`. `--no-input` must remain observational at task, plan,
   review, and draft-publication gates.
4. Update integration tests for persisted `current_stage`, the affected
   `stage_statuses`/`human_gates`, and `publish_eligibility`. Include a test
   that verification alone cannot prepare a publication artifact.

## Add or change output

- JSON: call `print_json_payload`; never mix prose with a machine payload.
- Text/JSON/CSV table: define default columns in `TABLE_DEFAULT_COLUMNS`,
  expose table arguments, then call `print_table_rows`.
- Human output: use `TerminalRenderer` and shared success/blocked helpers.
  Preserve quiet/no-color behavior and stdout/stderr separation.

## Add a project pack

1. Create `.loopforge/packs/<name>/pack.json` with a positive version,
   detection rules, priority, description, and skills.
2. Add the required contribution files: `SKILL.md`, `checks.json`,
   `protected-paths.json`, and `memory-rules.md`.
3. Keep check commands as nonempty argument lists with positive timeouts. Use
   only the documented `{python}`, `{repo}`, `{run_dir}`, and
   `{patch}` placeholders.
4. Test pack discovery, contributed skills, checks, and protected-path risk.
   A project-local pack overrides a bundled pack of the same name.

## Add a slash command

1. Add the supported name/description to the registry in `interactive.py`.
2. Implement `InteractiveShell.cmd_<name>() -> DispatchResult`; the existing
   dispatcher and completer derive behavior from the registry/convention.
3. Reuse engine/UI APIs and test through
   `loopforge shell --command "/..."` or direct shell dispatch.

## Change project configuration

Update `new_config`, `normalize_config`, and the relevant config-key
contract together. Preserve older config files by supplying defaults during
normalization, write atomically, and add repair/idempotency tests.

## Flows that do not exist

There is no HTTP endpoint/controller, service/repository database layer,
database entity/migration flow, background scheduler, or remote publication
flow. Do not add documentation or scaffolding for them without an explicit
product decision. Current publication support only prepares a local draft
artifact after review approval.
