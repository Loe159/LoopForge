# Iterative TUI screen and component workflow

This is the required design-to-validation workflow for **new LoopForge Textual screens and changes to existing screens**. It covers small widgets, major visual refactors, and responsive layouts. It is a maintainer workflow, **not** a LoopForge runtime pack skill.

Read `AGENTS.md`, `DESIGN.md`, `docs/agent/03-coding-patterns.md`, `docs/agent/04-reuse-catalog.md`, and `docs/agent/07-danger-zones.md` before modifying UI. Invoke the companion repository-agent skill at `.agents/skills/loopforge-tui-refinement/SKILL.md`.

## Non-negotiable gates

**No approval, no implementation.** Do not treat a proposed mockup, preference, or partial approval as permission to implement. The user must explicitly choose a visual direction or approve a clearly specified adjustment.

**One component per iteration.** Do not silently redesign adjacent widgets, other tabs, navigation, or the engine. Only address shared components when necessary for the approved change; explain the dependency first.

**Visual acceptance is separate from passing tests.** A committed component stays `implemented-awaiting-visual-review` until the user has tried the real TUI and approved it. Do not move to the next component just because unit tests pass.

**Every modification needs an isolated commit** after the applicable checks. Keep unrelated working-tree changes out of staging. Commit locally; do not push, merge, publish or close an issue unless explicitly instructed. A GitHub-only change must use an isolated branch/PR when remote `master` is behind unpushed local work.

## 0 — Understand the existing screen

1. Identify the user goal, context, exact surface(s), terminal interactions, source-of-truth data, and constraints (including what must remain unchanged).
2. Read the current `src/loopforge/cli/textual_app/` implementation and state projection, its styles, tests, `DESIGN.md`, and related UX decisions.
3. Map the screen into independently reviewable **components** (e.g. header, tool row, agent message, file event, diff viewer, tree). Note shared primitives, interactions, and dependencies.
4. Document the baseline and current defects; distinguish layout/visual defects from data/state bugs. Do not infer missing facts from an agent transcript or synthetic example.
5. Establish usable viewport sizes and environment constraints; a TUI is not a website. Preserve the command input, navigation context, accessibility, and keyboard ownership.

## 1 — Propose a component, not a finished implementation

For **one** component, show the current state/problem and **two or three genuinely different options** (unless the user asks for a single exact adjustment). Use compact terminal-like mockups or visual previews, not web-only cards. Show representative content and realistic long labels, error states, and terminal widths.

Each option must state:
- placement, hierarchy, density, colors, contrast, borders/rails and focus treatment, consistent with `DESIGN.md`;
- what a user can do by keyboard and mouse (especially expand/collapse, select, scroll, back/parent);
- behavior at narrow and wide viewports; do not equate a breakpoint class with actual available space;
- loading, empty, error, truncated or unavailable states where relevant;
- what data is authoritative and whether the UI is showing declarations, captured observations or verified evidence;
- compromises and a reasoned recommendation.

Wait for an **explicit user choice or approval**. Record the accepted variant, its constraints, and excluded features in the component plan. Do not present illustrative counts, timings, or contents as actual observed facts.

## 2 — Implement only the approved slice

1. Reuse existing Textual widgets, styles, application state, renderers, and action/engine interfaces; avoid parallel rendering and arbitrary ANSI escape codes.
2. Preserve source identity, provenance and scope: a harness file-change announcement is not a verified Git diff; `Attempt` and `Run cumulative` are different sources. Display `+/-`, paths, and code only when supported by the selected retained evidence.
3. Prefer semantic, concise labels. Keep live updates stable (selection/focus/scroll/expanded state) while snapshots refresh. Avoid reloading a synthetic demo from live storage.
4. Keep every control functional, keyboard-first and mouse-usable. Terminal layouts must preserve access to command input, primary navigation and blocking approvals.
5. Prefer data-driven layout measurements to large arbitrary responsive thresholds. Test actual pane dimensions; never silently hide a useful pane merely because a terminal is tagged `width-80`.
6. Supply or update an **isolated demo** with representative in-memory data, including a second/edge state. Synthetic data must be clearly labeled, never written to production run state.

## 3 — Test both behavior and appearance

Run tests in the repository's existing `unittest` conventions, including the narrowest relevant contract and adjacent regressions.

| Area | Minimum cases |
| --- | --- |
| Width/height | Terminal widths **48, 60, 80, 120, 160** when applicable; short terminal such as 24 rows and a normal-height terminal. Check measured dimensions, clipping, overflow and focus visibility. |
| Responsive | Resize during use across breakpoints in both directions; retain selection, disclosure state, scroll, command bar and interactive controls. |
| Input | Arrow keys, Enter, Esc/back, Tab, mouse, opening/closing parents, keyboard focus and scroll ownership. |
| Content | Long/nested paths, empty/no data, partial streaming, loading, failure/blocked, truncated and binary content, unknown or stale capture. |
| Readability | Light/dark terminal support as relevant, ASCII or `TERM=dumb` fallback, low-color output, code highlighting and contrast on added/deleted lines, quoted/inline Markdown text. |
| Truth/security | Native event vs workspace capture vs retained Git patch; current attempt vs cumulative run; no invented diffs, metrics, approvals or clickable untrusted links. |
| Regressions | Other screen views, ongoing streaming, approvals, command entry, tool output, state transitions, prior layouts and existing accessible actions. |

Run **real Textual/Pilot rendering**, not only model/serializer unit tests: use `App.run_test(size=(width, height))`, exercise interactions, and inspect/export actual screenshots. For complex responsive issues, validate **both** 60 and 80 columns and at least one wide screenshot. Don't assert only that a widget exists; assert its visibility, coordinates, viewport, focused state, content, and correct navigation result.

Required checks per `docs/agent/06-build-test-run.md` and `AGENTS.md`:

```text
python -m unittest
python -m compileall -q src
git diff --check
```

The repository policy asks for **two consecutive full-suite passes**. If tooling times out, run scoped groups, record exactly which ran, and state that the full suite is **unverified**; never turn a timeout into a pass. Fix failures before claiming acceptance.

## 4 — Commit, hand off, visually validate

1. Review `git diff` and `git status`; stage only intended source, tests, demo and plan files. Exclude screenshots/debug logs, generated files and other people's changes.
2. Create a descriptive Git commit for this component or corrective iteration. Do **not push** unless explicitly asked.
3. Report scope, tests/results/limitations, commit ID and the exact demo command. Ask the user to **visually validate in the real TUI**.
4. If the user reports a defect, modify only that issue, run relevant tests, create **another** commit, and request revalidation. Repeat until accepted.
5. Update the plan status to `visually-validated` only after user acceptance. Then propose mockups for the **next** component.

Suggested plan states: `proposed` → `approved-for-implementation` → `implemented-awaiting-visual-review` → `visually-validated`. Track each component and the accepted variants independently.

## Deliverables per component

- A documented chosen variant and explicit scope/out-of-scope.
- Reproducible visual demo, with synthetic data labeled as such.
- Functional and responsive test coverage, plus actual rendered screenshots inspected by the implementer.
- Focused commit with an accurate check report.
- The user's separate visual verdict before the next component.

## Example: Run / Live / Changes refactor

A useful breakdown is `Tool Call` → `Agent Message` → `File Changed` → `File Diff`. Each was specified, previewed and reviewed independently. File diffs benefited from unified 3-line context, one line-number column, syntax colors and tested keyboard tree navigation. The example illustrates the **process**, not a mandate to copy its layout to every screen.

See also `docs/plans/2026-10-20-001-run-live-context-ux-plan.md` for user-approved Run UX constraints. When an experimental plan exists only on an unpushed local branch, do not pretend the GitHub branch contains it.
