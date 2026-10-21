---
name: tui-component-iteration
description: Iteratively create or redesign LoopForge Textual screens and components with terminal-native mockups, explicit user design approval, bounded implementation, pilot tests, local commits, and user visual sign-off. Use for any substantial TUI layout, interaction, Run/Live or Changes UI request.
---

# LoopForge — iterative TUI component design

This is a **developer/agent skill**, not a bundled runtime pack skill. Apply it
when a user asks to create, polish, refactor or redesign a Textual screen,
panel, component, terminal layout, navigation or diff viewer.

Before working, read:
- `AGENTS.md` and `DESIGN.md`;
- `docs/agent/09-tui-component-iteration.md` (the canonical playbook);
- `docs/agent/03-coding-patterns.md`, `05-how-to-add-feature.md`,
  `06-build-test-run.md` and `07-danger-zones.md`;
- the screen's existing implementation, presenter, state and tests.

## Mandatory gates

**Discover → decompose → mock up → wait for user choice → implement one
approved component → test and demo → small commit → wait for user visual
approval → next mockup.**

1. **Discovery:** list screen components, contracts, authoritative data,
   focus/keyboard ownership, controls, responsive breakpoints and reusable code.
2. **Prototype:** give concrete A/B terminal-native mockups (unless a single
   approach is justified), compare compromises, specify keyboard and mouse
   behavior, include relevant failure/empty/loading states. Do **not** modify
   production UI yet.
3. **Design gate:** explicitly ask for the preferred mockup/adjustments. Never
   treat feedback on one component as approval for another component.
4. **Implementation:** only after approval, implement the selected component
   using current Textual/widgets/presenters/styles. Preserve other working-tree
   edits, headless paths, engine contracts, provenance and review authority.
5. **Verification:** write tests for rendering, state, interactions, boundaries
   and responsive sizes. Use real Textual `run_test` with arrow keys, Enter,
   clicks, resize and focus checks. Check 48/52/60/80/100/120/160-column
   cases and ~24-row terminals where meaningful; visually inspect screenshot
   evidence. Use reproducible synthetic TUI demos under `tools/` as helpful,
   without treating demo data as real evidence.
6. **Commit and report:** run relevant tests, attempt full suite, compile and
   `git diff --check`. Do not invent results when environment is unavailable.
   Commit the approved change locally; report SHA and precise check outcomes.
   **Do not push unless requested**.
7. **Visual acceptance gate:** provide preview instructions, request screenshot
   or explicit approval, incorporate fixes as new tested commits and re-review.
   Mark the component accepted *only* after confirmation; only then propose
   the next component's mockups.

## Specific protections

- **No implementation before mockup selection. No next component before visual
  sign-off.**
- Keep approved scope strict; avoid incidental changes to neighboring screens,
  adapter execution, approval gates, persistence, or publishing.
- Preserve focus and visible command access; verify narrow *and short* terminal
  layouts and breakpoint transitions, not only CSS width classes.
- Preserve syntax colors/contrast and ASCII fallback. A highlighted line must
  remain readable in Markdown, diff additions and diff deletions.
- Agent-declared edits do not prove workspace modifications. Render captured
  evidence as such; distinguish Attempt vs Run cumulative.
- If only GitHub is connected and the remote branch lacks newer local commits,
  use a **separate GitHub branch** for documentation or review changes; do not
  advance/overwrite remote `master` or imply that local tests ran.
- Record per-component status in `docs/plans/`: mockups, decision, tests,
  commit, user sign-off and next proposed component.

## Completion report

State the **component**, approved design and what changed; tests **actually
observed** (including timeouts and incomplete suites); commit/ref and push
status; exact demo/run command; and whether **visual acceptance is pending**.
