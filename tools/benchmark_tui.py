"""Reproducible baseline benchmark for the legacy prompt-toolkit console.

Run from the repository root, for example:

    python tools/benchmark_tui.py --output docs/benchmarks/phase0-local.json

The fixture stays in a temporary directory unless ``--keep-fixture`` is used.
It has no network side effects and never writes into a project under test.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter, sleep
from typing import Any, Callable, Iterator
from unittest import mock

from loopforge.cli.evidence import evidence_items
from loopforge.cli.interactive import InteractiveShell
from loopforge.cli.tui import LoopForgeConsole, format_run_snapshot
from loopforge.engine import (
    create_run,
    current_guidance,
    current_status,
    initialize_project,
    list_runs,
    read_json,
    write_json_atomic,
)
from loopforge.engine.storage import JsonStore


@dataclass(frozen=True)
class PerformanceFixture:
    root: Path
    home: Path
    project: Path
    run_dir: Path


def build_fixture(
    root: Path,
    *,
    project_count: int = 20,
    run_count: int = 1_000,
    evidence_count: int = 10_000,
) -> PerformanceFixture:
    """Build representative storage without needing an interactive terminal."""

    if project_count < 1 or run_count < 1 or evidence_count < 1:
        raise ValueError("fixture counts must be positive")
    home = root / "loopforge-home"
    projects = root / "projects"
    project = projects / "project-000"
    for index in range(project_count):
        candidate = projects / f"project-{index:03d}"
        candidate.mkdir(parents=True, exist_ok=True)
        initialize_project(candidate, home=home)

    previous_home = os.environ.get("LOOPFORGE_HOME")
    os.environ["LOOPFORGE_HOME"] = str(home)
    try:
        created = create_run(project, "Benchmark TUI render", success_checks=["python -m unittest"])
    finally:
        if previous_home is None:
            os.environ.pop("LOOPFORGE_HOME", None)
        else:
            os.environ["LOOPFORGE_HOME"] = previous_home
    run_dir = created.run_dir
    template = read_json(run_dir / "run.json")
    run_root = run_dir.parent
    for index in range(1, run_count):
        clone = dict(template)
        clone["run_id"] = f"benchmark-run-{index:05d}"
        clone["task"] = f"Benchmark task {index:05d}"
        clone["updated_at"] = f"2026-07-15T00:{index % 60:02d}:00Z"
        clone_dir = run_root / f"benchmark-run-{index:05d}"
        clone_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(clone_dir / "run.json", clone)

    evidence_root = run_dir / "artifacts" / "benchmark-evidence"
    suffixes = (".md", ".log", ".json", ".patch")
    for index in range(evidence_count):
        suffix = suffixes[index % len(suffixes)]
        path = evidence_root / f"bucket-{index // 250:03d}" / f"artifact-{index:05d}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"benchmark evidence {index}\n" * 3, encoding="utf-8")
    return PerformanceFixture(root=root, home=home, project=project, run_dir=run_dir)


def percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    return ordered[max(0, min(len(ordered) - 1, int((len(ordered) * fraction) + 0.999999) - 1))]


@contextmanager
def count_io(*, git_mode: str, process_delay_ms: float) -> Iterator[dict[str, int | float]]:
    """Count the I/O sources that must leave the render path in later phases."""

    counts: dict[str, int | float] = {
        "file_reads": 0,
        "file_read_ms": 0.0,
        "path_rglob": 0,
        "path_rglob_ms": 0.0,
        "json_reads": 0,
        "json_read_ms": 0.0,
        "subprocess_starts": 0,
        "subprocess_ms": 0.0,
    }
    original_read_text = Path.read_text
    original_rglob = Path.rglob
    original_json_read = JsonStore.read_object
    original_run = subprocess.run

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        counts["file_reads"] += 1
        started = perf_counter()
        try:
            return original_read_text(path, *args, **kwargs)
        finally:
            counts["file_read_ms"] += (perf_counter() - started) * 1_000

    def rglob(path: Path, *args: Any, **kwargs: Any) -> Iterator[Path]:
        counts["path_rglob"] += 1
        started = perf_counter()
        try:
            yield from original_rglob(path, *args, **kwargs)
        finally:
            counts["path_rglob_ms"] += (perf_counter() - started) * 1_000

    def json_read(store: JsonStore, path: Path) -> dict[str, Any]:
        counts["json_reads"] += 1
        started = perf_counter()
        try:
            return original_json_read(store, path)
        finally:
            counts["json_read_ms"] += (perf_counter() - started) * 1_000

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        counts["subprocess_starts"] += 1
        command = args[0] if args else kwargs.get("args", [])
        executable = command[0] if isinstance(command, (list, tuple)) and command else ""
        if executable == "git" and git_mode == "unavailable":
            raise OSError("benchmark: git executable unavailable")
        if process_delay_ms:
            sleep(process_delay_ms / 1_000)
        started = perf_counter()
        try:
            return original_run(*args, **kwargs)
        finally:
            counts["subprocess_ms"] += (perf_counter() - started) * 1_000

    with (
        mock.patch.object(Path, "read_text", read_text),
        mock.patch.object(Path, "rglob", rglob),
        mock.patch.object(JsonStore, "read_object", json_read),
        mock.patch("subprocess.run", run),
    ):
        yield counts


def measure(name: str, callback: Callable[[], Any], counts: dict[str, int | float], repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    before = dict(counts)
    for _ in range(repeats):
        started = perf_counter()
        callback()
        samples.append((perf_counter() - started) * 1_000)
    return {
        "name": name,
        "median_ms": round(percentile(samples, 0.5), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "calls": repeats,
        "io": {
            key: round(float(counts[key] - before[key]), 3) if key.endswith("_ms") else int(counts[key] - before[key])
            for key in counts
        },
    }


def run_benchmark(
    fixture: PerformanceFixture,
    *,
    repeats: int = 3,
    git_mode: str = "normal",
    process_delay_ms: float = 0.0,
) -> dict[str, Any]:
    """Measure engine reads, evidence scanning, and the current screen callbacks."""

    previous_home = os.environ.get("LOOPFORGE_HOME")
    os.environ["LOOPFORGE_HOME"] = str(fixture.home)
    try:
        with count_io(git_mode=git_mode, process_delay_ms=process_delay_ms) as counts:
            shell = InteractiveShell(fixture.project, output=sys.stderr)
            console = LoopForgeConsole(shell)
            console.state.screen = "run"
            render_body = console._timed_render_callback("body", console._body_fragments)
            hydrated_snapshot = console._snapshot(fixture.project)
            operations = [
                measure("current_status", lambda: current_status(fixture.project), counts, repeats),
                measure("current_guidance", lambda: current_guidance(fixture.project), counts, repeats),
                measure("list_runs", lambda: list_runs(fixture.project), counts, repeats),
                measure("evidence_scan", lambda: evidence_items(fixture.run_dir), counts, repeats),
                measure(
                    "run_snapshot_formatting",
                    lambda: format_run_snapshot(hydrated_snapshot, ascii_mode=False),
                    counts,
                    repeats,
                ),
                measure("first_frame", lambda: (console._header_fragments(), render_body(), console._footer_fragments()), counts, 1),
                measure("run_screen", render_body, counts, repeats),
            ]
            debug_timings = console.debug_timing_summary()
    finally:
        if previous_home is None:
            os.environ.pop("LOOPFORGE_HOME", None)
        else:
            os.environ["LOOPFORGE_HOME"] = previous_home

    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "filesystem": os.statvfs(fixture.root).f_bsize if hasattr(os, "statvfs") else "unknown",
            "commit": _git_commit(),
        },
        "fixture": {
            "projects": len(list((fixture.root / "projects").iterdir())),
            "runs": len(list(fixture.run_dir.parent.iterdir())),
            "evidence_paths": sum(
                1 for path in (fixture.run_dir / "artifacts" / "benchmark-evidence").rglob("*") if path.is_file()
            ),
            "git_mode": git_mode,
            "process_startup_delay_ms": process_delay_ms,
        },
        "operations": operations,
        "debug_timings": debug_timings,
    }


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the JSON result to this path.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--projects", type=int, default=20)
    parser.add_argument("--runs", type=int, default=1_000)
    parser.add_argument("--evidence", type=int, default=10_000)
    parser.add_argument("--git-mode", choices=("normal", "slow", "unavailable"), default="normal")
    parser.add_argument("--process-startup-delay-ms", type=float, default=0.0)
    parser.add_argument("--keep-fixture", type=Path, help="Build the fixture here instead of a temporary directory.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    delay = args.process_startup_delay_ms + (200.0 if args.git_mode == "slow" else 0.0)
    previous_debug = os.environ.get("LOOPFORGE_DEBUG")
    os.environ["LOOPFORGE_DEBUG"] = "1"
    try:
        if args.keep_fixture:
            args.keep_fixture.mkdir(parents=True, exist_ok=True)
            fixture = build_fixture(args.keep_fixture, project_count=args.projects, run_count=args.runs, evidence_count=args.evidence)
            result = run_benchmark(fixture, repeats=args.repeats, git_mode=args.git_mode, process_delay_ms=delay)
        else:
            with tempfile.TemporaryDirectory(prefix="loopforge-tui-benchmark-") as temporary:
                fixture = build_fixture(Path(temporary), project_count=args.projects, run_count=args.runs, evidence_count=args.evidence)
                result = run_benchmark(fixture, repeats=args.repeats, git_mode=args.git_mode, process_delay_ms=delay)
    finally:
        if previous_debug is None:
            os.environ.pop("LOOPFORGE_DEBUG", None)
        else:
            os.environ["LOOPFORGE_DEBUG"] = previous_debug

    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
