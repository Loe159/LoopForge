# CLI guidelines implementation progress

This file tracks implementation of the clig.dev and 12 Factor CLI Apps plan so
future work can resume without re-checking completed points.

## Status legend

- `todo`: not started.
- `partial`: implemented in part; keep working.
- `done`: implemented with targeted tests or existing coverage.

## Checklist

1. CLI common layer: done
2. Global flags: done
3. Structured argparse errors: done
4. Rich version command: done
5. Top-level help rewrite: done
6. `help` command: done
7. Command examples: done
8. `--format` and `--json`: done
9. CSV for list commands: done
10. Stable table renderer/options: done
11. Top-level `runs`: done
12. Color/rich controls: done
13. Controlled prompts: done
14. Confirmation helpers: done
15. Adapter stream summaries: done
16. Ctrl-C handling: done
17. Debug/logs: done
18. XDG/platform paths: done
19. Completion command: done
20. Contribution and usage docs: done
21. Startup performance: done
22. Compatibility preservation: done

## Notes

- `TerminalRenderer` now honors `NO_COLOR`, `LOOPFORGE_NO_COLOR`,
  `TERM=dumb`, `FORCE_COLOR`, and an explicit `no_color` constructor flag.
- `loopforge_home()` now keeps `LOOPFORGE_HOME` first, keeps an existing
  `~/LoopForge`, and otherwise defaults to a platform data directory.
- `loopforge version`, `loopforge help`, `loopforge runs`, and
  `loopforge completion` are public commands.
- `--json` is a global alias for `--format json`; list commands also support
  CSV and table shaping flags.
- Discovery commands are covered by tests that prove they do not query project
  state.
- Confirmation parsing now accepts `--confirm` with an optional value and routes
  it through `confirmation_accepted()` while preserving current boolean
  behavior for strict-profile actions.
