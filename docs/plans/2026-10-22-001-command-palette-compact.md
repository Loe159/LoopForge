# Command Palette — compact contextual redesign

Date: 2026-10-22

## Scope and decision

Component: `Ctrl+K` Command Palette only. Settings and the persistent
`Command Input` are out of scope.

User-approved design: Variant A, refined compact layout. Requirements:
- terminal-native, flat, square, graphite/violet palette from `DESIGN.md`;
- no run status on the top-right of the palette;
- current authoritative workflow actions first;
- **hide** unavailable actions, including empty sections;
- contextual slash commands grouped under COMMANDS / INSPECTION;
- one row per result, with selected-row description, command hint, and count;
- searchable by command, label, description, or action id;
- keyboard-first `Ctrl+K`, Up/Down, Enter, Escape; mouse selection;
- narrow layouts must preserve input, selection and footer;
- never bypass confirmation, eligibility or action freshness.

The user authorized implementation through GitHub. A separate remote feature
branch was created from master because other local work (Settings) is ongoing.
Do not merge/push master automatically.

## Existing contracts reused

- `cli/interactive.py:contextual_commands` and `SUPPORTED_COMMANDS` own
  discovery and descriptions.
- `cli/actions.py:ActionDescriptor` and
  `LoopForgeApp.available_actions` own authoritative guided-action exposure.
- `LoopForgeApp.request_action` retains approval and revision checks.
- `LoopForgeApp._run_slash_command` retains the sole slash dispatcher.
- `HomeCommandInput` / `RunCommandBar` remain unchanged.

The custom `ModalScreen` replaces only the stock Textual palette appearance.
There is no new command execution backend.

## Behavior

- Missing/invalid guided actions are not displayed.
- A selected action is rechecked against the current available actions before
  dispatch, preventing execution from a stale palette snapshot.
- `/run` / `/new` reuse the task composer.
- `/archive` reuses the existing confirmation screen.
- Commands requiring input are prefixed in the existing command field rather
  than sent incomplete. `/update` is only prefilled, never auto-executed
  from a single palette selection.
- When no result matches, Enter is inert; Escape dismisses the modal.
- At widths up to 60 columns, the palette uses the narrow layout.

## Implementation

- `src/loopforge/cli/textual_app/command_palette.py`
- `src/loopforge/cli/textual_app/app.py`
- `src/loopforge/cli/textual_app/styles.tcss`
- `tests/test_command_palette.py`

## Verification and acceptance

Tests authored: search and grouping, unavailable action filtering,
no new run for All projects, arrow navigation, empty search, Escape,
and 48/52/60/80/100/120/160-column Pilot iteration at 24 rows.

**Tests NOT executed on the GitHub connector**. The editing environment lacks
Textual and cannot reach Python package indexes; the repository does not expose
a CI workflow to run these tests. These are regression tests awaiting execution,
not evidence of a passing suite.

Local verification to perform:

```sh
python -m unittest tests.test_command_palette tests.test_cli_textual_app
python -m unittest
python -m compileall -q src
git diff --check
```

Visual acceptance is **pending** and must be requested on the actual runtime,
not inferred from the user-approved mockup. Do not begin a new component until
the user accepts this implementation.
