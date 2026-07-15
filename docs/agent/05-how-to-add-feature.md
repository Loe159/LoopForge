# How to add a feature

## Add a CLI command

1. Declare parser arguments, help, examples, and topic mapping in
   `cli/parser.py`; reuse format/table helpers.
2. Add the command to the relevant handler in `cli/app.py`, or a dedicated
   workflow handler in `cli/workflow.py`. Register a new handler only for a
   genuinely separate cohesive family.
3. Put reusable behavior in `engine/__init__.py` and return a result dataclass.
4. Render text with `cli/ui.py`; JSON uses one payload from the facade.
5. Update help/completion/interactive registry if the command is discoverable
   there.
6. Test parser/dispatch boundaries and integration output/artifacts.

## Add an engine operation or configuration field

1. Add an immutable `*Result` near existing engine result types.
2. Accept an explicit `project_dir: Path`; reuse home, status, profile, pack,
   and JSON helpers.
3. Return a blocked result for expected refusal; reserve exceptions for invalid
   or unexpected conditions.
4. For config, update `new_config`, `normalize_config`, and the relevant
   persisted contract together.
5. Test both the result and persisted files with an isolated `LOOPFORGE_HOME`.

## Change lifecycle, packs, or shell

- Start lifecycle work at `initial_workflow_state` and
  `normalize_run_workflow_state`. Preserve all coupled state fields and the
  separation between verification and review approval.
- Add a bundled pack under `src/loopforge/packs/<name>/`; use a project-local
  `.loopforge/packs/<name>/` pack for repository-specific behavior. Prefer
  `extends: generic-code` for a domain pack. Add concrete
  `skills/<name>/SKILL.md` definitions and, when overriding the base workflow,
  keep `agents.json`, agent prompts, `permissions.json`, and `workflow.json`
  internally consistent. Use only shell-free command lists in `checks.json`.
- Before changing navigation or command presentation, read
  `docs/cli-ux-command-plan.md`. Reuse `TerminalRenderer`, `shell_snapshot`,
  `ActionDescriptor`, `workflow_progress`, and hydrated pack workflow data.
- For the current shell, add slash commands to the `SUPPORTED_COMMANDS`
  registry and a matching `InteractiveShell.cmd_<name>` method in
  `cli/interactive.py`; update aliases/groups/help/completion and tests where
  applicable. Do not add a parallel prompt loop.
- When behavior exists in both the top-level CLI and shell, route both through
  the same engine operation and keep intake, confirmation, result, and next
  action consistent. `loopforge run`/`RunCockpitService` and `/run` are the
  current duplication to remove, not a pattern to copy.
- For multi-project behavior, reuse `engine/projects.py` through its public
  engine APIs. Do not scan storage roots or edit `current_run_id` outside
  engine APIs. Test moved/clone conflicts and prior-root migration.

There are no HTTP endpoints, database entities/migrations, background jobs, or
remote publication flows in the current codebase; do not scaffold them without
an explicit product decision.
