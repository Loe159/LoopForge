# Architecture

## Runtime components

```text
pyproject console script
  -> loopforge.cli:main (public compatibility facade)
  -> LoopForgeCli(api=loopforge.cli)
  -> CliParserBuilder + CliContext
  -> first matching command handler
  -> facade helpers and engine APIs
  -> filesystem / Git / local child processes / imported .agent checks

Terminal output -> ui.TerminalRenderer
Interactive shell -> interactive.InteractiveShell -> engine + UI
```

The engine is a local library, not a server. There is no database or internal
network service. State is stored in project config/memory plus external run
directories.

## CLI request flow

1. `LoopForgeCli.run` preparses global flags, builds argparse, creates a
   `CliContext` from `Path.cwd()` and the current standard streams, and
   handles version/no-argument discovery.
2. The parser normalizes `--json` and produces a namespace.
3. `_dispatch` visits Discovery, Project, Workflow, then Metrics handlers.
4. The selected handler calls dependencies through `context.api`, renders a
   result, and returns an exit code.
5. The application boundary maps usage to 2, normal runtime refusal to 1,
   interruption to 130, and unexpected failures to `LF_INTERNAL`.

## Persistence and initialization

`initialize_project` creates or normalizes `.loopforge/config.json`,
installs native templates, and creates durable `.loopforge/memory.md`.
`read_json` requires an object; `write_json_atomic` writes a temporary UTF-8
file, flushes/fsyncs it, then replaces the target.

The config stores the autonomy profile, external `run_root`, current run id,
and default adapter. Runtime artifacts stay outside the repository by default.
In a Git repository, a run can use an external detached worktree; without a
base commit it falls back to the shared checkout and records that mode.

## Run lifecycle

1. `RunCommandHandler._handle_run` auto-initializes, resumes the active
   cockpit when appropriate, or builds interactive/non-interactive intake.
2. `create_run` validates the task and limits, selects a pack, prepares the
   workspace, and writes `run.json`, native Markdown/JSON artifacts,
   `attempts/`, `artifacts/`, `metrics/`, and a legacy mirror.
3. `normalize_run_workflow_state` keeps `run.json` compatible while recording
   `current_stage`, the seven `stage_statuses`, `human_gates`, risk, and
   `publish_eligibility`.
4. GitHub tasks require an `agent:approved` label; manual interactive tasks
   record explicit local approval. `--no-input` reports state but never
   crosses a gate.
5. Research and plan validate frontmatter/sections and compare filesystem/Git
   snapshots before and after execution. Any workspace mutation blocks the
   read-only stage. Plan completion still requires `approve_plan`.
6. `continue_run` requires an approved plan, a valid contract, success
   checks, available workspace, remaining attempts, and profile permission.
7. `verify_run` generates a complete patch, applies diff policy, merges pack
   protected paths into risk policy, runs pack checks without a shell, detects
   repeated-failure stagnation, and writes verification evidence.
8. `approve_review` is separate from verification.
   `prepare_draft_publication` only writes a local draft artifact; it does
   not push, open a PR, or publish over the network.

The normal persisted path is:

```text
task_draft → task_approved → research_ready → plan_ready
  → implementation_ready → verification_ready → review_ready
  → draft_publication_ready
```

The plan, review, and draft-publication moves require explicit interactive
confirmation. `run --no-input` is observational at those gates. A failed
read-only stage or verification instead records a blocked stage and does not
rollback any detected workspace mutation.

## Packs and configuration loading

`pack_roots` searches project-local packs before bundled packs.
`discover_pack_contracts` deduplicates by name, while
`detect_project_pack` scores configured file/directory/glob markers and falls
back to `generic-code`. Checks, skills, protected paths, and memory rules are
loaded from the selected contract without adding domain-specific engine code.

## External boundaries

- Git: remote discovery, base commit, status/diff, worktrees, and patch checks.
- GitHub: explicit issue intake through the local `gh` executable. Failed
  approval verification blocks instead of silently trusting provider text.
- Agent CLIs: Codex, Claude Code, Aider, OpenCode, and mini-swe-agent through
  local subprocess adapters; a deterministic local fixture supports tests.
- Bootstrap checks: imported `.agent/` scripts for isolation, patch, policy,
  risk, result, and artifact validation.

The product contract forbids treating receipts, metrics, or deterministic
checks as publication authority.
