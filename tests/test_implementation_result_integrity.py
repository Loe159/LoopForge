from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loopforge.checks import validate_implementation_result
from loopforge.engine import (
    ADAPTER_BLOCKED,
    execute_attempt,
    expected_session_for,
    synthetic_adapter_result,
    update_run_after_attempt,
)


class ImplementationResultIntegrityTests(unittest.TestCase):
    def test_expected_session_includes_github_issue_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run = {
                "base_commit": "a" * 40,
                "run_id": "run-001",
                "task_id": "task-001",
                "evidence": {
                    "source": {
                        "type": "github_issue",
                        "reference": "Loe159/LoopForge#8",
                        "url": "https://github.com/Loe159/LoopForge/issues/8",
                    }
                },
            }

            session = expected_session_for(run, "codex", workspace)

            self.assertEqual(session["issue"], 8)
            self.assertEqual(
                validate_implementation_result.validate_expected_session(session),
                session,
            )

    def test_invalid_result_blocks_transition_and_retains_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            workspace = root / "workspace"
            run_dir = root / "run"
            project.mkdir()
            workspace.mkdir()
            (run_dir / "attempts").mkdir(parents=True)
            (run_dir / "progress.md").write_text("# Progress\n", encoding="utf-8")

            run = {
                "base_commit": "a" * 40,
                "run_id": "run-001",
                "task_id": "task-001",
                "task": "Make one bounded change",
                "project_root": str(project),
                "profile": "supervised",
                "workspace": {"path": str(workspace)},
                "limits": {"max_attempts": 3, "timeout_seconds": 30},
                "attempts": [],
            }
            contract = {
                "success_checks": ["python -m unittest"],
                "allowed_tools": [],
            }
            session = expected_session_for(run, "codex", workspace)
            invalid_result = synthetic_adapter_result(
                session=session,
                status="completed",
                summary="Adapter reported success.",
                workspace_changed=True,
            )
            invalid_result.pop("issue")

            child = {
                "completed": True,
                "returncode": 0,
                "timed_out": False,
                "interrupted": False,
                "output_limit_exceeded": False,
            }
            with (
                mock.patch("loopforge.engine.run_workspace_path", return_value=workspace),
                mock.patch("loopforge.engine.command_for_attempt", return_value=["codex"]),
                mock.patch(
                    "loopforge.engine.execute_adapter_command",
                    return_value=(child, b"", b""),
                ),
                mock.patch(
                    "loopforge.engine.parse_adapter_result_file",
                    return_value=invalid_result,
                ),
                mock.patch(
                    "loopforge.engine.workspace_snapshot",
                    side_effect=[{}, {"changed.txt": (1, 1)}],
                ),
                mock.patch(
                    "loopforge.engine.git_status_entries",
                    side_effect=[[], ["?? changed.txt"]],
                ),
            ):
                attempt = execute_attempt(
                    project_dir=project,
                    run_dir=run_dir,
                    run=run,
                    contract=contract,
                    adapter="codex",
                    adapter_args=[],
                )

            self.assertEqual(attempt["status"], "failed")
            self.assertIn("missing=['issue']", attempt["contract_validation_error"])
            self.assertEqual(attempt["invalid_result_path"], "attempts/attempt-001/result.invalid.json")

            result_path = run_dir / attempt["result_path"]
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            validate_implementation_result.validate_result(result)

            invalid_path = run_dir / attempt["invalid_result_path"]
            invalid_evidence = json.loads(invalid_path.read_text(encoding="utf-8"))
            self.assertNotIn("issue", invalid_evidence)

            with mock.patch("loopforge.engine.persist_run_json"):
                updated = update_run_after_attempt(
                    project_dir=project,
                    run_json_path=run_dir / "run.json",
                    run=run,
                    attempt=attempt,
                )

            self.assertEqual(updated["status"], ADAPTER_BLOCKED)
            self.assertEqual(updated["stage_statuses"]["implementation"], "blocked")
            self.assertEqual(updated["current_stage"], "implementation_blocked")


if __name__ == "__main__":
    unittest.main()
