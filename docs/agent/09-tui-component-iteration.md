# Component-by-component TUI design and redesign workflow

**Scope:** new LoopForge Textual screens, layout redesigns, terminal interaction
changes, and substantial visual changes to existing Run/Live/Changes components.
Apply the same discipline for a small component when user review is important.

**Authority:** user approval of a **mockup** allows an implementation, not
approval of the delivered UI. Automated tests cannot stand in for **visual
acceptance**. Neither gate authorizes a Git push or publication.

See `DESIGN.md`, `AGENTS.md`, [coding patterns](03-coding-patterns.md),
[adding features](05-how-to-add-feature.md), [build/test](06-build-test-run.md),
and [danger zones](07-danger-zones.md). Developer skill:
`../../.agents/skills/tui-component-iteration/SKILL.md`.

## Repeatable loop — one component at a time

1. **Inspect the running surface and contracts.** Read the existing widgets,
   presenter, state projector, styles, test cases, `DESIGN.md`, and related
   product/decision documents. List what each component displays, where its
   data comes from, its navigation/focus ownership, responsive behavior, and
   semantic constraints. Do not infer “verified” data from an agent transcript.
2. **Decompose the screen.** Make an ordered inventory of user-visible
   components (e.g., Tool Call, Agent Message, File Changed, Changes explorer).
   Separate distinct interactions; do not treat approval of one as approval of
   the whole screen. Track *proposed → mockup ready → design approved →
   implemented/tested → visually accepted* **per component**.
3. **Show interactive in-chat terminal mockups before coding.** Prefer paired `AppBlock` dark previews with functional DIL selection controls, as specified below. Do not generate images. Then: Usually propose meaningful
   **A/B alternatives**, not just labels. Show realistic terminal text/layout,
   dimensions, empty/loading/busy/error states when relevant, keyboard/mouse
   behavior, provenance labels, and a recommendation with tradeoffs. Keep the
   input bar, persistent controls and focus conventions visible where applicable.
   An ASCII/text mockup or a graphical preview is acceptable, but it must
   represent terminal constraints rather than a web layout.
4. **Wait for explicit design approval.** Record the selected variant and each
   requested adjustment in a plan. If a mockup is rejected or changed, revise
   and ask again. “Go” to the next proposal is not permission to implement an
   unapproved component.
5. **Implement the approved component only.** Reuse the existing Textual
   components, CSS tokens and projection/event contracts. Preserve unrelated
   changes and compatibility modes. Do not broaden the scope to sibling
   components, lifecycle rules, adapter behavior or publication flow without
   separate approval.
6. **Prove behavior and rendering.** Create focused unit/projection tests and
   Textual pilot tests; use a reproducible in-app preview for visual review.
   Inspect actual screenshots/terminal output, not only the component tree.
   Fix regressions, then retest. See the matrix below.
7. **Commit a small, auditable change.** Show the changed paths, precise tests
   run, failures/timeouts, and commit SHA. A correction requested after review
   receives its own tests and commit. Do **not** push unless explicitly asked.
8. **Ask for visual validation.** Give the exact preview command or workflow.
   Wait for the user's screenshot/feedback or explicit acceptance. If changes
   are requested, return to steps 5–8 **for the same component**. Only mark it
   *visually accepted* after the user explicitly approves the actual result.
   Then present mockups for the **next** component; do not implement it yet.

## Default dynamic ChatGPT mockups — exact format

**Canonical design gate:** the successful LoopForge Run/Live sessions used in-chat
HTML/CSS mockups that looked like the actual dark terminal, accompanied by
interactive choice controls. They were not image-generated pictures,
generic white-background interfaces, or only local Textual scripts.

### Tools and props

1. Author **two distinct AppBlock previews** in the same ChatGPT reply:
   `AppBlock title="Variante A — ..." language="html" variant="inline"`
   and `AppBlock title="Variante B — ..." language="html" variant="inline"`.
   Inside each block supply self-contained HTML + CSS. These previews are visual
   and need not duplicate the entire Textual implementation.
2. Use explicit `DESIGN.md` palette: `#15121B` panel background, `#1D1A23`
   code/command surface, `#494454` dividers, `#E7E0ED` body text, `#CBC3D7`
   secondary text, `#958EA0` muted labels and `#D0BCFF` focus. Syntax colors
   follow the product design. Force monospace, dense spacing, flat rectangular
   surfaces. Never use a default white browser canvas or unrelated web styling.
3. Outside AppBlock, declare client state with `{@body const [choice,setChoice]
   = DIL.useState("A")}` and optionally `{@body const [notes,setNotes]
   = DIL.useState("")}`. Add a controlled `<radio-group direction="col"
   value={choice} onChange={setChoice}>` with two `<radio value="A">` /
   `<radio value="B">` children. Optional `<textarea rows={2} value={notes}
   onChange={setNotes} />` captures feedback.
4. Use `<button onClick={() => GenUI.issueNewTurn(...)}>` with the choice
   and optional notes to send the user's approval. The callback must be
   user-triggered, never in an effect or generated JSON text.
5. Show the tradeoffs, keyboard/mouse intent and relevant empty/loading/error
   states. Present both variants, not merely labels or a textual suggestion.

### Complete illustrative in-chat mockup (DIL example)

~~~jsx
<AppBlock title="Variante A — Compact" language="html" variant="inline">
  <div class="lf-a"><div>Run #1 · Live</div><div class="lf-a-body">Agent Message</div><div>› Type / for commands</div></div>
  <style>.lf-a {background:#15121B;color:#E7E0ED;padding:12px;border:1px solid #494454;font:12px/1.5 ui-monospace,monospace}.lf-a-body{background:#1D1A23;padding:8px;margin:8px 0}</style>
</AppBlock>
<AppBlock title="Variante B — Structured" language="html" variant="inline">
  <div class="lf-b"><div>Run #1 · Live</div><div class="lf-b-grid"><span>Agents</span><span>Reasoning · Tool Call</span></div><div>› Type / for commands</div></div>
  <style>.lf-b{background:#15121B;color:#E7E0ED;padding:12px;border:1px solid #494454;font:12px/1.5 ui-monospace,monospace}.lf-b-grid{display:grid;grid-template-columns:30% 70%;gap:6px;background:#1D1A23;padding:8px}</style>
</AppBlock>
{@body const [choice,setChoice] = DIL.useState("A")}
{@body const [notes,setNotes] = DIL.useState("")}
<box border radius="lg" padding={3} gap={3}>
  **Quelle variante choisis-tu ?**
  <radio-group direction="col" value={choice} onChange={setChoice}>
    <radio value="A">A — Compact</radio>
    <radio value="B">B — Structured</radio>
  </radio-group>
  <textarea rows={2} value={notes} onChange={setNotes} placeholder="Ajustements…"/>
  <button block onClick={() => GenUI.issueNewTurn("Je valide la variante " + choice +
    ". " + (notes.trim() ? "Ajustements : " + notes.trim() + ". " : "") +
    "Implémente uniquement ce composant, teste-le et crée un commit local sans push.")}>Valider la variante</button>
</box>
~~~

AppBlock is only the styled visualization; **active form controls stay in DIL**.
Never substitute `image_gen` (or a generated picture) for these ChatGPT
mockups. If DIL/AppBlock is unavailable, explicitly say so and use the
closest supported interactive terminal preview, not a default white sketch.

### Different post-approval stage: real Textual

After explicit design approval implement the selected widget only, use
`tools/demo_<component>.py` with synthetic in-memory data and run real
Textual pilots: `app.run_test(size=(120,35))`, `pilot.press("down")`,
`pilot.click("#widget-id")`, `pilot.resize_terminal(60,24)`.
Inspect screenshots at 48/52/60/80/100/120/160 columns and short heights.
Test and commit locally; request a *separate* visual acceptance gate.

## Approval and handoff record

Keep a short, versioned record (e.g. in `docs/plans/`) containing:

| Field | Required information |
| --- | --- |
| Component | Screen and bounded component name |
| Contract | Existing data source, actions, constraints, and focus owner |
| Mockups | A/B screenshots or terminal text and design tradeoffs |
| User decision | Chosen variant, date/context and requested adjustments |
| Implementation | Scope/files changed, test commands and observed results |
| Git | Local commit SHA; whether pushed (default: no) |
| Visual sign-off | Pending or explicit user acceptance; subsequent feedback |
| Next | Next component to *mock up*, not to implement automatically |

Distinguish an approved **design**, a passing **test**, and approved **visual
behavior** in both planning notes and user updates. Keep prior accepted
components stable when iterating on later ones.

## Test matrix / definition of done

Select applicable cases, then record actual outcomes:

- **Real TUI interaction:** focused vs unfocused navigation, arrow keys, Enter,
  Escape, click, scroll, selection/focus persistence across update and resize,
  disabled/blocked/loading states and return navigation.
- **Responsive:** representative widths **48, 52, 60, 80, 100, 120, 160**,
  including breakpoint edges, with short heights such as **24/30**. Assert
  rectangles (non-overlap, minimum usable heights, visible command input),
  clipping, ellipsis and keyboard access. Prefer two columns when they remain
  usable instead of collapsing solely by a broad width-class name.
- **Rendering:** color contrast for every token category (including unstyled
  Markdown text), syntax highlighting, added/deleted backgrounds, code
  gutters/line numbers, three-line diff context when it exists, wrapping,
  scrollbars, Unicode/ASCII fallback and theme variability as applicable.
- **Evidence and boundaries:** native structured events vs free text, declared
  changes vs captured workspace diff vs cumulative verification patch, counts
  only if sourced, stale/partial/binary/renamed/missing diffs, session switching,
  truncated output and secret-safe rendering. Never invent line counts, diffs
  or availability.
- **Lifecycle and regressions:** streaming/partial updates, stable widget
  identity, output scrolling, real StateStore navigation and demo navigation,
  screen switching and command shortcuts. Exercise neighbor components to
  catch incidental CSS/callback changes.

Use `python -m unittest`, focused `tests/test_run_*.py` and
`tests/test_cli_textual_app.py` as appropriate, `python -m compileall -q src`,
and `git diff --check`. When execution is unavailable or times out, report
exactly which checks passed and which did not run. Do not claim a full-suite
pass from partial batches.

## Deterministic visual demo rules

- Prefer a dedicated `tools/demo_<component>.py` that renders the **real**
  widget/screen using in-memory synthetic snapshot objects.
- Include representative adjacent content and states (one successful example,
  one edge case). No filesystem mutation, external services, model calls, or
  hidden publication.
- Make it obvious the data is synthetic. Demo navigation must keep its mock
  state; a button should not unexpectedly reload production StateStore and
  show a generic “Loading agent output” placeholder.
- Capture screenshots in a temporary/untracked location and clean generated
  artifacts. They are verification aids, not substitute acceptance.
- If no access to the running environment exists, provide a reviewable
  mockup/patch and state that **runtime tests and visual validation remain
  pending**.

## Pitfalls observed during Run/Live refinement

- A Markdown renderer may leave default token colors unreadable on a dark
  deleted-line background: inspect **actual resolved colors**, not only CSS.
- An “Edited file” harness event is a **declaration**; line counts and diffs
  belong to a trustworthy retained capture. A cumulative verification patch
  must not be represented as per-event proof.
- A complete screenshot at 120 columns does not validate 60/80 columns:
  test **both width and height**, breakpoint transitions and live resizing.
- Too many stacked containers, low-contrast citations, title bars or excessive
  margins can obscure the main content. Terminal density should remain calm
  and keyboard-first.
- Interactions on a mock run may unexpectedly trigger a real-store refresh:
  test every button and view transition in the demo before declaring it usable.
