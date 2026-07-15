"""Deterministic performance contracts for the future snapshot render path."""

from __future__ import annotations

import ast
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from loopforge.cli.interactive import InteractiveShell
from loopforge.cli.tui import LoopForgeConsole, format_run_snapshot
from loopforge.cli.presentation import ShellSnapshot


ROOT = Path(__file__).resolve().parents[1]


class CliTuiPerformanceContractTests(unittest.TestCase):
    def test_snapshot_renderer_has_no_engine_or_filesystem_calls(self) -> None:
        """The snapshot boundary is guarded before more screens migrate to it."""

        tree = ast.parse((ROOT / "src" / "loopforge" / "cli" / "tui.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "format_run_snapshot")
        forbidden_names = {"current_status", "current_guidance", "list_runs", "list_registered_projects"}
        forbidden_attributes = {"run", "rglob", "read_text", "read_object", "load"}
        calls = [node.func for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(call, ast.Name) and call.id in forbidden_names for call in calls))
        self.assertFalse(any(isinstance(call, ast.Attribute) and call.attr in forbidden_attributes for call in calls))

    def test_debug_timing_is_opt_in_and_records_render_and_key_latency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            console = LoopForgeConsole(InteractiveShell(Path(temporary), output=io.StringIO()))
            callback = console._timed_render_callback("contract", lambda: [])
            callback()
            self.assertEqual(console.debug_timing_summary(), {})

            with mock.patch.dict(os.environ, {"LOOPFORGE_DEBUG": "1"}):
                console._refresh_requested_at = 0.0
                callback()
                timings = console.debug_timing_summary()
        self.assertEqual(timings["render.contract"]["count"], 1)
        self.assertEqual(timings["key_to_render"]["count"], 1)

    def test_benchmark_fixture_and_result_are_reproducible_at_small_scale(self) -> None:
        spec = importlib.util.spec_from_file_location("benchmark_tui", ROOT / "tools" / "benchmark_tui.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"LOOPFORGE_DEBUG": "1"}):
            fixture = module.build_fixture(Path(temporary), project_count=2, run_count=3, evidence_count=8)
            result = module.run_benchmark(fixture, repeats=1, git_mode="unavailable")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["fixture"]["projects"], 2)
        self.assertEqual(result["fixture"]["runs"], 3)
        self.assertTrue({entry["name"] for entry in result["operations"]} >= {"current_status", "first_frame", "run_screen"})
        self.assertIn("io", result["operations"][0])


if __name__ == "__main__":
    unittest.main()
