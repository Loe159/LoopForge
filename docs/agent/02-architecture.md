# Architecture

## Runtime flow

```text
pyproject console script
  -> loopforge.cli:main
  -> LoopForgeCli(api=loopforge.cli)
  -> CliParserBuilder + CliContext
  -> first matching command handler
  -> engine API / renderer / local process boundary
  -> project JSON/Markdown, external run workspace, Git, optional gh/agent CLI
```

The repository implements a local library and CLI, not an HTTP service. State
is filesystem-backed: project state is in `.loopforge/`, while run and
workspace data are normally outside the repository.

There are currently two human interaction surfaces after engine calls:

- one-shot commands dispatched by `LoopForgeCli` and rendered through
  `TerminalRenderer` (`cli/app.py`, `cli/workflow.py`, `cli/ui.py`);
- a `prompt_toolkit.PromptSession` slash-command REPL whose `cmd_*` methods also
  call engine APIs and render results (`cli/interactive.py`).

They share helpers but not a complete action/view-model layer, so equivalent
commands can follow different orchestration paths.

## Workflow data flow

1. `initialize_project` creates/normalizes configuration, native templates,
   and project memory (`engine/__init__.py`).
2. `create_run` resolves the effective pack, validates the task definition,
   prepares a workspace, writes `run.json` and native artifacts, and records
   the initial approval state.
3. `execute_readonly_stage` renders research/plan/review input with the selected
   pack agent and permission boundary, validates required sections, and blocks
   when workspace snapshots detect mutation.
4. `approve_plan` unlocks implementation. `continue_run` launches either the
   fixture or packaged adapter under the isolated-process policy.
5. `verify_run` invokes packaged patch/diff/risk modules, applies pack checks,
   persists verification evidence, and requires the read-only reviewer next.
6. The reviewer produces `review.md`; `approve_review` remains a separate human
   gate. `prepare_draft_publication` writes a local artifact only.

The state machine is normalized by `normalize_run_workflow_state`; verification
and metrics never authorize publication.

## Package and contract flow

`PackRegistry` (`engine/packs.py`) searches `<project>/.loopforge/packs/`
before `src/loopforge/packs/`, resolves pack inheritance, validates concrete
skill and prompt files, and hydrates declared agents, permission sets, and
workflow stages. Pack checks are argument lists expanded by the engine, not
shell strings. Policies and schemas are resolved by
`loopforge.contracts.policy_path` and `schema_path`.

The active adapter and checks live in `src/loopforge/adapters/` and `checks/`.
The engine invokes them with `python -m loopforge.…`; matching `.agent` scripts
are compatibility launchers.

## External boundaries

- Git: base commit, worktrees, diff/patch generation, and pack checks.
- `gh`: optional GitHub issue intake in `cli/github.py`; issue approval is
  explicitly checked.
- Agent executables: Codex, Claude Code, Aider, OpenCode, and mini-swe-agent
  through the allowlisted local adapter.
- No deployment or remote publication implementation was found.

## Project/run indexing boundary

`new_config` stores `project_name`, `run_root`, and one `current_run_id` in the
project-local config (`engine/__init__.py`). `default_run_root` and
`default_workspace_root` key external data by the resolved directory basename.
`list_runs`, `resume_run`, metrics summaries, and `dashboard_snapshot` all start
from that current project config.

No repository-wide project id, global project registry, or cross-project query
service exists. The proposed multi-project design and non-destructive migration
requirements are documented in `docs/cli-ux-command-plan.md`; they are not
implemented architecture yet.
