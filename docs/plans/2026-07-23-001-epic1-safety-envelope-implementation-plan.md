---
title: Epic 1/6 - Safety Envelope - Implementation Plan
type: plan
date: 2026-07-23
topic: epic1-safety-envelope
parent_roadmap: docs/plans/2026-07-22-001-refactor-loopforge-product-hardening-plan.md
parent_issue: https://github.com/Loe159/LoopForge/issues/27
artifact_contract: ce-unified-plan/v1
artifact_readiness: plan-ready
execution: code
---

# Epic 1/6 — Safety Envelope: Implementation Plan

## Goal Capsule

Build the safety envelope for LoopForge: confine paths, enforce pack trust,
bound all subprocess execution, make mutation targeting explicit, and
guarantee machine-output integrity.

## Context and Dependencies

- **Prerequisite**: Epic 0 (green baseline, licence/non-Git/install decisions)
- **Nominal window**: weeks 3-6 of the global roadmap
- **Blocks**: Epic 2 and any public beta
- **Existing issues to reconcile**: #17 (compatibility shell output leaking),
  #18 (adapter selector), #21 (Codex sandbox on Windows)

## Target Architecture

All path/filesystem operations must transit through confined resolvers. A
single `ProcessRunner` bounds output streams and kills the full process tree.
An explicit `ActionScope` prevents wrong-target mutations. Machine output
modes (`--json`, `--csv`, `--quiet`) are free of any loader/spinner/ANSI on
stdout.

## Subtasks

---

### Subtask 1.1 — Path and artifact confinement

**Objective**: Every `project_id`, `run_id`, artifact path, run root, and
pack-provided path must be validated by a confined resolver before any
filesystem access. Reject or explicitly migrate legacy external `run_root`
values.

**Files concerned**:
- `src/loopforge/engine/projects.py` — `storage_root()`, `load_registry()`,
  `register_project()`
- `src/loopforge/engine/__init__.py` — `open_project()`, `create_run()`,
  `resume_run()`, `run_workspace_path()`, `persist_run_json()`, `/raw` paths
- New module: `src/loopforge/engine/path_resolvers.py`
- `src/loopforge/cli/interactive.py` — `cmd_raw()` (~line 1751)
- `src/loopforge/checks/isolated_process.py` — `validate_command()`

**Work items** (sequential):
1. Create `src/loopforge/engine/path_resolvers.py` containing:
   - `validate_identifier(value: str, prefix: str) -> str` — validates
     identifier syntax, rejects `..`, `/`, `\`, `:`, `*`, etc.
   - `resolve_confined(allowed_root: Path, *segments: str) -> Path` — joins
     segments, resolves, proves containment with `relative_to`.
   - `resolve_run_root(home: Path, project_id: str) -> Path`
   - `resolve_run_dir(run_root: Path, run_id: str) -> Path`
   - `resolve_artifact(run_dir: Path, relative_path: str) -> Path`
2. Apply resolvers in `projects.py`:
   - Validate `project_id` in `storage_root()`.
   - Confine `registry_path()` in `home`.
   - Validate `project_id` in `register_project()`.
3. Apply resolvers in `engine/__init__.py`:
   - `open_project()`: resolve and confine `project_dir`, validate `project_id`.
   - `create_run()`: validate `project_id` and `run_id` before directory
     creation; confine all writes under `run_root`.
   - `resume_run()`: validate `run_id` before lookup.
   - `run_workspace_path()`: confine workspace path within `run_dir`.
   - `archive_current_run()`: validate `run_id` before mutation.
4. Legacy `run_root` migration:
   - Detect external `run_root` in `normalize_config()`.
   - Reject with clear diagnostic instead of silent copy.
   - Add `doctor` message for explicit migration.
5. `/raw` hardening in `cli/interactive.py`:
   - Resolve path via `resolve_artifact(run_dir, relative_path)`.
   - Refuse if outside `run_dir`.
6. Runtime root inside project:
   - Detect if `LOOPFORGE_HOME` / data home is nested inside project.
   - Refuse at startup or exclude from adapter scope.

**Tests**:
- `tests/test_path_resolvers.py` (new):
  - `test_validate_identifier_rejects_traversal`
  - `test_validate_identifier_accepts_valid`
  - `test_resolve_confined_blocks_outside`
  - `test_resolve_confined_allows_within`
  - `test_resolve_run_dir_rejects_bad_id`
- `tests/test_cli.py` additions:
  - `test_init_rejects_escape_project_id`
  - `test_raw_blocks_outside_run_dir`
  - `test_raw_allows_within_run_dir`

**Exit criteria**: AE1 passes (malicious config rejected before creation).
`/raw` cannot disclose files outside `run_dir`.

---

### Subtask 1.2 — Local-pack trust

**Objective**: A local pack cannot execute a check without explicit approval.
In non-interactive mode, refuse with a stable error code. Log hash, origin,
and commands.

**Files concerned**:
- `src/loopforge/engine/packs.py` — `load_checks()`, `check_paths()`,
  `load_contract()`
- `src/loopforge/engine/__init__.py` — `verify_run()`, `create_run()`,
  `discover_pack_contracts()`
- `src/loopforge/cli/textual_app/app.py` — trust confirmation UI
- `src/loopforge/cli/interactive.py` — `/trust`, `/untrust` commands
- `src/loopforge/engine/storage.py` — trust state persistence

**Work items**:
1. Create `PackTrustStore` (in `packs.py` or new module):
   - `is_trusted(pack_hash: str) -> bool`
   - `trust(pack_hash, pack_name, commands) -> None`
   - `untrust(pack_hash) -> None`
   - Store in `{LOOPFORGE_HOME}/trusted_packs.json` via `JsonStore`.
   - Hash covers the complete hydrated contract.
2. Modify `PackRegistry`:
   - `load_checks()` → also return `content_hash`.
   - `load_contract()` → add `contract_hash` (sha256 of hydrated contract).
3. Modify `verify_run()`:
   - Before executing local-pack checks:
     - Compute hash, check `PackTrustStore.is_trusted(hash)`.
     - Interactive mode: request confirmation (name, hash, commands, cwd, env
       policy, changes since last approval).
     - Non-interactive mode: refuse with stable error code (exit 77) + remediation.
   - Log execution receipt (hash, commands, exit code, timestamp) in run.
4. Add trust management commands:
   - `/trust pack <name>` — compute current hash, register.
   - `/untrust pack <name>` — revoke.
   - `trusted list` — display approved packs.
5. Minimal environment:
   - Pass only allow-listed env variables (already done in `isolated_process.py`).
   - Document network disabling (platform-dependent).
6. TUI trust confirmation:
   - Add `TrustPackScreen` widget showing hash, origin, commands, env policy.
   - Reuse via `request_action()` for untrusted pack actions.

**Tests**:
- `tests/test_engine_services.py` additions:
  - `test_untrusted_local_pack_refused_non_interactive`
  - `test_trusted_pack_allowed_after_approval`
  - `test_pack_trust_revoked`
  - `test_bundled_pack_always_trusted`
  - `test_trust_hash_changes_after_pack_modified`
  - `test_pack_trust_store_persistence`
- `tests/test_cli.py` additions:
  - `test_trust_command_registers_hash`
  - `test_untrust_command_revokes_hash`
  - `test_verify_blocked_for_untrusted_pack`

**Exit criteria**: AE2 passes (untrusted pack: interactive display, non-interactive
refusal with stable code). No local-pack subprocess starts without approval.

---

### Subtask 1.3 — Unified bounded process runner

**Objective**: Replace ad-hoc process runners with one `ProcessRunner` that
bounds output in streaming mode, closes stdin, kills the full process tree
on timeout/cancellation, and produces a trusted receipt.

**Files concerned**:
- `src/loopforge/checks/isolated_process.py` — already strong, to extend
- `src/loopforge/engine/__init__.py` — multiple subprocess calls (~lines 5293,
  6857, 7352)
- New module: `src/loopforge/engine/process_runner.py`

**Work items**:
1. Audit all subprocess calls in the engine:
   - List every `subprocess.Popen`/`subprocess.run`/`subprocess.check_output`
     in `engine/__init__.py`.
   - Identify those not passing through `isolated_process.run()`.
   - Priority: `verify_run()` (line 7631), adapters (lines 5293, 6857), git
     operations (~lines 2163, 2178).
2. Create `src/loopforge/engine/process_runner.py`:
   - `ProcessRunner` class with:
     - `run(command, *, timeout, output_limit_bytes, env, cwd, stdin_data,
       cancel_event) -> ProcessReceipt`
   - `ProcessReceipt` dataclass: `completed`, `timed_out`,
     `output_limit_exceeded`, `kill_requested`, `returncode`, `stdout`,
     `stderr`, `started_at`, `finished_at`, `pid`, `children_terminated`
   - Delegates to `isolated_process.run()` with additions:
     - Ring buffer (`collections.deque(maxlen=N)`) when output exceeds
       `output_limit_bytes`, with `output_truncated` flag.
     - Optional file spooling if `spool_dir` provided.
     - Process tree termination:
       - POSIX: `os.setsid()`, `os.killpg()`, `SIGKILL`, verify with `pgrep`.
       - Windows: `CREATE_NEW_PROCESS_GROUP`, `taskkill /F /T /PID`.
     - Stdin: closed by default (`DEVNULL`), piped only if `stdin_data` provided.
     - Issue distinction: `exit`, `timeout`, `output_limit`, `cancellation`,
       `launch_failure`, `protocol_failure`.
3. Replace ad-hoc runners:
   - `verify_run()` → use `ProcessRunner` for each check.
   - `command_for_adapter()` / adapter execution → `ProcessRunner`.
   - Git operations → `ProcessRunner`.
   - Every direct `subprocess` call → migrate.
   - Each call produces a `ProcessReceipt` recorded in the run.
4. Add post-timeout verification:
   - After timeout, verify PID and descendants are terminated.
   - Log warning if descendants survive.

**Tests**:
- `tests/test_process_runner.py` (new):
  - `test_infinite_stdout_bounded`
  - `test_timeout_kills_process_tree`
  - `test_cancellation_stops_process`
  - `test_stdin_closed_by_default`
  - `test_launch_failure_receipt`
  - `test_normal_completion_receipt`
  - `test_large_output_ring_buffer`
  - `test_process_tree_termination_posix`
  - `test_process_tree_termination_windows`
- `tests/test_cli.py` additions:
  - `test_verify_timeout_produces_blocked_evidence`
  - `test_json_on_tty_no_spinner`

**Exit criteria**: AE5 passes (infinite output + child → bounded output, tree
terminated, result not `completed`). AE7 passes (TTY + `--json` → first byte
`{`). All subprocess calls use `ProcessRunner` or have a documented exception.

---

### Subtask 1.4 — Mutation targeting and cancellation truth

**Objective**: `ActionScope(project_id, project_path, run_id, revision)`
prevents mutations on the wrong target. `archive_run(run_id)` targets
explicitly. An operation non-cancellable after commit must never appear
`cancelled`.

**Files concerned**:
- `src/loopforge/cli/textual_app/app.py` — `action_archive()`,
  `_archive_confirmed()`, `_operation_result()`
- `src/loopforge/cli/operations.py` — `OperationController`
- `src/loopforge/engine/__init__.py` — `archive_current_run()`, all mutating
  functions
- `src/loopforge/cli/state_store.py` — snapshots, `selected_run_id`

**Work items**:
1. Create `ActionScope` dataclass:
   ```python
   @dataclass(frozen=True)
   class ActionScope:
       project_id: str
       project_path: Path
       run_id: str | None
       revision: int | None
       snapshot: str | None
   ```
   - `validate() -> None` — verify project exists, IDs are valid.
   - `revalidate(store) -> ActionScope | None` — reload from storage, compare.
2. Modify `archive_current_run()` → `archive_run(run_id: str)`:
   - Takes explicit `run_id` instead of using `config["current_run_id"]`.
   - Uses `ActionScope` to validate the target.
   - Raises `ValueError` if `run_id` doesn't match current project.
3. Modify `action_archive()`:
   - Capture `run_id` of the highlighted item (`_selected_index`).
   - Build `ActionScope` with this `run_id`.
   - Revalidate before committing.
   - Pass `run_id` to shell operation, not global `current_run_id`.
4. Rework cancellation logic in `_operation_result()`:
   - Distinguish two phases in `OperationController`:
     - `is_cancellable` — before commit point.
     - `commit_started` — after commit began.
   - `cancel()` before commit → `cancelled=True`, no persistent effect.
   - `cancel()` after commit → `cancelled=False`, real result returned.
   - `_operation_result()` NEVER replaces result with "Operation cancelled"
     after commit started.
5. Add identity guards to workers:
   - `_load_evidence_worker`, `_export_evidence_worker`, `_open_run_worker`:
     - Capture `project_id` and `run_id` at launch.
     - Before publishing result, verify current project/run unchanged.
     - If changed, do not publish (result is stale).
6. Make UI explicit about cancellation:
   - Confirmation dialogs display exact `run_id` and `short_id`.
   - Receipts always show `project`, `run`, `stage`, `target`, `consequence`.

**Tests**:
- `tests/test_cli_textual_app.py` additions:
  - `test_archive_targets_highlighted_run_not_current`
  - `test_cancellation_before_commit_no_effect`
  - `test_cancellation_after_commit_reports_real_result`
- `tests/test_engine_services.py` additions:
  - `test_archive_run_with_explicit_id`
  - `test_archive_run_wrong_project_raises`
  - `test_action_scope_revalidate_detects_change`

**Exit criteria**: AE6 passes (run B highlighted → confirmation names B, only B
mutated after revalidation). No operation shows "cancelled" after commit.
Evidence preview/export workers don't publish stale results.

---

### Subtask 1.5 — Machine-output integrity

**Objective**: `--json`, `--csv`, `--quiet` must be free of spinners, colors,
and human text on stdout, including in a TTY. Human progress goes to stderr.

**Files concerned**:
- `src/loopforge/cli/workflow.py` — Run/Verify/Continue/Learn handlers
- `src/loopforge/cli/ui.py` — `TerminalRenderer`, `loading()`, spinners
- `src/loopforge/cli/__init__.py` — `print_json_payload()`
- `src/loopforge/cli/interactive.py` — shell parsers (direct stderr writes)

**Work items**:
1. Disable loaders in machine mode:
   - In `cli/workflow.py` handlers:
     - If `context.mode in ("json", "csv", "quiet")` → plain mode only.
     - Never call `renderer.loading()` or `renderer.panel()`.
   - In `cli/ui.py`:
     - Add `renderer.set_machine_mode(enabled=True)` disabling all animations.
     - `loading()` → no-op in machine mode.
     - `panel()`, `section()` → plain text without markup.
2. Route progress to stderr:
   - Add `renderer.progress(message, *, file=sys.stderr)`.
   - Handlers call `progress()` instead of writing to stdout.
   - `print_json_payload()` verifies stdout has no parasitic bytes before JSON.
3. Inject streams into slash parsers:
   - Replace `sys.stderr` direct writes with `self.stderr` injected.
   - Argument errors and functional refusals go through the same channel.
4. Fake-TTY regressions:
   - Add tests simulating stdout attached to a TTY (mock `os.isatty()`).
   - Verify `--json` on TTY produces `{` as first useful byte.
   - Verify `--quiet` on TTY produces nothing on stdout.
5. Verify all surfaces:
   - Top-level: `loopforge run --json`, `loopforge verify --json`,
     `loopforge status --json`.
   - Slash shell: `shell --command "/status --json"`.
   - `--plain` stays clean (no ANSI leaks to stdout when piped).

**Tests**:
- `tests/test_cli.py` additions:
  - `test_json_output_no_spinner_on_fake_tty`
  - `test_quiet_output_empty_stdout`
  - `test_csv_output_no_color_codes`
  - `test_progress_on_stderr_not_stdout`
  - `test_slash_parser_errors_on_stderr`
- `tests/test_cli_structure.py` additions:
  - `test_json_payload_pure_stdout`

**Exit criteria**: AE7 passes. All `--json`, `--csv`, `--quiet` outputs are
free of spinner/color/human text on stdout. Human progress is exclusively on
stderr.

---

### Subtask 1.6 — Integration, smoke tests, and exit gate

**Objective**: Assemble all subtasks, run regression tests, validate epic
scenarios, and document the exit.

**Work items**:
1. Run full suite: `python -m unittest discover -s tests -p "test_*.py"` → 100%.
   Fix any regressions introduced by subtasks.
2. Execute manual validation scenarios:
   - Malicious/invalid IDs and absolute/`..` paths → no out-of-root effect.
   - Untrusted pack → never starts a process.
   - Secrets/proxy variables absent from child environment.
   - Infinite stdout bounded, process tree terminated after timeout.
   - Selecting run B + archiving → only B mutated after confirmation.
   - Cancellation before commit → nothing changes; after commit → real result.
   - JSON/CSV/quiet clean on real and fake TTY.
   - Windows and POSIX process behavior covered.
3. Reconcile existing issues:
   - #17 (compatibility shell output leaking): verify injected streams fix it.
   - #18 (adapter selector): document if unresolved for Epic 3/4.
   - #21 (Codex sandbox Windows): verify `ProcessRunner` handles Windows Job
     Objects; document residual limitations.
4. Document exit on issue #27:
   - List each subtask with status.
   - List each merged PR.
   - Test results: count, platforms tested.
   - Validation scenario results.
   - Known residual risks.
   - Verification command: `python -m unittest && git diff --check`.
5. Verify plan boundaries:
   - No new wizard, pack, or screen.
   - `loopforge.cli:main` stable.
   - `--plain`, `shell --command`, `shell --script`, JSON/CSV compatible.

**Verification commands**:
```bash
python -m unittest
python -m unittest tests.test_path_resolvers tests.test_process_runner
python -m unittest tests.test_engine_services
python -m unittest tests.test_cli_structure tests.test_cli_textual_app
git diff --check
pip install dist/*.whl
loopforge version
loopforge pack list
loopforge doctor
```

**Exit criteria (gate)**:
- No known out-of-root read/write path in project/run/pack/evidence flows.
- No untrusted local pack can execute.
- All subprocess execution paths use the trusted runner or have a documented,
  tested exception.
- No mutation can target a resource different from the confirmed `ActionScope`.
- Machine-output contract tests pass in TTY and redirected modes.
- Final evidence comment on issue with fixes, Windows + POSIX results.

---

## Dependency Graph

```
1.1 (Path confinement) ──┬── 1.2 (Pack trust)
                         │
                         ├── 1.4 (Mutation targeting)
                         │
                         └── (foundation for all)

1.3 (Process runner) ──── (independent of 1.2, depends on 1.1 for paths)

1.5 (Machine output) ──── (independent of 1.2/1.4, co-dependent with 1.3)

1.6 (Integration) ─────── (last, depends on all)
```

**Parallelization**: 1.2 and 1.3 can proceed in parallel after 1.1.
1.4 and 1.5 can also proceed in parallel. 1.6 is always last.

---

## Summary Table

| # | Subtask | Primary files | New files | Tests | Order |
|---|---------|--------------|-----------|-------|-------|
| 1.1 | Path confinement | `projects.py`, `engine/__init__.py`, `interactive.py` | `engine/path_resolvers.py` | `test_path_resolvers.py`, +existing | 1st (foundation) |
| 1.2 | Pack trust | `packs.py`, `engine/__init__.py`, `app.py` | `engine/pack_trust.py` | `test_engine_services.py`, `test_cli.py` | 2nd (after 1.1) |
| 1.3 | Process runner | `isolated_process.py`, `engine/__init__.py` | `engine/process_runner.py` | `test_process_runner.py`, `test_cli.py` | 2nd/3rd (after 1.1) |
| 1.4 | Mutation targeting | `app.py`, `operations.py`, `engine/__init__.py` | None (dataclass inline) | `test_cli_textual_app.py`, `test_engine_services.py` | 3rd (after 1.1) |
| 1.5 | Machine output | `workflow.py`, `ui.py`, `__init__.py`, `interactive.py` | None | `test_cli.py`, `test_cli_structure.py` | 3rd (independent) |
| 1.6 | Integration | `tests/`, docs | None | Full suite | 6th (last) |

## Related Artifacts

- Parent roadmap: `docs/plans/2026-07-22-001-refactor-loopforge-product-hardening-plan.md`
- GitHub issue: https://github.com/Loe159/LoopForge/issues/27
- Parent roadmap issue: https://github.com/Loe159/LoopForge/issues/25
- Existing issues: #17, #18, #21
- Module map: `docs/agent/01-modules.md`
- Coding patterns: `docs/agent/03-coding-patterns.md`
- Reuse catalog: `docs/agent/04-reuse-catalog.md`