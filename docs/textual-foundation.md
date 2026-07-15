# Textual foundation

Phase 7 keeps the current `prompt_toolkit` console as the default while the
Textual backend is developed behind `LOOPFORGE_TUI_BACKEND=textual`.

The dependency is `textual>=8.0,<9`. The foundation spike was verified against
Textual 8.2.8 and uses only its public `App`, worker, Pilot, binding, and
command-palette APIs. `rich` and `prompt_toolkit` remain explicit dependencies:
Rich owns one-shot CLI output and prompt-toolkit remains the emergency legacy
full-screen backend during the stabilization period.

`loopforge --plain`, `shell --command`, `shell --script`, JSON, and CSV do not
import `loopforge.cli.textual_app`. The selector is temporary and internal;
invalid values safely fall back to `legacy`.

The Textual app renders only an immutable `UiSnapshot`. Project loads run in a
Textual worker through `StateStore`; worker code publishes messages and never
mutates widgets. The initial command palette draws from the existing
`ActionDescriptor` registry, but presents metadata only until phase 8 adds the
approval and operation screens.
