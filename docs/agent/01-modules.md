# Module map

## Product package

| Module | Responsibility and dependencies | Extension point |
| --- | --- | --- |
| `src/loopforge/__init__.py` | Exposes `__version__` | Update with release metadata only |
| `cli_errors.py` | `CliError`, `CliUsageError`, and `CliRuntimeError` with stable code/title/detail/fix/exit semantics | Reuse for operator-facing failures |
| `cli_models.py` | `CliOptions`, `GitHubIssueRef`, `RunIntake`, and `IssueReadResult` dataclasses | Add shared CLI DTOs here instead of handler-local equivalents |
| `cli_parser.py` | `LoopForgeArgumentParser`, common argument helpers, and `CliParserBuilder` for the public argparse tree | Add commands, options, aliases, topics, and help text here |
| `cli_context.py` | Immutable `CliContext` carrying facade, streams, renderer, options, parser, and cwd | Pass invocation dependencies to handlers instead of reading globals |
| `cli_github.py` | Injected `GitHubIssueClient` for remote parsing, issue reads, labels, and approval checks | Add GitHub-provider behavior while preserving facade seams |
| `cli_intake.py` | `RunIntakeService` for guided manual/GitHub intake | Add prompts and intake decisions here |
| `cli_workflow.py` | `RunCommandHandler`, `RunCockpitService`, `ContinueCommandHandler`, `VerifyCommandHandler`, and `LearnCommandHandler` | Change one workflow command or cockpit concern without growing application dispatch |
| `cli_app.py` | Discovery/project/metrics handlers, `LoopForgeCli`, dispatch, and the top-level exception boundary | Add behavior to the matching handler or register a new cohesive handler |
| `cli.py` | Public compatibility facade, intake/GitHub provider, global options, formatting/tables, help/completion, payloads, and cockpit helpers; delegates parser and main | Preserve re-exports and injected lookup points when extracting more code |
| `engine_storage.py` | `JsonStore` read-object and atomic-write primitives | Persist JSON objects without duplicating atomic write logic |
| `engine_packs.py` | `PackRegistry` for discovery, override resolution, validation, detection, checks, and protected paths | Adapt repositories through pack data, not engine branches |
| `engine_metrics.py` | `MetricsService` for record loading and unknown-safe aggregation | Summarize metrics without treating unavailable values as zero |
| `engine.py` | Public compatibility functions plus workflow state, config/runs, workspaces, profiles, memory, adapters, verification, dashboard, and local draft publication | Add reusable domain behavior here, then extract a cohesive service when it gains persistence/invariants |
| `ui.py` | `TerminalRenderer` plus shared status/guidance/dashboard/success/blocked rendering with Rich/plain modes | Reuse for all human-readable terminal output |
| `interactive.py` | Slash-command registry, completer, `InteractiveShell`, session preferences, export/copy helpers, and shell dispatch | Add a real slash command through the existing registry and `cmd_*` convention |

`cli_app.py` deliberately resolves command dependencies through the injected
`loopforge.cli` facade. This preserves existing imports and monkeypatches such
as `loopforge.cli.current_status` and the GitHub provider helpers. It is a
compatibility boundary, not accidental indirection.

## Command-handler ownership

- `DiscoveryCommandHandler`: help, version, completion, shell, and
  `interactive`.
- `ProjectCommandHandler`: init, pack, runs, status, guide, and dashboard.
- `RunCommandHandler`, `ContinueCommandHandler`, `VerifyCommandHandler`,
  and `LearnCommandHandler`: one class for each workflow command.
- `MetricsCommandHandler`: metrics record and summarize.

Each handler returns `None` for an unowned command and an integer exit code
after handling one. `LoopForgeCli._dispatch` stops at the first non-`None`
result.

## Workflow-state ownership

`engine.py` is the single owner of persisted lifecycle transitions:

| Transition | Engine API / persisted outcome | CLI integration |
| --- | --- | --- |
| Approved task → research/plan | `execute_readonly_stage` validates the artifact and blocks workspace mutation | `RunCockpitService` offers the next read-only stage from `run` |
| Awaiting plan → implementation | `approve_plan` records the local approval and sets `implementation_ready` | Cockpit confirmation only; no separate top-level command |
| Verified → review | `verify_run` records verification, leaves review pending, and makes publication ineligible | Cockpit prompts for review only in interactive text mode |
| Review approved → draft artifact | `approve_review` enables draft eligibility; `prepare_draft_publication` writes the local artifact | Cockpit confirmation only; `--no-input` does neither action |

Use these APIs and `normalize_run_workflow_state`; do not patch lifecycle keys
from a handler or interactive command.

## Packs

Every bundled pack under `.loopforge/packs/<name>/` can contain:

- `pack.json`: name, positive version, priority, detection, skills, and
  contribution filenames;
- `SKILL.md`: pack-facing guidance;
- `checks.json`: shell-free deterministic commands;
- `protected-paths.json`: risk contribution;
- `memory-rules.md`: human-readable promotion rules.

Project-local packs at `<project>/.loopforge/packs/<name>/` override bundled
packs with the same name. Use this data-driven extension before adding
project-specific branches to `engine.py`.

## Imported bootstrap core

`engine.py` still resolves code under `.agent/` through
`repository_root()`, `imported_check()`, `local_implementation_adapter()`,
and `isolated_process_module()`.

- Main verification dependencies:
  `generate_complete_patch.py`, `diff_policy.py`, and
  `classify_patch_risk.py`.
- Process/adapter dependencies:
  `isolated_process.py`,
  `.agent/adapters/local_implementation_adapter.py`, and
  `validate_implementation_result.py`.
- Legacy compatibility:
  `.agent/templates/`, `validate_artifacts.py`, policies, and schemas.

Keep these scripts runnable until their behavior has moved into the product
package behind thin compatibility wrappers. Other inherited scripts are not
necessarily part of the current product path.

## Tests and documentation

- `tests/test_cli_structure.py` fixes the modular boundaries: facade
  re-exports, parser delegation, application delegation, first-handler-wins,
  topics/options, and usage errors.
- `tests/test_cli.py` exercises config, runs, packs, GitHub intake, memory,
  profiles, shell/UI, guidance, metrics, worktrees, adapters, verification,
  risk, stagnation, review, and publication guards.
- `tests/test_engine_services.py` fixes the atomic JSON-store, project-pack
  override/normalization, and unknown-safe metrics-service contracts.
- `README.md` and `docs/product-architecture.md` describe current operator
  and architectural intent. Migration/implementation plans are historical or
  directional and must be checked against code before reuse.
