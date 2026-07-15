"""Phase-0 UX baselines for the CLI redesign.

These tests intentionally exercise the current renderer and serializers rather
than a new view-model layer.  They make future UX changes explicit while keeping
the text and machine interfaces compatible.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loopforge.cli import main
from loopforge.cli.ui import TerminalRenderer, format_status_lines
from loopforge.engine import GuidedAction, GuidanceResult, StatusResult


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ux"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def status_and_guidance(case: dict[str, object], workflow: list[object]) -> tuple[StatusResult, GuidanceResult]:
    project_dir = Path("/workspace/LoopForge")
    config_path = project_dir / ".loopforge" / "config.json"
    initialized = bool(case["initialized"])
    run: dict[str, object] | None = None
    verification: dict[str, object] | None = None
    blockers = [str(value) for value in case.get("blockers", [])]

    if initialized and "status" in case:
        run = {
            "status": case["status"],
            "run_id": case["run_id"],
            "task": case["task"],
            "pack": "generic-code",
            "pack_contract": {"workflow": workflow},
            "stage_statuses": case["stage_statuses"],
        }
        verification = {"status": case["verification"]}

    result = StatusResult(
        project_dir=project_dir,
        config_path=config_path,
        initialized=initialized,
        config={"profile": "supervised", "current_run_id": None} if initialized else None,
        run_dir=project_dir / ".loopforge" / "runs" / str(case.get("run_id", "none")) if run else None,
        run_json_path=None,
        run=run,
        native_artifacts={"status": "complete", "present": 1, "total": 1} if run else None,
        legacy_artifacts={"status": "valid", "errors": []} if run else None,
        loop_contract={"success_checks": ["targeted test"]} if run else None,
        verification=verification,
        memory=None,
        next_step=str(case["next_command"]),
        blockers=blockers,
    )
    action = GuidedAction(
        id="phase-zero-next",
        label="Continue the fixture",
        command=str(case["next_command"]),
        risk="low",
        requires_confirmation=False,
        why="The phase-0 baseline records the current next action.",
    )
    guidance = GuidanceResult(
        project_dir=project_dir,
        state=str(case["guidance_state"]),
        summary="Phase-0 UX fixture.",
        priority="fixture",
        diagnostics=[],
        recommended_actions=[action],
        blocked_reasons=blockers,
        evidence=[],
    )
    return result, guidance


class CliUxPhaseZeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = load_json(FIXTURE_ROOT / "phase0-state-matrix.json")
        cls.machine_contracts = load_json(FIXTURE_ROOT / "phase0-machine-contracts.json")

    def test_plain_status_goldens_cover_the_core_workflow_states(self) -> None:
        workflow = self.matrix["workflow"]
        for case in self.matrix["cases"]:
            with self.subTest(case=case["id"]):
                result, guidance = status_and_guidance(case, workflow)
                output = io.StringIO()
                renderer = TerminalRenderer(output, mode="plain")
                renderer.panel("LoopForge status", format_status_lines(result, guidance))
                self.assertEqual(output.getvalue(), case["plain_output"])

    @unittest.skipUnless(importlib.util.find_spec("rich"), "Rich is not installed")
    def test_rich_status_goldens_keep_the_same_essential_information(self) -> None:
        workflow = self.matrix["workflow"]
        for case in self.matrix["cases"]:
            with self.subTest(case=case["id"]):
                result, guidance = status_and_guidance(case, workflow)
                output = io.StringIO()
                with mock.patch.dict(
                    os.environ,
                    {"TERM": "xterm-256color"},
                    clear=True,
                ):
                    renderer = TerminalRenderer(output, mode="rich")
                    renderer.panel("LoopForge status", format_status_lines(result, guidance))
                rich_output = output.getvalue()
                self.assertIn("\x1b[", rich_output)
                visible_output = ANSI_ESCAPE.sub("", rich_output)
                for line in str(case["plain_output"]).splitlines():
                    if line:
                        self.assertIn(line, visible_output)
                for token in case["rich_tokens"]:
                    self.assertIn(token, visible_output)

    def test_state_family_mapping_is_explicit_before_the_view_model_exists(self) -> None:
        expected = {
            "not_initialized": "setup",
            "ready_for_run": "ready",
            "task_awaiting_approval": "needs_human",
            "implementation_blocked": "blocked",
            "verification_blocked": "blocked",
            "review_pending": "ready",
            "archived": "complete",
        }
        observed = {
            str(case["guidance_state"]): str(case["state_family"])
            for case in self.matrix["cases"]
        }
        self.assertEqual(observed, expected)

    def test_same_named_project_fixtures_record_the_legacy_collision(self) -> None:
        projects = [
            FIXTURE_ROOT / "projects" / "same-name-a" / "LoopForge",
            FIXTURE_ROOT / "projects" / "same-name-b" / "LoopForge",
        ]
        configs = [load_json(project / ".loopforge" / "config.json") for project in projects]

        self.assertEqual([project.name for project in projects], ["LoopForge", "LoopForge"])
        self.assertNotEqual(projects[0].parent, projects[1].parent)
        self.assertEqual([config["project_name"] for config in configs], ["LoopForge", "LoopForge"])
        self.assertEqual(configs[0]["run_root"], configs[1]["run_root"])
        self.assertNotEqual(configs[0]["current_run_id"], configs[1]["current_run_id"])

    def test_machine_output_contracts_and_exit_codes_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            project_dir = workspace / "LoopForge"
            project_dir.mkdir()
            loopforge_home = workspace / "home"

            uninitialized = self._run(project_dir, loopforge_home, self.machine_contracts["status_uninitialized"]["command"])
            self._assert_status_contract(
                uninitialized,
                self.machine_contracts["status_uninitialized"],
            )
            self.assertFalse(uninitialized[1]["status"]["initialized"])

            self.assertEqual(
                self._run(project_dir, loopforge_home, ["init"], parse_json=False)[0],
                0,
            )

            no_run = self._run(project_dir, loopforge_home, self.machine_contracts["status_no_run"]["command"])
            self._assert_status_contract(no_run, self.machine_contracts["status_no_run"])
            self.assertTrue(no_run[1]["status"]["initialized"])
            self.assertIsNone(no_run[1]["status"]["run"])

            runs_contract = self.machine_contracts["runs_empty"]
            runs_json = self._run(project_dir, loopforge_home, runs_contract["json_command"])
            self.assertEqual(runs_json[0], runs_contract["exit_code"])
            self.assertEqual(sorted(runs_json[1]), runs_contract["json_keys"])
            self.assertEqual(runs_json[1]["rows"], [])

            csv_code, csv_output = self._run(project_dir, loopforge_home, runs_contract["csv_command"], parse_json=False)
            self.assertEqual(csv_code, runs_contract["exit_code"])
            self.assertEqual(csv_output.splitlines()[0], runs_contract["csv_header"])

    def _run(
        self,
        project_dir: Path,
        loopforge_home: Path,
        command: list[object],
        *,
        parse_json: bool = True,
    ) -> tuple[int, object]:
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
            working_directory(project_dir),
            contextlib.redirect_stdout(output),
        ):
            exit_code = main([str(value) for value in command])
        return exit_code, json.loads(output.getvalue()) if parse_json else output.getvalue()

    def _assert_status_contract(self, result: tuple[int, object], contract: dict[str, object]) -> None:
        exit_code, payload = result
        self.assertEqual(exit_code, contract["exit_code"])
        self.assertEqual(sorted(payload), contract["top_level_keys"])
        if "status_keys" in contract:
            self.assertEqual(sorted(payload["status"]), contract["status_keys"])
        if "guidance_keys" in contract:
            self.assertEqual(sorted(payload["guidance"]), contract["guidance_keys"])
