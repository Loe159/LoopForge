---
name: loopforge-tui-refinement
description: Design, build, test and iterate on a LoopForge Textual screen or component with explicit mockup approval, one-component scope, real terminal previews, keyboard/responsive tests, isolated commits and user visual sign-off.
---

# LoopForge TUI refinement

Use this skill whenever a request creates, redesigns, polishes or fixes **visual or interactive** elements of the LoopForge Textual console.

**First read:** `AGENTS.md`, `DESIGN.md`, `docs/agent/08-iterative-tui-design.md`, and the related `docs/agent/` conventions. This is a **repository-maintainer skill**; do not insert it into `src/loopforge/packs/` or modify a runtime agent workflow.

## Mandatory sequence

1. **Audit:** inspect the current widget, TCSS, state/projector, source data, existing UI tests and screen constraints. Preserve engine and permission boundaries.
2. **Decompose:** break the requested screen into small independent components and identify one next component.
3. **Mockup:** offer 2–3 terminal-native variants with explicit keyboard/mouse behavior and narrow/wide behavior. Recommend one; do not code.
4. **Approval gate:** require the user's explicit variant or adjustment acceptance. Record it and out-of-scope features.
5. **Build:** change only the approved component. Reuse existing state/actions/styles; no parallel renderer, speculative evidence or fake metrics.
6. **Test:** run focused `unittest` tests plus neighboring regressions; execute real Textual/Pilot interaction and screenshot inspection at applicable 48/60/80/120/160 columns (especially 60 and 80), with a short-height case and resize tests. Check contrast, truncation, arrow keys, parent navigation, input focus and source provenance.
7. **Commit:** `git diff --check`, `python -m compileall -q src`, full tests as feasible and required by project policy. Stage only related files. Create a local commit; no push without instruction. Never claim tests that timed out passed.
8. **Visual gate:** provide a runnable demo command and wait for the user to try and approve it. If defects remain, fix one issue, test and commit again. **Do not advance to the next component until visual acceptance.**

## Checklist before reporting done

- [ ] The user selected the design before implementation.
- [ ] Only the approved UI surface changed (or a dependency was explicitly authorized).
- [ ] Real Textual screenshots and measurements were inspected at narrow and wide sizes.
- [ ] Keyboard navigation, mouse, focus, state refresh, and responsive resizing were checked.
- [ ] Empty, loading, long content, truncation and failure states are honest and usable.
- [ ] Engine truth, permissions, verification evidence and approval authority are unchanged.
- [ ] Tests actually passed; timeouts and unrun checks are reported.
- [ ] A focused commit exists; no push or publication without permission.
- [ ] User visual validation is pending or explicitly recorded.

For the full decision process, test matrix and deliverables, see `docs/agent/08-iterative-tui-design.md`.
