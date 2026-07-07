# LoopForge Agent Rules

LoopForge is a general-purpose agentic workflow engine. Keep the project
portable, ergonomic, and honest about autonomy.

## Direction

- Prefer a small working CLI over a large policy framework.
- Keep reusable engine code separate from project-specific packs.
- Treat imported `.agent/**` files as bootstrap core until they are refactored
  into the LoopForge package.
- Preserve deterministic checks for patch generation, risk classification,
  process isolation, artifacts, and metrics.
- Do not turn receipts, validation, or metrics into publication authority.

## Architecture

- `agent.md`: operator-facing system contract.
- `.loopforge/templates/`: product templates for loop, memory, scratch, and
  exchange files.
- `.loopforge/packs/`: project-specific rules and verification adapters.
- `.loopforge/skills/`: reusable task skills loaded on demand.
- `.agent/`: imported bootstrap implementation from the ABL workflow.
- `docs/`: product plans, migration notes, and design records.

## Change Rules

- Keep imported scripts runnable while refactoring.
- Add focused tests when changing Python behavior.
- Avoid hidden network, publication, or destructive filesystem actions.
- Keep generated run artifacts outside the repository by default.
- Preserve unrelated working-tree changes.
