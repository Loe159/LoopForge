from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from loopforge.cli import main


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CliTests(unittest.TestCase):
    def test_init_creates_config_and_templates_in_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["init"]), 0)

            config_path = repo / ".loopforge" / "config.json"
            self.assertTrue(config_path.exists())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(config),
                {
                    "project_name",
                    "profile",
                    "run_root",
                    "current_run_id",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertEqual(config["project_name"], repo.name)
            self.assertEqual(config["profile"], "supervised")
            self.assertEqual(
                config["run_root"],
                str(Path.home() / "LoopForge" / "runs" / repo.name),
            )
            self.assertIsNone(config["current_run_id"])
            self.assertTrue((repo / ".loopforge" / "templates" / "loop.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "memory.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "scratch.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "exchange.json").exists())
            self.assertIn("LoopForge initialized", output.getvalue())

    def test_init_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)

            with working_directory(repo), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init"]), 0)
            config_path = repo / ".loopforge" / "config.json"
            first_config_text = config_path.read_text(encoding="utf-8")

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["init"]), 0)

            self.assertEqual(config_path.read_text(encoding="utf-8"), first_config_text)
            self.assertIn("LoopForge already initialized", output.getvalue())

    def test_run_creates_external_run_and_updates_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=LoopForge Tests",
                    "-c",
                    "user.email=loopforge@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Add a useful command"]), 0)

            config_path = repo / ".loopforge" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            run_id = config["current_run_id"]
            self.assertIsInstance(run_id, str)
            self.assertEqual(config["run_root"], str(loopforge_home / "runs" / repo.name))

            run_dir = loopforge_home / "runs" / repo.name / run_id
            self.assertTrue(run_dir.exists())
            self.assertFalse(run_dir.is_relative_to(repo))

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["run_id"], run_id)
            self.assertEqual(run_json["task_id"], run_id)
            self.assertEqual(run_json["task"], "Add a useful command")
            self.assertEqual(run_json["project_root"], str(repo.resolve()))
            self.assertEqual(run_json["base_commit"], base_commit)
            self.assertEqual(run_json["profile"], "supervised")
            self.assertEqual(run_json["pack"], "generic-code")
            self.assertEqual(run_json["status"], "ready_for_verification")
            self.assertEqual(run_json["success_checks"], [])
            self.assertEqual(run_json["blockers"], [])
            self.assertEqual(run_json["legacy"]["issue_source"], "generated_from_task_id")
            self.assertIsInstance(run_json["legacy"]["issue"], int)
            self.assertGreater(run_json["legacy"]["issue"], 0)
            self.assertEqual(run_json["legacy"]["base_commit"], base_commit)
            self.assertEqual(run_json["legacy"]["base_commit_source"], "git")

            for file_name in (
                "task.md",
                "loop.md",
                "plan.md",
                "progress.md",
                "verification.md",
                "memory.md",
                "scratch.md",
                "exchange.json",
            ):
                self.assertTrue((run_dir / file_name).exists(), file_name)
            for directory_name in ("attempts", "artifacts", "metrics"):
                self.assertTrue((run_dir / directory_name).is_dir(), directory_name)

            legacy_dir = Path(run_json["legacy"]["artifact_dir"])
            self.assertEqual(legacy_dir, run_dir / "artifacts" / "legacy-agent")
            for file_name in (
                "task.md",
                "research.md",
                "plan.md",
                "progress.md",
                "verification.md",
                "review.md",
            ):
                self.assertTrue((legacy_dir / file_name).exists(), file_name)
            validation = subprocess.run(
                [
                    sys.executable,
                    str(Path(run_json["legacy"]["validator"])),
                    "--run",
                    str(legacy_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

            exchange = json.loads((run_dir / "exchange.json").read_text(encoding="utf-8"))
            self.assertEqual(exchange["run_id"], run_id)
            self.assertIn("Add a useful command", (run_dir / "task.md").read_text(encoding="utf-8"))
            self.assertIn("LoopForge run created", output.getvalue())

            self.assertFalse((repo / "run.json").exists())
            self.assertFalse((repo / "attempts").exists())
            self.assertFalse((repo / "artifacts").exists())
            self.assertFalse((repo / "metrics").exists())

    def test_run_requires_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with working_directory(Path(temp_dir)), contextlib.redirect_stderr(output):
                self.assertEqual(main(["run", "--task", "Do the thing"]), 1)
            self.assertIn("run `loopforge init` first", output.getvalue())

    def test_status_reports_not_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with working_directory(Path(temp_dir)), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn("state: not initialized", text)
            self.assertIn("next step: Initialize LoopForge with `loopforge init`.", text)

    def test_status_reports_initialized_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--profile", "strict"]), 0)
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn("state: initialized", text)
            self.assertIn("profile: strict", text)
            self.assertIn("current run: none", text)
            self.assertIn('next step: Create a run with `loopforge run --task "..."`.', text)

    def test_status_reports_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Add status output"]), 0)
                self.assertEqual(main(["status"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            text = output.getvalue()
            self.assertIn(f"current run: {config['current_run_id']}", text)
            self.assertIn("task: Add status output", text)
            self.assertIn("profile: supervised", text)
            self.assertIn("loop status: ready_for_verification", text)
            self.assertIn("native artifacts: complete", text)
            self.assertIn("legacy artifacts: valid", text)
            self.assertIn("legacy issue:", text)
            self.assertIn("blockers:\n- none", text)
            self.assertIn("next step: Review the run artifacts", text)

    def test_run_without_git_uses_native_task_id_and_legacy_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Write docs without GitHub"]), 0)
                self.assertEqual(main(["status"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task_id"], run_json["run_id"])
            self.assertIsNone(run_json["base_commit"])
            self.assertEqual(run_json["legacy"]["base_commit"], "0" * 40)
            self.assertEqual(run_json["legacy"]["base_commit_source"], "synthetic_no_git_sentinel")
            self.assertIn("legacy artifacts: valid", output.getvalue())

    def test_status_reports_invalid_legacy_artifact_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Notice missing legacy file"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            (Path(run_json["legacy"]["artifact_dir"]) / "review.md").unlink()

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn("native artifacts: complete", text)
            self.assertIn("legacy artifacts: missing", text)
            self.assertIn("missing legacy artifacts: review.md", text)

    def test_status_reports_missing_current_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Lose metadata carefully"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            (loopforge_home / "runs" / repo.name / config["current_run_id"] / "run.json").unlink()

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn(f"current run: {config['current_run_id']}", text)
            self.assertIn("current run metadata not found", text)
            self.assertIn("next step: Restore the missing run artifacts or create a new run.", text)

    def test_unknown_command_still_exits_with_parser_error(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as raised:
                main(["unknown"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", output.getvalue())


if __name__ == "__main__":
    unittest.main()
