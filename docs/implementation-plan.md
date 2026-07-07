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
