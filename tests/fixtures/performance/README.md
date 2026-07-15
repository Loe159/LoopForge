# TUI performance fixtures

`tools/benchmark_tui.py` generates these fixtures dynamically so the repository
does not carry 10,000 files. The default matrix contains 20 registered projects,
1,000 runs in the active project, and 10,000 representative evidence artifacts.

The benchmark also supports an unavailable Git executable and injected process
startup delay. This keeps the baseline reproducible on Linux and Windows
without requiring an interactive terminal.
