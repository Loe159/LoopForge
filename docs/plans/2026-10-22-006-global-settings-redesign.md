# Global Settings redesign — discovery

Status: variant A composition and first frame/navigation scope explicitly
approved. First component implemented and verified within scope;
user visual acceptance pending. Detailed configuration forms remain proposed.

## Confirmed user needs

- Build a complete global LoopForge configuration center with dedicated subpages.
- Configure harness selection, a default model per harness, and harness/model
  selection per workflow stage, including reasoning and advanced options.
- Global settings provide defaults; packs may override them for their needs.
  Editing project/pack overrides in the UI is outside this iteration.
- Configure autonomy and LoopForge behavior, including integrated execution vs
  a dedicated terminal. Keep run observation and LoopForge workflow approvals
  in LoopForge in either mode. Harness-native interactions remain subject to
  the selected execution mode and its actual supported capabilities.
- Detect harness installation and connection, guide login, select the binary,
  and verify configuration. Direct provider/key management was not selected.
- Keep all four autonomy profiles as starting points AND provide configurable
  behavior for each stage (explicit user answer, 2026-10-22).
- Interview first, then terminal mockups, explicit design approval, and only
  then bounded implementation. Preserve the existing terminal design language.

## Observed implementation and reuse points

| Area | Existing source and behavior | Design consequence |
| --- | --- | --- |
| Settings | `cli/textual_app/app.py`, `_screen_layout`: theme, adapter, project, branch, snapshot revision, PATH diagnostics. Enter opens the adapter picker. | Replace the diagnostic summary with navigable configuration sections after approval. |
| Adapter picker | `cli/textual_app/screens.py`, `AdapterSelectionScreen` | Existing keyboard-first selection; currently persists a project default. Do not silently reuse its project mutation for global settings. |
| Harness commands | `adapters/commands.py`: Codex, Claude Code, Kilo Code, Aider, OpenCode, mini-SWE-agent; fixture adapter is internal/testing. | Present real harness capabilities; installed does not imply authenticated or ready. |
| Execution | `engine/terminal.py`, `execution.py`, `stages.py`: auto/terminal/headless; built-in separate terminal launcher currently Windows only. | Integrated/dedicated is a global default to add. Platform and harness support must be factual. Observation is not interactive terminal input. |
| Project config | `engine/project_service.py`: profile, default adapter, adapter arguments; normalization and engine update APIs | Current operational defaults are project-scoped. Global operational configuration and resolution require an engine extension. |
| User preferences | `engine/__init__.py`: global theme only, atomic persistence | Reuse storage and public API patterns; richer global defaults are new behavior. |
| Autonomy | `engine/__init__.py`: assist/supervised/autonomous/strict and transition/stop policies | Explain actual effects. Distinguish LoopForge workflow autonomy from harness-native permissions. |
| Run limits | `cli/parser.py`, `cli/interactive.py`: maximum attempts and timeout | Global defaults for these existing per-run limits are useful; do not change active runs implicitly. |
| Workflow | Effective `PackRegistry` contract; bundled generic-code workflow has agent research/plan/implementation/review and deterministic task/verification/publication | Stage UI must derive from contracts. Do not offer a model for deterministic checks. Global role/stage defaults need a resolution contract compatible with custom packs. |
| Packs | `engine/packs.py` owns inheritance and effective contributions | Keep overrides outside the editor. Their precedence must remain explainable. |

Read-only source inspection only: no live harness, account, external terminal,
network probe, or user configuration was invoked or modified.

## Proposed information architecture (not yet approved)

1. **Comportement**: default execution destination (integrated/dedicated/automatic
   if retained), theme, explanatory capability/status feedback. Distinguish
   execution controls from display-only preferences.
2. **Harness et modèles**: installation/login status, executable detection and
   override, guided connection, default model, reasoning, advanced options,
   explicit configuration checks. Model discovery/manual entry must expose
   the selected harness's actual capabilities and unknown states.
3. **Étapes du workflow**: global default harness and agent-stage routing;
   explicit inheritance of model/reasoning/options from the chosen harness;
   optional stage-specific overrides. Deterministic stages are described as
   such rather than shown as model assignments.
4. **Autonomie et limites**: profile, concrete effects on transitions and
   confirmations, default attempts and timeout. Fine-grained custom approval
   rules are an unresolved product choice, not an existing capability.
5. **Données et stockage**: useful locations and storage diagnostics initially;
   distinguish locations controlled by environment from editable defaults.
   Memory content and pack-specific promotion policies are not global toggles.
   No implicit migration, deletion, cleanup, or new retention policy.
6. **Diagnostics**: consolidated local capability/readiness checks, version,
   actionable missing-dependency/connection/configuration feedback; explicit
   test action and results. Avoid duplicating harness configuration forms.

Packs remain authoritative for their workflow contributions and overrides.
No pack/project settings editor is included. A separate pack management page
is unnecessary unless a concrete global task emerges during design.

## Proposed interaction rules (not yet approved)

- Use persistent category navigation and a content pane; compare an alternative
  terminal composition in A/B mockups after the interview is settled.
- Prefer a configuration draft with explicit save/revert, a visible dirty state,
  field validation, and an exit warning only when unsaved edits exist.
- Show inherited vs explicitly overridden values and allow returning to the
  harness default without copying a stale value into each stage.
- Expose unsupported/unknown/loading/error states honestly; optional reasoning
  controls appear only when meaningful for the selected harness/model.
- Separate configuration validation from an actual model request, which is
  never an automatic consequence of selecting a harness or model.
- Proposed default: saved operational changes affect future runs; current run
  configuration remains stable. Theme can preview/apply immediately with a
  clearly defined cancellation behavior.
- Verify keyboard ownership, mouse parity, back navigation and narrow/short
  layouts in the mockup proposal and subsequent Textual pilots.

## Interview outcome

- Both the four autonomy profiles and custom stage rules are required
  (explicit user answer). This needs an additional policy contract and is not
  existing behavior. No remaining interview question blocks composition mockups.

## A/B composition proposal

Artifact: `docs/previews/settings-global-ab.html` (self-contained, offline).

- **A — persistent category rail and focused editor (recommended):** six global
  categories remain visible; autonomy has a stage list and one stage editor.
  Strong orientation for a broad settings center; less horizontal space for
  dense comparisons.
- **B — category tabs and overview matrix:** categories are on top; autonomy
  displays stage rules in a table and edits the selected row below. Easier
  comparison; category navigation needs a compact selector on narrow terminals.
- Both show profiles, custom before/after/failure rules, an effective-behavior
  summary, inherited defaults, and pack-required gates. Continue does not create
  an approval receipt. Examples and readiness indicators are synthetic.
- Both provide sample contents for the six categories, explicit save/revert
  simulation, width controls (~120/80/60 columns), and loading/empty/error
  scenarios. This is a composition proposal, not approval of all subpage forms.
- Proposed keyboard behavior: Tab between zones, arrows within choices, Enter
  to select/edit, Escape to return to navigation; mouse equivalents. Narrow
  layouts use a page selector and stack the stage editor. Actual Textual focus
  handling and 24-row usability remain implementation-stage pilot work.
- AppBlock/DIL are unavailable in this session. Disclosed to user; dark HTML
  with native controls plus in-chat terminal sketches used as fallback.
- Browser inspection unavailable: Chrome DevTools could not connect. Static
  HTML/JavaScript checks do not prove the rendered appearance or runtime UX.

## Gates and next step

### User composition decision (2026-10-22)

User selected variant A explicitly for composition only and requested agreement
on the first component before implementation. The category rail and focused
editor topology are accepted. No subpage form or production implementation is
approved by that preference.

### First component: Settings frame and navigation

Scope explicitly approved by the user ("Je valide ce premier périmètre"),
then resumed with "continue" after interruption:

- Global Settings identity, persistent six-category rail, current category title,
  content region, and contextual keyboard footer.
- Open from any existing parent screen without requiring a selected run/project;
  remember the actual opener and return there with its context preserved.
- Up/Down select a category and update its content region immediately; Enter,
  Right or Tab transfers focus into the content. Mouse selection is equivalent.
- Escape returns from content to the rail, then from the rail to the opener;
  local editors/menus consume Escape before screen-level back navigation.
- Retain selected category while moving focus; preserve it across resizing.
  In narrow terminals, replace the rail with a compact category selector, keeping
  the current category title, content access, and return action available.
- Use existing factual information for the initial content integration. Detailed
  configuration forms, save/revert semantics, global operational persistence,
  harness/model routing, and autonomy policy changes are separate approvals.
  The HTML's synthetic values must never become runtime settings or readiness
  claims. No inert/fake controls may stand in for unimplemented subpages.
- Acceptance evidence: Textual pilots covering category changes, keyboard/mouse
  focus, Escape hierarchy, parent-context restoration, and wide/narrow/short
  terminal layouts; then local commit (no push) and separate visual acceptance.

After this component's visual acceptance, proposed next design target:
Harness et modèles, since its defaults feed the workflow-stage assignments.

| Component | Status |
| --- | --- |
| Global Settings architecture/navigation | Implemented/tested from approved A; visual acceptance pending |
| Comportement | Proposed |
| Harness et modèles | Proposed |
| Étapes du workflow | Proposed |
| Autonomie et limites | Proposed |
| Données et stockage | Proposed |
| Diagnostics | Proposed |

Next: local commit, then request visual acceptance of
the frame/navigation. Do not start the next component before that acceptance.
Each subsequent implementation requires its own design approval, tests, local
commit (no push), and separate user visual acceptance.

## Implementation evidence — frame/navigation

- `cli/textual_app/settings.py` owns the six-category navigation, compact native
  selector, scrollable content pane, focus ownership, and a back-request message.
  It does not write configuration or execute harnesses.
- `settings.tcss` extends the existing DESIGN.md palette. The rail is visible
  at 100+ columns; smaller widths use a one-row category selector. The header,
  category title, return button and footer remain usable at 48 columns/24 rows.
- `app.py` mounts the frame alongside the existing Home/Run surfaces. Opening
  Settings retains the opener, list cursor, filters and focused widget. Escape
  returns from content to navigation, then to the actual opener. Native select
  overlays and child dialogs consume their own Escape first.
- Initial subpage content is read-only and factual: existing theme, execution
  default, harness PATH diagnostics, engine profiles, API-provided storage
  locations and current run's pack-driven stage titles when available.
  No model, authentication, routing or global operational setting is invented.
  Project adapter mutation remains an explicit existing guided action and is
  not triggered by Enter in global Settings.
- During screenshot review, the native selector inherited black text on a
  black background in ANSI/NO_COLOR mode. Explicit component foreground and
  background styles fixed it; no contrast exception was added for runtime UI.
- `tests/test_settings_navigation.py` exercises real keyboard/mouse pilots,
  immediate category changes, native menu dismissal, resize/focus retention,
  live snapshot scroll stability, each opener, project cursor and command-input
  restoration, literal values, ASCII hints, and absence of filesystem writes.
  Existing Settings/adapter regression tests were updated to the approved route.
- `tools/demo_settings_navigation.py` uses the real frame with synthetic,
  explicitly unverified diagnostics. It does not initialize a project or run an
  agent. Escape returns to the demo's Home screen.

Observed checks so far:

- Original 10 Settings pilots passed (21.821s); after contrast/layout corrections,
  the 10 pilots plus explicit adapter-action regression passed (24.990s).
  The additional cursor/input restoration pilot passed independently (1.813s).
- Three affected foundation tests plus CLI structure and engine services:
  90 tests passed (26.204s).
- Final combined verification on the current tree: 11 Settings pilots, three
  affected foundation tests, CLI structure and engine services — 102 tests
  passed in 53.611s. This includes the current installation test and the new
  project-cursor/active-command-input round trip.
- Full `python -m unittest` attempt hit its 300s process limit during task
  composer tests; it did not complete and is not a full-suite pass. A replacement
  run was cancelled while correcting a newly added test's command-focus setup.
  A final full run with a larger limit completed: 802 tests in 330.086s,
  4 errors and 3 existing platform skips. The second consecutive run was not
  started because the first was not green.
- Three of the full-suite errors are subcases of
  `test_readonly_research_retains_invalid_candidates_and_allows_retry`:
  rejected candidate files are absent. All three reproduced unchanged against
  an archived clean `f7523c5` tree in `/tmp/loopforge-settings-baseline-sxbhyp4u`
  (1 test, 3 errors, 0.410s). They are not introduced by Settings.
- The fourth error was in the installation test being modified concurrently.
  Its error log used the earlier verification command; the current test and
  engine implementation pass the same isolated case. No installation/CLI
  handler changes were made or included in this component.
- `python -m compileall -q src` and `git diff --check` passed.
- Real Textual SVGs captured at 48/52/60/80/100/120/160 x 24, plus an open native
  menu and autonomy content view. Wide/narrow, color and NO_COLOR captures were
  inspected. Generated captures remain outside the repository under `/tmp/`.

Review commands from repository root:

```sh
PYTHONPATH=src .venv/bin/python tools/demo_settings_navigation.py
PYTHONPATH=src .venv/bin/python tools/demo_settings_navigation.py --capture /tmp/settings-review
PYTHONPATH=src .venv/bin/python -m unittest tests.test_settings_navigation
```

Git: isolated local implementation commit; no push authorized. The full-suite
baseline failure is recorded rather than broadening this approved UI change
into unrelated Research/installation fixes. Exact commit reference follows.
Visual acceptance: pending user inspection of the actual frame/navigation.

### Finish review

The delegated reviewer confirmed the wide/narrow captures were legible in an
interim message, but failed due to a usage limit before returning a verdict.
It is not counted as an independent completed review. A disclosed inline pass
using `impeccable/reference/degraded/finish-reviewer.md` replaced it:

- **Disposition: ship**, limited to the approved frame/navigation; this is not
  visual acceptance and not a claim that the full test suite is green.
- **Persistence:** approved A and bounded scope are recorded here; existing
  DESIGN.md remains authoritative. No new visual identity was introduced.
- **Fidelity:** identity/global scope, category rail, content pane, selected/focus
  treatments and footer match A. The compact selector is the approved narrow
  adaptation. Detailed editable forms and save controls are deferred under the
  user's explicitly bounded first-component approval.
- **Ceiling:** terminal grid, square geometry, keyboard ownership, mouse parity,
  responsive content and palette are retained. No web typography/motion is
  introduced into the terminal surface.
- **Material fixes:** none remaining in the reviewed frame after fixing native
  selector contrast. Unrelated Research errors remain outside this component.
- **Keep:** honest read-only data, native menu Escape ownership, actual-opener
  restoration and user visual acceptance as a separate gate.

Prototype verification: HTML parsed with the Python standard library; no
external resources; inline JavaScript syntax checked with `node --check`;
`git diff --check` passed before final preview adjustments. Re-run static
checks on the final artifact. The design hook's initial contrast findings came
from its interpreting an implicit document body as white; explicit head/body
markup resolved them and the hook reported no deterministic quality issues.
No contrast finding was suppressed. A subsequent `flat-type-hierarchy` finding
was triaged as an intentional terminal-design exception: DESIGN.md specifies
inherited terminal monospace, one-row roles, and a single cell grid. A narrow
`flat-type-hierarchy=*` ignore scoped only to
`docs/previews/settings-global-ab.html` was persisted through the skill's
`hooks ignore-value` command in `.impeccable/config.json`. No mockup typography
or production UI was changed. Existing design-sidecar drift is out of scope.
