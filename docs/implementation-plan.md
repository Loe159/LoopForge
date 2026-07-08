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

Status: completed on 2026-07-07.

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

- [x] `loopforge init` creates local config/templates.
- [x] `loopforge run --task` creates a run directory.
- [x] `loopforge status` prints current loop, profile, next step, and blockers.

Implementation notes:

- The package exposes the `loopforge` console script through `pyproject.toml`.
- `init` is idempotent and stores project config in `.loopforge/config.json`.
- `run --task` creates external run artifacts under
  `~/LoopForge/runs/<project-name>/<run-id>/`, with `LOOPFORGE_HOME` available
  for isolated tests.
- `status` handles not-initialized, initialized-without-run, current-run, and
  missing-run-metadata states.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes; editable install plus `loopforge status` also works in a temporary
  virtual environment. `pytest` was not available in the local environment.

## Phase 2: Universal Run Model

Status: completed on 2026-07-07.

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

- [x] new runs do not require GitHub;
- [x] existing imported validators can still validate the legacy artifacts;
- [x] `loopforge status` explains both native and legacy artifact state.

Implementation notes:

- The native run model uses `task_id` as the stable product identifier and keeps
  `base_commit` optional when the target project is not a Git checkout.
- Native run files live at the run root, while compatibility artifacts for the
  imported `.agent` validator live under `artifacts/legacy-agent/` so the legacy
  contract does not reject LoopForge-native Markdown files.
- `run.json` records the generated legacy numeric `issue`, its source, the
  legacy base commit, the legacy artifact directory, and the validator path.
- For non-Git projects, the legacy artifact mirror uses an explicit synthetic
  zero SHA only to satisfy the imported validator's historical full-SHA rule;
  the native `base_commit` remains `null`.
- `loopforge status` now reports native artifact completeness separately from
  legacy artifact validity.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes, including a direct call to `.agent/checks/validate_artifacts.py`
  against generated legacy artifacts.

## Phase 3: Loop Design Contract

Status: completed on 2026-07-07.

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

- [x] every `run` creates a loop contract;
- [x] `continue` refuses to run without success checks;
- [x] subjective work asks for a rubric before autonomous attempts.

Implementation notes:

- `loopforge run` now renders a structured `loop.md` contract with objective,
  scope, inputs, selected pack, selected skills, allowed tools, success checks,
  limits, stagnation rule, rollback strategy, and human-review conditions.
- `run.json` stores only the indexable contract summary: contract path, version,
  status, subjective-work detection, rubric requirement, and success checks.
- `loopforge run` accepts `--success-check`, `--skill`, `--allow-tool`,
  `--max-attempts`, `--timeout`, and `--rubric` so a run can be designed at
  creation without adding a larger planning framework.
- `loopforge status` reports loop-contract validity, success-check count,
  subjective-work detection, and rubric presence alongside native and legacy
  artifact state.
- `loopforge continue` is a Phase 3 pre-execution gate: it validates the
  current `loop.md`, refuses missing success checks, and refuses autonomous
  subjective work without a rubric. Successful validation stops at the Phase 4
  adapter boundary.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes with tests for generated contracts, missing success checks, and
  autonomous subjective rubric handling.

## Phase 4: Adapter Execution

Status: completed on 2026-07-07.

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

- [x] `loopforge continue --adapter codex` can execute a bounded attempt;
- [x] stdout/stderr are captured;
- [x] workspace changes are detected;
- [x] the attempt summary is appended to `progress.md`;
- [x] failures produce a readable blocked state.

Implementation notes:

- `loopforge continue` still supports a validation-only mode when no adapter is
  passed, preserving the Phase 3 contract gate.
- `loopforge continue --adapter <adapter> -- <args...>` now creates a bounded
  attempt under `RUN/attempts/attempt-NNN/` with `expected-session.json`,
  `attempt.json`, `adapter.stdout`, `adapter.stderr`, and `result.json`.
- Real agent adapters (`codex`, `claude-code`, `aider`, `opencode`, and
  `mini-swe-agent`) are routed through the imported
  `.agent/adapters/local_implementation_adapter.py`, which uses the imported
  isolated child environment policy.
- The `local-adapter-fixture` adapter executes a shell-free command through the
  imported isolated process helper so tests can deterministically exercise
  output capture, workspace-change detection, and blocked states without
  requiring an installed agent CLI.
- The missing imported result validator has been restored at
  `.agent/checks/validate_implementation_result.py`, keeping the imported local
  adapter runnable.
- The imported local adapter's clean-workspace check ignores LoopForge runtime
  metadata under `.loopforge/`, so `loopforge init` and `loopforge run` do not
  block the first adapter attempt while unrelated workspace changes still do.
- Successful attempts update `run.json` to `ready_for_verification`; blocked or
  failed attempts update `run.json` to `adapter_blocked` with a readable blocker
  and append the attempt summary to `progress.md`.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes, including fixture tests for completed and failed adapter attempts and
  imported-adapter clean-workspace handling.

## Phase 5: Verification And Patch Flow

Status: completed on 2026-07-07.

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

- [x] `loopforge verify` generates a patch for changed workspaces;
- [x] diff policy and risk classification are shown in `status`;
- [x] pack verification commands can be configured without editing engine code.

Implementation notes:

- `loopforge verify` now runs the imported complete-patch generator, diff
  policy validator, and risk classifier against the current run's Git
  `base_commit`, storing the patch under `RUN/artifacts/patches/complete.patch`.
- Verification results are written to `run.json` and `verification.md`,
  including patch path, patch size, diff-policy verdict, risk route, pack-check
  results, blockers, and the latest loop diagnostic in `loop.md`.
- `loopforge status` reports verification status, patch size, diff-policy
  allowance, risk level, pack-check pass count, and stagnation state when
  present.
- Pack verification commands are loaded from
  `.loopforge/packs/<pack-name>/checks.json` or
  `.loopforge/packs/<pack-name>.checks.json`, with repository-local pack files
  overriding bundled defaults.
- The bundled `generic-code` pack starts with a shell-free `git diff --check`
  verification command.
- Repeated equivalent verification failures record a stable failure signature
  and mark the run as stagnated on the next matching failure.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes with tests for patch generation, diff policy/risk status, pack checks,
  and repeated verification failure stagnation.

## Phase 6: Memory

Status: completed on 2026-07-07.

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

- [x] `loopforge learn` proposes memory updates;
- [x] durable memory changes are reviewable;
- [x] a new run can load compact durable memory without loading old transcripts.

Implementation notes:

- `loopforge init` creates durable project memory at `.loopforge/memory.md`.
- New runs render `RUN/memory.md` as a compact snapshot of durable memory
  sections and intentionally omit promotion logs and old transcripts.
- `loopforge learn` writes reviewable proposals to
  `RUN/artifacts/memory/proposals.json` and `proposals.md`.
- Promotion requires `loopforge learn --approve` or a pack-defined
  `memory-rules.json` auto-promotion rule; secrets and raw untrusted
  issue/comment/body text are rejected before promotion.
- Durable promotions append both the selected memory item and a Promotion Log
  entry with source and approval/rule evidence.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes with tests for durable memory initialization, compact run snapshots,
  scratch/exchange proposals, approved promotion, and secret rejection.

## Phase 7: Project Packs

Status: completed on 2026-07-07.

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

- [x] project detection selects a pack;
- [x] packs contribute checks and risk rules;
- [x] packs can add skills without changing the engine.

Implementation notes:

- Packs now use a product contract made of `pack.json`, `SKILL.md`,
  `checks.json`, `protected-paths.json`, and `memory-rules.md`.
- The bundled initial packs are `generic-code`, `python`, `node`,
  `documentation`, and `intellij-plugin`; project-local packs under
  `.loopforge/packs/<pack-name>/` override bundled packs with the same name.
- `loopforge run` auto-detects the pack from repository markers, records the
  resolved pack contract in `run.json`, and supports `--pack` for an explicit
  override.
- `loopforge pack list` and `loopforge pack detect` expose available packs and
  the selected pack without requiring a run.
- Pack skills are added to `loop.md` from `pack.json` and `SKILL.md`, so new
  packs can contribute skills without engine changes.
- Pack checks continue to come from `checks.json`, while
  `protected-paths.json` is merged with the imported risk policy into
  `RUN/artifacts/policies/risk-rules.merged.json` during verification.
- Pack memory rules preserve `memory-rules.json` compatibility and can also be
  provided through `pack.json` while `memory-rules.md` documents human-facing
  promotion guidance.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes with tests for auto-detection, project-local pack skills, pack CLI
  listing/detection, pack risk-rule contribution, and existing check loading.
- Revalidated on 2026-07-08: the full unit suite still passes, `loopforge pack
  list` reports the five initial packs, and `loopforge pack detect` selects the
  Python pack for this repository.

## Phase 8: Autonomy Profiles

Status: completed on 2026-07-08.

Implement four profiles:

- `assist`: no mutation;
- `supervised`: mutation allowed, review before major transitions;
- `autonomous`: bounded attempts continue when checks are objective;
- `strict`: explicit confirmation before mutation and memory promotion.

Done when:

- [x] profile is stored in `run.json`;
- [x] each command reports what the profile allows;
- [x] autonomous mode stops on unclear success criteria, repeated failure,
  publication, deletion, secrets, money, or external side effects.

Implementation notes:

- Autonomy profiles are normalized through a shared engine policy and stored in
  both project config and new `run.json` files, including a readable
  `profile_policy` summary for each run.
- CLI and interactive outputs now report profile permissions for initialization,
  run creation, status, continuation, verification, and learning flows.
- `assist` blocks adapter execution, verification artifact generation, and
  durable memory promotion while still allowing review-oriented LoopForge
  bookkeeping.
- `strict` requires `--confirm` before adapter execution, verification, and
  durable memory promotion; the interactive shell can ask for confirmation only
  in interactive mode.
- `autonomous` allows bounded adapter attempts only when the loop contract has
  objective success checks, subjective work has a rubric, stagnation has not
  occurred, and the task/contract does not request publication, deletion,
  secrets, money, network, or external side effects.
- Adapter protocol results that request publication or network/external side
  effects keep autonomous runs in a blocked human-review state instead of moving
  them to verification.
- Guided actions respect the selected profile: assist recommends review,
  autonomous can recommend an unconfirmed bounded attempt only when stop
  conditions are clear, and strict marks mutating transitions as requiring
  confirmation.
- Current validation: `PYTHONPATH=src python -m unittest discover -s tests`
  passes with 58 tests, including coverage for assist blocking adapter
  execution, autonomous publication stop conditions, and strict confirmation for
  verification and memory promotion.

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
