# Textual foundation

Textual is the sole full-screen console. There is no backend selector or
fallback full-screen renderer.

The dependency is `textual>=8.0,<9`. The foundation spike was verified against
Textual 8.2.8 and uses only its public `App`, worker, Pilot, binding, and
command-palette APIs. `rich` owns one-shot CLI output. The former prompt shell
and its Prompt Toolkit dependency have been removed.

One-shot CLI commands (including `--plain`), `shell --command`, `shell --script`,
JSON, and CSV do not import `loopforge.cli.textual_app`. Bare `loopforge` and
`loopforge shell` in a TTY open Textual, also when `--plain` is supplied.

The Textual app renders only an immutable `UiSnapshot`. Project loads run in a
Textual worker through `StateStore`; worker code publishes messages and never
mutates widgets. The initial command palette draws from the existing
`ActionDescriptor` registry, but presents metadata only until phase 8 adds the
approval and operation screens.
