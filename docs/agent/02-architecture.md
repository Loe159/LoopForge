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

## Workflow data flow

1. `initialize_project` creates/normalizes configuration, native templates,
   and project memory (`engine/__init__.py`).
2. `create_run` selects a pack, prepares a workspace, writes `run.json` and
   native artifacts, and records the initial approval state.
3. `execute_readonly_stage` renders research/plan input, validates required
   sections, and blocks when workspace snapshots detect mutation.
4. `approve_plan` unlocks implementation. `continue_run` launches either the
   fixture or packaged adapter under the isolated-process policy.
5. `verify_run` invokes packaged patch/diff/risk modules, applies pack checks,
   persists verification evidence, and leaves review pending.
6. `approve_review` and `prepare_draft_publication` are separate; preparation
   writes a local artifact only.

The state machine is normalized by `normalize_run_workflow_state`; verification
and metrics never authorize publication.

## Package and contract flow

`PackRegistry` (`engine/packs.py`) searches `<project>/.loopforge/packs/`
before `src/loopforge/packs/`. Pack checks are argument lists expanded by the
engine, not shell strings. Policies and schemas are resolved by
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
