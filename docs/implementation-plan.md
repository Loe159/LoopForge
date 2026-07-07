# LoopForge Implementation Plan

This plan turns the imported ABL workflow core into a general-purpose agentic
workflow product.

## Product Goal

LoopForge should run repeatable work loops across many projects:

```text
trigger -> context intake -> loop design -> agent attempt -> verification
        -> memory update -> next action or human review
```

The engine should feel ergonomic first. Safety remains present as bounded
execution, visible evidence, rollback, and review points, not as dozens of
operator-facing gates.

## Guiding Decisions

- Start with a CLI, not a web UI.
- Keep run artifacts outside target repositories by default.
- Use project packs for domain-specific behavior.
- Keep imported `.agent/**` scripts as bootstrap primitives until replaced.
- Support multiple agent CLIs through adapters.
- Make autonomy configurable by profile.
- Promote durable memory only through an explicit rule.

## Architecture Target

```text
LoopForge
  CLI
    init
    run
    status
    continue
    verify
    learn
    pack
  Engine
    run store
    loop planner
    attempt runner
    verifier
    memory manager
    adapter registry
  Project packs
    generic-code
    python
    node
    docs
    intellij-plugin
  Imported bootstrap core
    patch generation
    diff policy
    risk classification
    artifact validation
    isolated process
    local implementation adapter
    metrics
```

## Phase 0: Repository Bootstrap

Status: started.

Deliverables:

- `README.md`
- `AGENTS.md`
- `agent.md`
- `.loopforge/templates/`
- `.loopforge/packs/`
- `.loopforge/skills/`
- selected `.agent/**` imports
- this plan

Validation:

- imported scripts respond to `--help`;
- artifact templates validate;
- no ABL-specific prompt remains in active generic prompts.

## Phase 1: Minimal CLI

Create a Python package with a console command:

```text
loopforge init
loopforge status
loopforge run --task "..."
```

Implementation notes:

- Use `argparse` first; avoid framework lock-in.
- Store config in `.loopforge/config.json`.
- Default external run root:
  `~/LoopForge/runs/<project-name>/<run-id>/`.
- Generate `loop.md`, `memory.md`, `scratch.md`, and `exchange.json`.
- Detect Git base commit when inside a Git repo.

Done when:

- `loopforge init` creates local config/templates.
- `loopforge run --task` creates a run directory.
- `loopforge status` prints current loop, profile, next step, and blockers.

## Phase 2: Universal Run Model

Define a product-native run layout:

```text
RUN/
  run.json
  task.md
  loop.md
  plan.md
  progress.md
  verification.md
  memory.md
  scratch.md
  exchange.json
  attempts/
  artifacts/
  metrics/
```

Keep compatibility with imported artifact templates, but stop requiring every
task to be a numeric GitHub issue. Introduce `task_id` while mapping legacy
`issue` where needed.

Done when:

- new runs do not require GitHub;
- existing imported validators can still validate the legacy artifacts;
- `loopforge status` explains both native and legacy artifact state.

## Phase 3: Loop Design Contract

Implement `loop.md` as the central work contract.

Required fields:

- objective;
- scope;
- inputs;
- selected project pack;
- selected skills;
- allowed tools;
- success checks;
- max attempts;
- timeout;
- stagnation rule;
- rollback strategy;
- human-review conditions.

Done when:

- every `run` creates a loop contract;
- `continue` refuses to run without success checks;
- subjective work asks for a rubric before autonomous attempts.

## Phase 4: Adapter Execution

Reuse the imported local adapter and isolated process as the first execution
path.

Initial adapters:

- Codex;
- Claude Code;
- Aider;
- OpenCode;
- mini-swe-agent;
- generic shell-free local command fixture for tests.

Done when:

- `loopforge continue --adapter codex` can execute a bounded attempt;
- stdout/stderr are captured;
- workspace changes are detected;
- the attempt summary is appended to `progress.md`;
- failures produce a readable blocked state.

## Phase 5: Verification And Patch Flow

Reuse:

- `generate_complete_patch.py`;
- `diff_policy.py`;
- `classify_patch_risk.py`;
- project-pack verification commands.

Product behavior:

- small code changes get patch generation automatically;
- quality checks come from the selected pack;
- failures update the loop diagnostic;
- repeated equivalent failures trigger stagnation.

Done when:

- `loopforge verify` generates a patch for changed workspaces;
- diff policy and risk classification are shown in `status`;
- pack verification commands can be configured without editing engine code.

## Phase 6: Memory

Implement three memory layers:

- durable project memory: stable facts and decisions;
- run scratch memory: temporary context;
- exchange memory: structured handoffs between skills/adapters.

Promotion rules:

- never promote secrets;
- never promote raw untrusted issue/comment/body text;
- require either human approval or a pack-defined rule;
- record a promotion log entry.

Done when:

- `loopforge learn` proposes memory updates;
- durable memory changes are reviewable;
- a new run can load compact durable memory without loading old transcripts.

## Phase 7: Project Packs

Create pack contract:

```text
pack.json
SKILL.md
checks.json
protected-paths.json
memory-rules.md
```

Initial packs:

- `generic-code`;
- `python`;
- `node`;
- `documentation`;
- `intellij-plugin`;
- later: `abl-plugin` migrated from the old project.

Done when:

- project detection selects a pack;
- packs contribute checks and risk rules;
- packs can add skills without changing the engine.

## Phase 8: Autonomy Profiles

Implement four profiles:

- `assist`: no mutation;
- `supervised`: mutation allowed, review before major transitions;
- `autonomous`: bounded attempts continue when checks are objective;
- `strict`: explicit confirmation before mutation and memory promotion.

Done when:

- profile is stored in `run.json`;
- each command reports what the profile allows;
- autonomous mode stops on unclear success criteria, repeated failure,
  publication, deletion, secrets, money, or external side effects.

## Phase 9: Metrics

Reuse and simplify imported metrics recording.

Track:

- run duration;
- adapter;
- model;
- attempt count;
- token/cost status when available;
- patch size;
- verification result;
- human correction count;
- final disposition.

Done when:

- `loopforge metrics record` writes a compact JSON record;
- `loopforge metrics summarize` compares runs without treating unknowns as
  zero.

## Phase 10: Local UI

Build only after the CLI proves the model.

Dashboard views:

- run list;
- current loop;
- attempts;
- verification;
- memory proposals;
- adapter comparison;
- next human action.

Done when:

- UI calls the CLI or engine API;
- it does not bypass loop limits, checks, or memory rules.

## What Not To Port Yet

- historical golden set adoption;
- GitHub issue ingestion as the default path;
- draft PR publication;
- very granular authorization receipt chains;
- ABL/Proparse-specific research rules;
- claims about full sandbox or network isolation.

These can return later as optional packs or enterprise controls.

## First Working Milestone

Milestone name: `mvp-local-loop`.

Goal:

Build the MVP as a sequence of vertical CLI increments. Each increment must be
observable through a user command and testable in a temporary repository in a
few minutes or less. The workflow is:

```text
init -> run -> status -> verify -> learn
```

This milestone does not include autonomous agent execution.

Starting point:

- `pyproject.toml` already exposes the `loopforge` command.
- `src/loopforge/cli.py` is still a placeholder.
- `.loopforge/templates/` contains the loop, memory, scratch, and exchange
  templates.
- `.agent/checks/generate_complete_patch.py`, `.agent/checks/diff_policy.py`,
  and `.agent/checks/classify_patch_risk.py` are available as bootstrap
  primitives.

Vertical increments:

1. Real CLI and `init`
   - User result: `loopforge init` creates usable project configuration.
   - Implementation: add a small engine layer for config, paths, and atomic
     JSON writes. Write `.loopforge/config.json` with `project_name`,
     `profile`, `run_root`, and `current_run_id: null`. Keep the command
     idempotent.
   - Quick test: in a temporary repository, run `main(["init"])`, verify the
     config, run it again, and verify it does not destructively overwrite
     existing configuration.

2. External run creation
   - User result: `loopforge run --task "..."` creates a run outside the
     target repository.
   - Implementation: use `~/LoopForge/runs/<project>/<run-id>/` by default,
     with `LOOPFORGE_HOME` as a test override. Create `run.json`, `task.md`,
     `loop.md`, `memory.md`, `scratch.md`, `exchange.json`, `attempts/`,
     `artifacts/`, and `metrics/`. Detect `git rev-parse HEAD` when possible
     and store `current_run_id` in config.
   - Quick test: in a temporary Git repository with `LOOPFORGE_HOME` set, run
     `init` and `run`, then verify the run is external and the target
     repository only receives `.loopforge/config.json`.

3. Filled loop contract
   - User result: the run contains a readable `loop.md`, not an empty
     template.
   - Implementation: fill objective, inputs, repository, base commit, default
     pack `generic-code`, profile `supervised`, default limits, and rollback
     guidance. Add repeatable `run --success-check "..."`. Without success
     checks, mark the run as blocked for clarification in `run.json`.
   - Quick test: `run --task ... --success-check ...` produces a `loop.md`
     without critical placeholders; running without success checks makes
     `status` report the blocker.

4. Useful `status`
   - User result: `loopforge status` explains the current run and next action.
   - Implementation: discover the current run from `.loopforge/config.json`,
     read `run.json` and artifacts, and print run id, task, profile, loop
     status, base commit, next step, blockers, and patch/verification/memory
     proposal presence. Handle not initialized and no current run states.
   - Quick test: assert stdout for not initialized, initialized without run,
     run with success checks, and run without success checks.

5. Patch and policy verification
   - User result: `loopforge verify` produces local evidence for a modified
     repository.
   - Implementation: add `verify` to the CLI. Generate
     `artifacts/changes.patch` through
     `.agent/checks/generate_complete_patch.py --repo <repo> --base <base>`.
     Run `diff_policy.py` and `classify_patch_risk.py` in JSON mode. Write
     `verification.md` with the result, risk, artifact paths, and readable
     errors. Do not stage Git changes or mutate source files.
   - Quick test: in a temporary Git repository, make an initial commit, modify
     a file, run `run` then `verify`, and verify the external patch,
     `verification.md`, and zero exit code. The no-change case must report a
     clear status instead of an opaque failure.

6. Manual memory proposal
   - User result: `loopforge learn --proposal "..."` records a proposed memory
     item without durable promotion.
   - Implementation: add
     `learn --proposal TEXT --category stable-fact|preference|verification-pattern|decision|pitfall`.
     Append an entry to the run `memory.md` under `Proposed Durable Memory`
     with timestamp, category, text, and status `proposed`. Do not write to
     project durable memory in this milestone.
   - Quick test: run `learn`, verify the entry in `RUN/memory.md`, and verify
     `.loopforge/config.json` and templates are not polluted.

7. Full MVP smoke test
   - User result: the full local flow completes quickly.
   - Implementation: add an integration test that runs
     `init -> run -> status -> verify -> learn -> status` against a temporary
     repository. Keep tests offline and isolate the external run root with
     `LOOPFORGE_HOME`.
   - Quick test: `python -m pytest` should complete in a few seconds.

Interfaces:

- `loopforge init`
- `loopforge run --task TEXT [--success-check TEXT ...]`
- `loopforge status`
- `loopforge verify`
- `loopforge learn --proposal TEXT --category CATEGORY`
- `LOOPFORGE_HOME`: override for the external run root during tests.

Minimal `run.json` fields:

- `run_id`
- `task_id`
- `task`
- `project_root`
- `base_commit`
- `profile`
- `pack`
- `status`
- `created_at`
- `success_checks`
- `blockers`
- `artifacts`

MVP statuses:

- `ready_for_verification`
- `blocked_missing_success_checks`
- `verified`
- `verification_failed`
- `memory_proposed`

Acceptance criteria:

- Tests use temporary directories and do not touch the real `~/LoopForge`.
- Commands do not require GitHub, network access, autonomous agents,
  publication, Git staging, or destructive mutation.
- Run artifacts are created outside the target repository by default.
- Bootstrap scripts remain callable as external processes; `.agent/**` is not
  moved or deleted.
- `status` always explains the next step in plain language, including
  incomplete states.

Defaults and assumptions:

- The default MVP pack is `generic-code`.
- MVP memory is only a proposal in the current run; no durable memory promotion
  happens automatically.
- `verify` is limited to patch generation, diff policy, and risk
  classification. Pack checks are not required for `mvp-local-loop`.
- `continue` and agent adapter invocation are out of scope for this milestone.

Compact scope:

1. Package skeleton and `loopforge` command.
2. External run creation.
3. Loop contract generation.
4. Status command.
5. Patch generation and diff policy over a sample repo.
6. Manual memory proposal.

This milestone should be useful before any autonomous agent execution exists.
