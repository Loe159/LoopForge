# Product Architecture

LoopForge has four layers.

## 1. CLI

The CLI is the user experience:

```text
loopforge init
loopforge run
loopforge status
loopforge continue
loopforge verify
loopforge learn
```

It should explain the next action in plain language and avoid exposing internal
receipt chains unless the user asks for details.

## 2. Engine

The engine owns:

- run discovery;
- loop contracts;
- attempt state;
- adapter invocation;
- verification;
- memory promotion;
- metrics.

## 3. Packs

Packs make the engine useful for specific project types. They provide:

- detection;
- reusable skill definitions;
- named agents and prompts;
- permission sets;
- an ordered, gated workflow;
- deterministic commands and risk paths;
- memory rules.

`generic-code` owns the base development workflow. Domain packs inherit it and
add language- or project-specific skills and checks. `PackRegistry` resolves
inheritance, validates agent/permission/workflow references, and persists the
effective contract into each run.

## 4. Compatibility Launchers

The `.agent/checks/` and `.agent/adapters/` paths are thin compatibility
launchers for packaged runtime modules. Product code and contracts live under
`src/loopforge/`; the former standalone bootstrap implementation was removed.

## Data Flow

```text
task validation + approval
  -> selected effective pack
  -> researcher / research.md
  -> planner / plan.md + approval
  -> developer / isolated workspace
  -> deterministic patch and checks
  -> reviewer / review.md + approval
  -> local draft publication artifact
```

## Main Product Tension

LoopForge should optimize for autonomy and flow, but every autonomous action
must still be bounded by explicit loop limits and visible evidence.
