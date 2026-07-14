# Reuse catalog

Before creating code, search this catalog and the referenced module.

| Reusable element | Where | Reuse when | Do not duplicate |
| --- | --- | --- | --- |
| Public CLI facade | `src/loopforge/cli.py` | Preserving entry point, re-exports, helpers, and historical lookup points | A second public entry point or parallel error/model types |
| Application boundary | `LoopForgeCli` in `cli_app.py` | Parsing, dispatch ordering, exception/exit handling | Another top-level parse/dispatch/try-except loop |
| Invocation context | `CliContext` | Sharing cwd, streams, renderer, options, and facade | Direct global lookups in every new handler |
| GitHub provider | `GitHubIssueClient` in `cli_github.py` | Remote parsing, issue reads, labels, approval validation | New `gh` subprocess calls in intake/handlers |
| Guided intake | `RunIntakeService` in `cli_intake.py` | Manual/GitHub task prompts, checks, permissions, and source metadata | Prompt logic embedded in command handlers |
| Command handlers | Discovery/project/metrics handlers in `cli_app.py` | Adding behavior to an existing command family | New command `if/elif` branches in `main()` |
| Workflow handlers | `cli_workflow.py` | `run`, `continue`, `verify`, or `learn` behavior | A multi-command workflow handler |
| Run cockpit | `RunCockpitService` in `cli_workflow.py` | Active-run resume, created-run summary, and adapter launch prompt | UI/state-transition helpers embedded in `RunCommandHandler` |
| Parser builder | `CliParserBuilder`, `LoopForgeArgumentParser` | Commands, subcommands, aliases, topics, help | A separate parser or raw argparse exits |
| Shared parser helpers | `add_format_args`, `add_table_args`, `non_negative_int` | Formats, shaped tables, nonnegative metrics | Repeated option/validator definitions |
| CLI DTOs | `cli_models.py` | Global options, issue refs, intake/read results | Equivalent dicts or tuples |
| CLI errors | `cli_errors.py`, `render_cli_error` | Structured operator errors and stable codes | Direct error printing with arbitrary exit codes |
| Terminal UI | `TerminalRenderer` and `render_*` in `ui.py` | Human summaries, tables, panels, loading, no-color | Direct ANSI/Rich logic or divergent text fallback |
| Table/payload helpers | `print_json_payload`, `apply_table_options`, `print_table_rows`, status/guidance payloads in `cli.py` | JSON/CSV/list/status output | Ad-hoc serialization, filtering, or sorting |
| Engine result dataclasses | Result types near the top of `engine.py` | New domain operation with normal blocked states | Boolean/tuple conventions incompatible with handlers |
| Lifecycle transitions | `normalize_run_workflow_state`, `apply_*_approval`, `execute_readonly_stage`, `approve_plan`, `approve_review`, `prepare_draft_publication` in `engine.py` | Changing stage/gate/publication behavior | Direct edits to `run.json` lifecycle fields outside engine tests |
| Cockpit stage integration | `RunCockpitService` and `maybe_run_readonly_stage_from_cockpit` | An interactive next-stage confirmation or rendering change | A second gate/prompt implementation in a handler |
| JSON/path primitives | `read_json`, `write_json_atomic`, home/root functions in `engine.py` | Config, run metadata, metrics, artifacts | Hard-coded home paths or non-atomic JSON |
| JSON storage | `JsonStore` in `engine_storage.py` | New file-backed JSON object persistence | Duplicated temporary-file/replace implementations |
| Pack registry | `PackRegistry` in `engine_packs.py` | Contract discovery, override, checks, and protected paths | Pack filesystem parsing in engine/CLI code |
| Metrics service | `MetricsService` in `engine_metrics.py` | Record discovery and unknown-safe aggregation | Summary logic that treats missing values as zero |
| Workflow status/guidance | `current_status`, `current_guidance`, `guided_action` | Operator orientation and next actions | Recomputing state in CLI/UI code |
| Packs | Discovery/load/check/protected-path/memory helpers in `engine.py` and `.loopforge/packs/` | Project/domain adaptation | Project-specific conditions in the engine |
| Native templates | `.loopforge/templates/`, template loaders in `engine.py` | Loop/memory/scratch/exchange initialization | Alternate artifact formats |
| Imported deterministic core | `.agent/checks/`, policies, schemas, templates, local adapter; engine resolver helpers | Patch, diff, risk, isolation, legacy validation during migration | Reimplementation inside CLI handlers |
| Interactive registry | `SUPPORTED_COMMANDS`, `COMMANDS`, `InteractiveShell.cmd_*` in `interactive.py` | Slash commands and completion | A second interactive router |
| Test fixtures | Helpers at the start of `tests/test_cli.py` | Repository/run/workflow integration tests | Repeated setup and inline artifact contracts |

## Strongest opportunities

1. Extend the existing handler family and pass state through `CliContext`.
2. Put reusable behavior in an engine API that returns a result dataclass.
3. Use `TerminalRenderer` and the existing JSON/table helpers.
4. Use atomic JSON and portable runtime-root helpers.
5. Prefer a project-local pack for checks, protected paths, skills, and memory
   rules. `test_project_local_pack_can_add_skills_without_engine_changes`
   demonstrates this extension path.
6. Keep using the imported deterministic checks until their behavior is moved
   behind product-package wrappers and parity tests.
7. Reuse engine lifecycle transitions for every approval or publication change;
   verification evidence must remain separate from review approval.
