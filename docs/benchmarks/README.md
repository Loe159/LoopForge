# Performance benchmarks

Run the phase-0 baseline from an installed checkout:

```text
python tools/benchmark_tui.py --output docs/benchmarks/phase0-local.json
```

For a Windows process-startup simulation or a missing Git executable:

```text
python tools/benchmark_tui.py --git-mode slow --process-startup-delay-ms 200
python tools/benchmark_tui.py --git-mode unavailable
```

The report separates pure snapshot formatting from filesystem/JSON reads and
subprocess time. It is an observed baseline, not a unit-test time budget:
run it on Linux and Windows before accepting phases 1–6.
