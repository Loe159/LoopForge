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
  `.loopforge/packs/<name>/` pack for repository-specific behavior. Include
  valid `pack.json` and only shell-free command lists in `checks.json`.
- Add slash commands to the `SUPPORTED_COMMANDS` registry and a matching
  `InteractiveShell.cmd_<name>` method in `cli/interactive.py`.

There are no HTTP endpoints, database entities/migrations, background jobs, or
remote publication flows in the current codebase; do not scaffold them without
an explicit product decision.
