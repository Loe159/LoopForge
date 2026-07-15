# Reuse catalog

| Reusable element | Location | Use it for | Do not duplicate |
| --- | --- | --- | --- |
| CLI facade | `cli/__init__.py` | Entry point, global flags, payload/table/help helpers, historical seams | A second main/dispatch loop |
| Application/handlers | `cli/app.py`, `cli/workflow.py` | Command dispatch and a cohesive command family | Top-level `if/elif` command branches |
| Invocation context | `cli/context.py` | Streams, options, parser, renderer, and project path | Handler-local global lookups |
| Parser helpers | `cli/parser.py` | Commands, topics, formats, tables, numeric validation | Parallel argparse trees |
| DTOs/errors | `cli/models.py`, `cli/errors.py` | Shared CLI values and structured failures | Handler-specific tuples/dicts/errors |
| GitHub/intake | `cli/github.py`, `cli/intake.py` | Remote issue parsing and guided task collection | New `gh` subprocess calls in handlers |
| Terminal renderer | `cli/ui.py` | Semantic Rich/plain panels, tables, operation context, status/guidance/dashboard views, workflow progress | Direct ANSI, command-local palettes, duplicate status mapping |
| Presentation/actions | `cli/presentation.py`, `cli/actions.py` | Pack-driven stage snapshots and eligible primary actions for text and TUI | Local status mapping or action eligibility |
| Interactive console | `cli/tui.py`, `cli/operations.py`, `cli/evidence.py` | Default TTY navigation, foreground operation receipts, evidence and approval views | Another full-screen layout or fake progress source |
| Interactive shell | `cli/interactive.py` | Headless slash commands and `--plain` prompt history/completion | Another command registry or prompt loop |
| Lifecycle APIs | `engine/__init__.py` | Run state, gates, status/guidance, verification, local draft artifact | Direct lifecycle edits in `run.json` |
| JSON persistence | `engine/storage.py`, engine wrappers | Atomic JSON object reads/writes | Direct non-atomic writes |
| Project registry | `engine/projects.py`, engine exports | Project ids, migrated storage roots, global projects/runs, moved/clone resolution | Basename-keyed roots or manual `LOOPFORGE_HOME` scans |
| Pack registry | `engine/packs.py` | Discovery, inheritance, project override, skills, agents, permissions, workflows, checks, protected paths | Ad-hoc pack filesystem parsing or hard-coded workflow metadata |
| Metrics | `engine/metrics.py` | Unknown-safe records and aggregates | Treating unavailable metrics as zero |
| Runtime modules | `checks/`, `adapters/`, `contracts/`, `templates/` | Patch/diff/risk/isolation/adapter contracts | New copies in CLI code or `.agent` |
| Pack data | `packs/<name>/`, `<project>/.loopforge/packs/` | Project-specific rules and checks | Project branches in engine code |
| Test fixtures | helpers in `tests/test_cli.py` | Isolated home, temporary repositories, workflow states | Repeated setup and inline contracts |

Strongest extension path: add behavior to an existing handler, use a public
engine operation returning a result dataclass, and configure domain variation
through a project-local pack.

For interactive changes, reuse `shell_snapshot`, `action_descriptors`,
`workflow_progress`, the engine `GuidedAction` results, foreground operation
events, and the hydrated `pack_contract` stored on each run.
