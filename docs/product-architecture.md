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
- commands;
- risk paths;
- skill routing;
- memory rules.

## 4. Bootstrap Core

The imported `.agent/**` layer supplies proven primitives while the engine is
being built. It is not the final public API.

## Data Flow

```text
task
  -> run.json
  -> loop.md
  -> selected pack
  -> selected skills
  -> adapter attempt
  -> patch/checks
  -> verification.md
  -> memory proposal
  -> next loop decision
```

## Main Product Tension

LoopForge should optimize for autonomy and flow, but every autonomous action
must still be bounded by explicit loop limits and visible evidence.
