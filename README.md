# LoopForge

LoopForge is a portable agentic workflow engine. It turns a task into a bounded
work loop with context intake, loop design, agent execution, verification,
memory updates, and human review when the evidence is weak.

This repository starts from the reusable core of the ABL plugin workflow:
portable artifacts, patch generation, deterministic policy checks, bounded
process execution, local adapters, and metrics. The product direction is more
general and ergonomic: one engine, multiple project packs, explicit autonomy
profiles.

## MVP Shape

```text
loopforge init
loopforge run --task "..."
loopforge status
loopforge continue
loopforge verify
loopforge learn
```

## Imported Core

The initial import lives under `.agent/` to keep the proven scripts runnable
while the public CLI is designed. Important imported pieces:

- `.agent/checks/diff_policy.py`
- `.agent/checks/generate_complete_patch.py`
- `.agent/checks/classify_patch_risk.py`
- `.agent/checks/validate_artifacts.py`
- `.agent/checks/isolated_process.py`
- `.agent/checks/record_run_metrics.py`
- `.agent/adapters/local_implementation_adapter.py`
- `.agent/templates/`
- `.agent/prompts/`

## Product Principle

LoopForge should be more autonomous than the original pilot, but not opaque.
Every run should show:

- what goal is being pursued;
- which loop is active;
- what evidence proves progress;
- when the agent is stuck;
- what memory will be retained;
- what action, if any, needs a human decision.
