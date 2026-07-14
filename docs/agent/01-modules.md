# Module map

## Product package

| Area | Main files | Responsibility and extension point |
| --- | --- | --- |
| Public CLI | `cli/__init__.py` | Stable `loopforge.cli:main`, compatibility exports, global options, payload/table helpers, and CLI presentation seams. |
| CLI parsing/contracts | `cli/parser.py`, `models.py`, `errors.py`, `context.py` | Argument tree, shared DTOs/errors, and immutable invocation dependencies. Add shared command contracts here. |
| CLI orchestration | `cli/app.py`, `workflow.py`, `intake.py`, `github.py` | Handler dispatch, workflow commands, guided intake, and GitHub access. Add a command in its existing cohesive handler family. |
| CLI experience | `cli/ui.py`, `interactive.py` | Rich/plain rendering and slash-command shell. Reuse renderer helpers and shell registry. |
| Engine facade | `engine/__init__.py` | Config, runs, lifecycle state, workspaces, adapters, verification, memory, metrics wrappers, and local draft preparation. It owns persisted lifecycle transitions. |
| Engine services | `engine/storage.py`, `packs.py`, `metrics.py` | Atomic JSON objects, pack discovery/validation, and unknown-safe metric aggregation. |
| Packaged runtime | `checks/`, `adapters/`, `contracts/`, `templates/` | Executable deterministic checks, local adapter, policy/schema paths, and legacy artifact templates. |
| Bundled packs | `packs/<name>/` | Pack metadata and optional skills, checks, and protected paths. Project-local homonyms take precedence. |

## CLI handler ownership

`LoopForgeCli` in `cli/app.py` dispatches in order and stops at the first
handler returning an exit code:

- `DiscoveryCommandHandler`: help, version, completion, shell/interactive.
- `ProjectCommandHandler`: init, packs, runs, status, guide, dashboard.
- `RunCommandHandler`, `ContinueCommandHandler`, `VerifyCommandHandler`, and
  `LearnCommandHandler` in `cli/workflow.py`: one workflow command each.
- `MetricsCommandHandler`: metrics record and summarize.

Handlers resolve dependencies through `CliContext.api`, the injected
`loopforge.cli` facade. This is a compatibility seam verified by
`tests/test_cli_structure.py`.

## Engine ownership

`normalize_run_workflow_state` and the approval/verification APIs in
`engine/__init__.py` own `current_stage`, `stage_statuses`, `human_gates`, and
`publish_eligibility`. CLI and shell code must call these APIs rather than
editing lifecycle fields directly.

`PackRegistry` reads both project and bundled packs. `JsonStore` writes JSON
through a temporary file and replacement. `MetricsService` keeps unavailable
numeric values unknown rather than converting them to zero.

## Compatibility material

The active modules under `.agent/checks/` and
`.agent/adapters/local_implementation_adapter.py` delegate to packaged
counterparts. Other `.agent/` scripts, prompts, policies, schemas, and shell
adapters remain inherited material; no current engine path proves all of them
are runnable.
