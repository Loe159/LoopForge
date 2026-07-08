from __future__ import annotations

import contextlib
import hashlib
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
from loopforge.engine import current_guidance, usable_python_executable
from loopforge.interactive import (
    InteractiveShell,
    SlashCommandCompleter,
    available_commands,
    tui_dependency_state,
)


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def fixture_python() -> str:
    executable = Path(sys.executable)
    if "WindowsApps" not in str(executable):
        return str(executable)
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "python.exe"
    )
    if bundled.exists():
        return str(bundled)
    return str(executable)


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
                    "default_adapter",
                    "default_adapter_args",
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
            self.assertEqual(config["default_adapter"], "codex")
            self.assertEqual(config["default_adapter_args"], [])
            self.assertTrue((repo / ".loopforge" / "templates" / "loop.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "memory.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "scratch.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "exchange.json").exists())
            self.assertTrue((repo / ".loopforge" / "memory.md").exists())
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
            self.assertEqual(run_json["status"], "loop_contract_draft")
            self.assertEqual(run_json["success_checks"], [])
            self.assertEqual(run_json["blockers"], [])
            self.assertEqual(run_json["loop_contract"]["status"], "loop_contract_draft")
            self.assertFalse(run_json["loop_contract"]["requires_rubric"])
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
            run_memory = (run_dir / "memory.md").read_text(encoding="utf-8")
            self.assertIn("# Durable Project Memory Snapshot", run_memory)
            self.assertIn("transcripts are intentionally omitted", run_memory)
            self.assertIn("Add a useful command", (run_dir / "task.md").read_text(encoding="utf-8"))
            loop_contract = (run_dir / "loop.md").read_text(encoding="utf-8")
            self.assertIn("# Objective", loop_contract)
            self.assertIn("# Selected Project Pack", loop_contract)
            self.assertIn("generic-code", loop_contract)
            self.assertIn("None recorded.", loop_contract)
            self.assertIn("LoopForge run created", output.getvalue())

            self.assertFalse((repo / "run.json").exists())
            self.assertFalse((repo / "attempts").exists())
            self.assertFalse((repo / "artifacts").exists())
            self.assertFalse((repo / "metrics").exists())

    def test_run_loads_compact_durable_project_memory(self) -> None:
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
                (repo / ".loopforge" / "memory.md").write_text(
                    (
                        "---\n"
                        "memory_version: 1\n"
                        "scope: project\n"
                        "status: active\n"
                        "---\n\n"
                        "# Stable Project Facts\n\n"
                        "- Tests use unittest discovery.\n\n"
                        "# User Preferences\n\n"
                        "- Prefer small CLI changes.\n\n"
                        "# Verification Patterns\n\n"
                        "# Reusable Decisions\n\n"
                        "# Known Pitfalls\n\n"
                        "# Promotion Log\n\n"
                        "- old run transcript should stay out of snapshots\n"
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(main(["run", "--task", "Use memory"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_memory = (run_dir / "memory.md").read_text(encoding="utf-8")

            self.assertIn("- Tests use unittest discovery.", run_memory)
            self.assertIn("- Prefer small CLI changes.", run_memory)
            self.assertNotIn("old run transcript", run_memory)

    def test_run_detects_python_pack_and_adds_pack_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            (repo / "pyproject.toml").write_text(
                "[project]\nname = \"sample\"\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Update Python package metadata"]),
                    0,
                )
                self.assertEqual(main(["status"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            loop_contract = (run_dir / "loop.md").read_text(encoding="utf-8")

            self.assertEqual(run_json["pack"], "python")
            self.assertEqual(run_json["pack_contract"]["detection"], "auto")
            self.assertIn("python-testing", run_json["pack_contract"]["skills"])
            self.assertIn("pack:python:SKILL.md", loop_contract)
            self.assertIn("pack: python", output.getvalue())
            self.assertIn("pack skills: 3", output.getvalue())

    def test_project_local_pack_can_add_skills_without_engine_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            (repo / "loopforge.custom").write_text("yes\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                custom_pack = repo / ".loopforge" / "packs" / "custom"
                custom_pack.mkdir(parents=True)
                (custom_pack / "pack.json").write_text(
                    json.dumps(
                        {
                            "name": "custom",
                            "version": 1,
                            "description": "Custom project pack.",
                            "priority": 50,
                            "detection": {"files_any": ["loopforge.custom"]},
                            "skills": ["custom-skill"],
                        }
                    ),
                    encoding="utf-8",
                )
                (custom_pack / "SKILL.md").write_text(
                    "# Custom Pack\n\nCustom guidance.\n",
                    encoding="utf-8",
                )
                self.assertEqual(main(["run", "--task", "Use custom pack"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            loop_contract = (run_dir / "loop.md").read_text(encoding="utf-8")

            self.assertEqual(run_json["pack"], "custom")
            self.assertIn("custom-skill", run_json["pack_contract"]["skills"])
            self.assertIn("pack:custom:SKILL.md", loop_contract)

    def test_pack_cli_lists_and_detects_packs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["pack", "list"]), 0)
                self.assertEqual(main(["pack", "detect"]), 0)

            text = output.getvalue()
            self.assertIn("generic-code:", text)
            self.assertIn("node:", text)
            self.assertIn("pack: node", text)

    def test_learn_proposes_memory_without_promoting_by_default(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Learn a fact"]), 0)
                self.assertEqual(
                    main(["learn", "--note", "Fact: Tests use unittest discovery."]),
                    0,
                )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            proposals = json.loads(
                (run_dir / "artifacts" / "memory" / "proposals.json").read_text(
                    encoding="utf-8"
                )
            )
            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")

            self.assertEqual(proposals["proposals"][0]["status"], "pending")
            self.assertIn("pending: 1", output.getvalue())
            self.assertNotIn("- Tests use unittest discovery.", durable)

    def test_learn_reads_scratch_and_exchange_candidates(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Learn from run artifacts"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            (run_dir / "scratch.md").write_text(
                (
                    "# Working Notes\n\n"
                    "- Memory: Preference: Prefer deterministic local checks.\n"
                    "- This ordinary note is temporary only.\n"
                ),
                encoding="utf-8",
            )
            (run_dir / "exchange.json").write_text(
                json.dumps(
                    {
                        "exchange_version": 1,
                        "run_id": config["current_run_id"],
                        "messages": [
                            {
                                "trusted": True,
                                "memory_candidate": (
                                    "Verification: Use unittest discovery for this package."
                                ),
                            },
                            {
                                "trusted": False,
                                "memory_candidate": "Fact: temporary handoff says remember this",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["learn"]), 0)

            proposals = json.loads(
                (run_dir / "artifacts" / "memory" / "proposals.json").read_text(
                    encoding="utf-8"
                )
            )["proposals"]
            pending = [proposal for proposal in proposals if proposal["status"] == "pending"]
            rejected = [proposal for proposal in proposals if proposal["status"] == "rejected"]

            self.assertEqual(len(pending), 2)
            self.assertEqual(len(rejected), 1)
            self.assertIn("untrusted", rejected[0]["rejection_reason"])
            self.assertIn("proposals: 3", output.getvalue())

    def test_learn_approve_promotes_safe_memory_and_records_log(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Learn a decision"]), 0)
                self.assertEqual(
                    main(
                        [
                            "learn",
                            "--approve",
                            "--note",
                            "Decision: Keep generated run artifacts outside repositories.",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["status"]), 0)

            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")
            self.assertIn(
                "- Keep generated run artifacts outside repositories.",
                durable,
            )
            self.assertIn("human_approved", durable)
            self.assertIn("promoted: 1", output.getvalue())
            self.assertIn("durable memory: 1 items", output.getvalue())

    def test_learn_rejects_secret_candidates_even_when_approved(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Reject unsafe memory"]), 0)
                self.assertEqual(
                    main(["learn", "--approve", "--note", "Fact: API token is abc123"]),
                    0,
                )

            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            proposals = json.loads(
                (run_dir / "artifacts" / "memory" / "proposals.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(proposals["proposals"][0]["status"], "rejected")
            self.assertIn("secret", proposals["proposals"][0]["rejection_reason"])
            self.assertNotIn("abc123", durable)
            self.assertIn("rejected: 1", output.getvalue())

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
            self.assertIn("loop status: loop_contract_draft", text)
            self.assertIn("native artifacts: complete", text)
            self.assertIn("loop contract: valid", text)
            self.assertIn("success checks: 0", text)
            self.assertIn("legacy artifacts: valid", text)
            self.assertIn("legacy issue:", text)
            self.assertIn("blockers:\n- none", text)
            self.assertIn("next step: Complete the loop contract", text)

    def test_shell_status_reports_not_initialized_initialized_and_current_run(self) -> None:
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
                self.assertEqual(main(["shell", "--command", "/status"]), 0)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["shell", "--command", "/status"]), 0)
                self.assertEqual(main(["run", "--task", "Add shell status"]), 0)
                self.assertEqual(main(["shell", "--command", "/status"]), 0)

            text = output.getvalue()
            self.assertIn("state: not initialized", text)
            self.assertIn("state: initialized", text)
            self.assertIn("task: Add shell status", text)
            self.assertIn("loop status: loop_contract_draft", text)

    def test_shell_plain_text_creates_run(self) -> None:
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
                self.assertEqual(main(["shell", "--command", "Add an interactive task"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Add an interactive task")
            self.assertIn("LoopForge run created", output.getvalue())

    def test_shell_script_runs_native_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            script = workspace / "commands.loopforge"
            script.write_text(
                "\n".join(
                    [
                        "/init",
                        '/run --task "Scripted loop" --success-check "contract validates"',
                        "/continue --check",
                        '/learn --note "Fact: this repo uses unittest"',
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["shell", "--script", str(script)]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["status"], "loop_contract_ready")
            self.assertTrue((run_dir / "artifacts" / "memory" / "proposals.json").exists())
            text = output.getvalue()
            self.assertIn("Loop contract accepted", text)
            self.assertIn("proposals:", text)

    def test_shell_verify_runs_pack_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".gitignore").write_text(".loopforge/\n", encoding="utf-8")
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", "README.md"],
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

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                run_command = (
                    '/run --task "Update README interactively" '
                    '--success-check "README changed"'
                )
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["shell", "--command", run_command]), 0)
                (repo / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["shell", "--command", "/verify"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["status"], "verified")
            self.assertIn("verification: passed", output.getvalue())

    def test_shell_context_and_compact(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Summarize context"]), 0)
                self.assertEqual(main(["shell", "--command", "/context"]), 0)
                self.assertEqual(main(["shell", "--command", "/compact focus on verification"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            compact_path = run_dir / "artifacts" / "context" / "compact.md"
            self.assertTrue(compact_path.exists())
            compact = compact_path.read_text(encoding="utf-8")
            self.assertIn("# LoopForge Compact Context", compact)
            self.assertIn("Focus: focus on verification", compact)
            text = output.getvalue()
            self.assertIn("LoopForge context", text)
            self.assertIn("compact path:", text)

    def test_shell_runs_and_resume(self) -> None:
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
                self.assertEqual(main(["run", "--task", "First run"]), 0)
                config_text = (repo / ".loopforge" / "config.json").read_text(encoding="utf-8")
                first = json.loads(config_text)["current_run_id"]
                self.assertEqual(main(["run", "--task", "Second run"]), 0)
                self.assertEqual(main(["shell", "--command", "/runs"]), 0)
                self.assertEqual(main(["shell", "--command", f"/resume {first}"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["current_run_id"], first)
            text = output.getvalue()
            self.assertIn("First run", text)
            self.assertIn("Second run", text)
            self.assertIn("LoopForge resumed run", text)

    def test_shell_catalog_and_unsupported_commands_are_honest(self) -> None:
        commands = available_commands()
        for name in (
            "status",
            "context",
            "compact",
            "model",
            "permissions",
            "mcp",
            "review",
            "security-review",
            "statusline",
            "keymap",
        ):
            self.assertIn(name, commands)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with working_directory(Path(temp_dir)), contextlib.redirect_stdout(output):
                self.assertEqual(main(["shell", "--command", "/model"]), 0)

            text = output.getvalue()
            self.assertIn("/model is recognized but not supported yet", text)
            self.assertIn("Model selection is owned", text)

    def test_shell_completer_supports_prompt_toolkit_async_api(self) -> None:
        completer = SlashCommandCompleter(available_commands())

        self.assertTrue(hasattr(completer, "get_completions_async"))

    def test_guidance_reports_not_initialized_and_cli_guide(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            guidance = current_guidance(repo)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["guide"]), 0)
                self.assertEqual(main(["status"]), 0)

            self.assertEqual(guidance.state, "not_initialized")
            self.assertEqual(guidance.recommended_actions[0].id, "init")
            text = output.getvalue()
            self.assertIn("guidance:", text)
            self.assertIn("recommended next action: [init]", text)
            self.assertIn("loopforge init", text)

    def test_guidance_reports_initialized_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)

            with working_directory(repo), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init"]), 0)

            guidance = current_guidance(repo)
            self.assertEqual(guidance.state, "ready_for_run")
            self.assertEqual(guidance.recommended_actions[0].id, "create-run")
            self.assertIn("loopforge run --task", guidance.recommended_actions[0].command)

    def test_guidance_reports_draft_ready_blocked_verify_failed_and_verified_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Draft run"]), 0)
                self.assertEqual(current_guidance(repo).recommended_actions[0].id, "show-plan")

                self.assertEqual(
                    main(["run", "--task", "Ready run", "--success-check", "proof exists"]),
                    0,
                )
                ready = current_guidance(repo)
                self.assertEqual(ready.state, "loop_contract_ready")
                self.assertEqual(ready.recommended_actions[0].id, "continue")

                self.assertEqual(
                    main(
                        [
                            "continue",
                            "--adapter",
                            "local-adapter-fixture",
                            "--",
                            fixture_python(),
                            "-c",
                            "import sys; print('blocked', file=sys.stderr); sys.exit(3)",
                        ]
                    ),
                    1,
                )
                blocked = current_guidance(repo)
                self.assertEqual(blocked.state, "adapter_blocked")
                self.assertEqual(blocked.recommended_actions[0].id, "inspect-attempt")

                self.assertEqual(
                    main(["run", "--task", "Verify run", "--success-check", "README changed"]),
                    0,
                )
                (repo / "README.md").write_text("# Project\n\nChanged.\n", encoding="utf-8")
                run_dir = loopforge_home / "runs" / repo.name / json.loads(
                    (repo / ".loopforge" / "config.json").read_text(encoding="utf-8")
                )["current_run_id"]
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                run_json["status"] = "ready_for_verification"
                run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
                self.assertEqual(current_guidance(repo).recommended_actions[0].id, "verify")

                self.assertEqual(main(["verify"]), 1)
                failed = current_guidance(repo)
                self.assertEqual(failed.state, "verification_failed")
                self.assertEqual(failed.recommended_actions[0].id, "inspect-verification")

                subprocess.run(
                    ["git", "init"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                (repo / ".gitignore").write_text(".loopforge/\n", encoding="utf-8")
                subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
                subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=LoopForge Tests",
                        "-c",
                        "user.email=loopforge@example.invalid",
                        "commit",
                        "-m",
                        "baseline",
                    ],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    main(["run", "--task", "Verified run", "--success-check", "README changed"]),
                    0,
                )
                (repo / "README.md").write_text("# Project\n\nVerified.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)
                verified = current_guidance(repo)
                self.assertEqual(verified.state, "verified")
                self.assertEqual(verified.recommended_actions[0].id, "compact")

    def test_guidance_reports_pending_memory_proposals(self) -> None:
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
                self.assertEqual(
                    main(["run", "--task", "Remember fact", "--success-check", "proposal exists"]),
                    0,
                )
                self.assertEqual(main(["learn", "--note", "Fact: this repo uses unittest"]), 0)

            guidance = current_guidance(repo)
            self.assertTrue(
                any(action.id == "approve-memory" for action in guidance.recommended_actions)
            )

    def test_shell_guidance_commands_and_do_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            output = io.StringIO()
            error = io.StringIO()

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(error),
            ):
                self.assertEqual(main(["shell", "--command", "/actions"]), 0)
                self.assertEqual(main(["shell", "--command", "/next"]), 0)
                self.assertEqual(main(["shell", "--command", "/why"]), 0)
                self.assertEqual(main(["shell", "--command", "/do init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Ready action", "--success-check", "proof exists"]),
                    0,
                )
                self.assertEqual(main(["shell", "--command", "/guide"]), 0)
                self.assertEqual(main(["shell", "--command", "/do continue"]), 1)
                self.assertEqual(main(["shell", "--command", "/do missing"]), 1)

            self.assertTrue((repo / ".loopforge" / "config.json").exists())
            text = output.getvalue()
            self.assertIn("Guided actions", text)
            self.assertIn("next:", text)
            self.assertIn("why [", text)
            self.assertIn("LoopForge guidance", text)
            self.assertIn("requires confirmation", error.getvalue())

    def test_init_repairs_legacy_config_with_adapter_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            config_dir = repo / ".loopforge"
            config_dir.mkdir()
            config_path = config_dir / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "project_name": repo.name,
                        "profile": "supervised",
                        "run_root": str(repo / "runs"),
                        "current_run_id": None,
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            with working_directory(repo), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init"]), 0)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["default_adapter"], "codex")
            self.assertEqual(config["default_adapter_args"], [])

    def test_shell_adapter_selection_persists_adapter_and_args(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "shell",
                            "--command",
                            "/adapter local-adapter-fixture -- python -c pass",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["shell", "--command", "/adapters"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["default_adapter"], "local-adapter-fixture")
            self.assertEqual(config["default_adapter_args"], ["python", "-c", "pass"])
            text = output.getvalue()
            self.assertIn("selected adapter: local-adapter-fixture", text)
            self.assertIn("local-adapter-fixture", text)

    def test_shell_continue_uses_selected_adapter_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            fixture_code = (
                "from pathlib import Path; "
                "Path('default-adapter.txt').write_text('ok\\n', encoding='utf-8')"
            )
            adapter_command = (
                f"/adapter local-adapter-fixture -- {fixture_python()!r} "
                f"-c {fixture_code!r}"
            )

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "shell",
                            "--command",
                            adapter_command,
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Use the selected adapter",
                            "--success-check",
                            "default-adapter.txt exists",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["shell", "--command", "/continue"]), 0)

            self.assertEqual((repo / "default-adapter.txt").read_text(encoding="utf-8"), "ok\n")
            self.assertIn("adapter: local-adapter-fixture", output.getvalue())

    def test_shell_config_and_session_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            script = repo / "prefs.loopforge"
            script.write_text(
                "\n".join(
                    [
                        "/init",
                        "/config set profile strict",
                        "/config set default-adapter claude-code",
                        "/config set adapter-args --dangerously-skip-permissions",
                        "/theme dark",
                        "/tui plain",
                        "/keymap vim",
                        "/statusline compact",
                        "/title Focus",
                        "/config show",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["shell", "--script", str(script)]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["profile"], "strict")
            self.assertEqual(config["default_adapter"], "claude-code")
            self.assertEqual(config["default_adapter_args"], ["--dangerously-skip-permissions"])
            text = output.getvalue()
            self.assertIn("theme: dark", text)
            self.assertIn("tui: plain", text)
            self.assertIn("keymap: vim", text)
            self.assertIn("statusline: compact", text)
            self.assertIn("title: Focus", text)

    def test_shell_stats_tasks_usage_cost_and_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            fixture_code = (
                "from pathlib import Path; "
                "Path('raw-output.txt').write_text('ok\\n', encoding='utf-8'); "
                "print('raw hello')"
            )

            output = io.StringIO()
            adapter_command = (
                f"/adapter local-adapter-fixture -- {fixture_python()!r} "
                f"-c {fixture_code!r}"
            )
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "shell",
                            "--command",
                            adapter_command,
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["run", "--task", "Record raw output", "--success-check", "adapter runs"]),
                    0,
                )
                self.assertEqual(main(["shell", "--command", "/continue"]), 0)
                self.assertEqual(main(["shell", "--command", "/stats"]), 0)
                self.assertEqual(main(["shell", "--command", "/usage"]), 0)
                self.assertEqual(main(["shell", "--command", "/cost"]), 0)
                self.assertEqual(main(["shell", "--command", "/tasks"]), 0)
                self.assertEqual(main(["shell", "--command", "/ps"]), 0)
                self.assertEqual(main(["shell", "--command", "/raw latest stdout"]), 0)

            text = output.getvalue()
            self.assertIn("tokens", text)
            self.assertIn("unavailable", text)
            self.assertIn("LoopForge attempts", text)
            self.assertIn("raw hello", text)

    def test_shell_memory_skills_permissions_and_review(self) -> None:
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
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Review shell evidence",
                            "--allow-tool",
                            "git",
                            "--success-check",
                            "evidence is printed",
                        ]
                    ),
                    0,
                )
                for command in (
                    "/memory",
                    "/skills",
                    "/plugins",
                    "/permissions",
                    "/allowed-tools",
                    "/sandbox",
                    "/review",
                    "/code-review",
                    "/security-review",
                    "/simplify",
                ):
                    self.assertEqual(main(["shell", "--command", command]), 0)

            text = output.getvalue()
            self.assertIn("LoopForge memory", text)
            self.assertIn("LoopForge skills", text)
            self.assertIn("allowed tools:", text)
            self.assertIn("- git", text)
            self.assertIn("local review evidence", text)

    def test_shell_copy_falls_back_to_export_and_export_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch.object(InteractiveShell, "copy_to_clipboard", return_value=False),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Export context"]), 0)
                self.assertEqual(main(["shell", "--command", "/export context"]), 0)
                self.assertEqual(main(["shell", "--command", "/copy compact"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            self.assertTrue((run_dir / "artifacts" / "exports" / "context.txt").exists())
            self.assertTrue((run_dir / "artifacts" / "exports" / "compact.txt").exists())
            self.assertIn("clipboard unavailable; exported instead", output.getvalue())

    def test_shell_fork_archive_and_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
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

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Base run", "--success-check", "base check"]),
                    0,
                )
                self.assertEqual(main(["shell", "--command", "/fork Forked run"]), 0)
                self.assertEqual(main(["shell", "--command", "/archive"]), 0)
                self.assertEqual(main(["shell", "--command", "/branch"]), 0)
                self.assertEqual(main(["shell", "--command", "/branch create shell-test"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_json_path = (
                loopforge_home
                / "runs"
                / repo.name
                / config["current_run_id"]
                / "run.json"
            )
            run_json = json.loads(
                run_json_path.read_text(encoding="utf-8")
            )
            self.assertEqual(run_json["task"], "Forked run")
            self.assertEqual(run_json["success_checks"], ["base check"])
            self.assertTrue(run_json["archived"])
            self.assertIn("LoopForge fork created", output.getvalue())
            self.assertIn("LoopForge archived run", output.getvalue())

    def test_shell_cd_add_dir_mention_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            extra = repo / "extra"
            extra.mkdir()
            mentioned = repo / "README.md"
            mentioned.write_text("# Project\n", encoding="utf-8")
            script = workspace / "context.loopforge"
            script.write_text(
                "\n".join(
                    [
                        "/cd project",
                        "/add-dir extra",
                        "/mention README.md",
                        "/context",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with working_directory(workspace), contextlib.redirect_stdout(output):
                self.assertEqual(main(["shell", "--script", str(script)]), 0)

            text = output.getvalue()
            self.assertIn(f"project dir: {repo}", text)
            self.assertIn(f"added context dir: {extra}", text)
            self.assertIn(f"mentioned: {mentioned}", text)
            self.assertIn("session context dirs:", text)
            self.assertIn("session mentions:", text)

    def test_shell_doctor_reports_missing_tui_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with (
                mock.patch(
                    "loopforge.interactive.importlib.util.find_spec",
                    return_value=None,
                ),
                working_directory(Path(temp_dir)),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["shell", "--command", "/doctor"]), 0)

            text = output.getvalue()
            self.assertIn("prompt_toolkit: missing", text)
            self.assertIn("rich: missing", text)
            self.assertEqual(tui_dependency_state()["prompt_toolkit"], True)

    def test_no_args_in_non_interactive_mode_prints_help(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main([]), 2)
        self.assertIn("usage: loopforge", error.getvalue())

    def test_shell_without_command_requires_tty(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["shell"]), 2)
        self.assertIn("requires an interactive terminal", error.getvalue())

    def test_run_records_success_checks_and_continue_accepts_contract_boundary(self) -> None:
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
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Add status output",
                            "--success-check",
                            "loopforge status prints the current run",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["continue"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["status"], "loop_contract_ready")
            self.assertEqual(
                run_json["success_checks"],
                ["loopforge status prints the current run"],
            )
            self.assertIn(
                "- loopforge status prints the current run",
                (run_dir / "loop.md").read_text(encoding="utf-8"),
            )
            self.assertIn("Loop contract accepted", output.getvalue())
            self.assertIn("Phase 4", output.getvalue())

    def test_continue_refuses_without_success_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Add status output"]), 0)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["continue"]), 1)

            text = error.getvalue()
            self.assertIn("continue refused", text)
            self.assertIn("no success checks", text)

    def test_autonomous_subjective_task_requires_rubric_before_continue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init", "--profile", "autonomous"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Improve the onboarding copy",
                            "--success-check",
                            "README contains an onboarding section",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["continue"]), 1)

            text = error.getvalue()
            self.assertIn("subjective work needs a rubric", text)

    def test_autonomous_subjective_task_accepts_rubric(self) -> None:
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
                self.assertEqual(main(["init", "--profile", "autonomous"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Improve the onboarding copy",
                            "--success-check",
                            "README contains an onboarding section",
                            "--rubric",
                            "Clear, concise, and accurate for a first-time user.",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["continue"]), 0)

            self.assertIn("Loop contract accepted", output.getvalue())

    def test_continue_fixture_adapter_records_completed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            fixture_code = (
                "from pathlib import Path\n"
                "import sys\n"
                "Path('adapter-output.txt').write_text('changed\\n', encoding='utf-8')\n"
                "print('fixture stdout')\n"
                "print('fixture stderr', file=sys.stderr)\n"
            )

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Create fixture output",
                            "--success-check",
                            "adapter-output.txt exists",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "continue",
                            "--adapter",
                            "local-adapter-fixture",
                            "--",
                            fixture_python(),
                            "-c",
                            fixture_code,
                        ]
                    ),
                    0,
                )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt = run_json["last_attempt"]
            attempt_dir = run_dir / "attempts" / "attempt-001"

            self.assertEqual(run_json["status"], "ready_for_verification")
            self.assertEqual(run_json["attempt_count"], 1)
            self.assertEqual(attempt["status"], "completed")
            self.assertTrue(attempt["workspace_changed"])
            self.assertEqual((repo / "adapter-output.txt").read_text(encoding="utf-8"), "changed\n")
            self.assertIn("fixture stdout", (attempt_dir / "adapter.stdout").read_text())
            self.assertIn("fixture stderr", (attempt_dir / "adapter.stderr").read_text())
            result = json.loads((attempt_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["workspace_changed"])
            progress = (run_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("## Attempt 1: local-adapter-fixture", progress)
            self.assertIn("Fixture command completed and changed the workspace.", progress)
            self.assertIn("LoopForge adapter attempt completed", output.getvalue())

    def test_continue_fixture_adapter_failure_blocks_readably(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Fail fixture output",
                            "--success-check",
                            "adapter succeeds",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stderr(error):
                    self.assertEqual(
                        main(
                            [
                                "continue",
                                "--adapter",
                                "local-adapter-fixture",
                                "--",
                                fixture_python(),
                                "-c",
                                "import sys; print('bad fixture', file=sys.stderr); sys.exit(3)",
                            ]
                        ),
                        1,
                    )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt_dir = run_dir / "attempts" / "attempt-001"

            self.assertEqual(run_json["status"], "adapter_blocked")
            self.assertEqual(run_json["attempt_count"], 1)
            self.assertIn("reported failed", run_json["blockers"][0])
            self.assertIn("bad fixture", (attempt_dir / "adapter.stderr").read_text())
            self.assertIn("blocked state", error.getvalue())
            self.assertIn("Fixture command failed with return code 3.", error.getvalue())

    def test_verify_generates_patch_policy_risk_and_pack_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".gitignore").write_text(".loopforge/\n", encoding="utf-8")
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", "README.md"],
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

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Update README",
                            "--success-check",
                            "README contains the new line",
                        ]
                    ),
                    0,
                )
                (repo / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)
                self.assertEqual(main(["status"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["status"], "verified")
            self.assertEqual(verification["status"], "passed")
            self.assertEqual(verification["diff_policy"]["allowed"], True)
            self.assertEqual(verification["risk"]["risk"], "low")
            self.assertEqual(verification["checks_passed"], 1)
            self.assertTrue((run_dir / "artifacts" / "patches" / "complete.patch").exists())
            self.assertIn("README.md", (run_dir / "artifacts" / "patches" / "complete.patch").read_text())
            self.assertIn("verification: passed", output.getvalue())
            self.assertIn("diff policy allowed: True", output.getvalue())
            self.assertIn("risk: low", output.getvalue())

    def test_pack_protected_paths_contribute_risk_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".gitignore").write_text(".loopforge/\n", encoding="utf-8")
            (repo / "pyproject.toml").write_text(
                "[project]\nname = \"sample\"\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )
            (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", "pyproject.toml", "sample.py"],
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

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Update Python package metadata",
                            "--success-check",
                            "pyproject version is updated",
                        ]
                    ),
                    0,
                )
                (repo / "pyproject.toml").write_text(
                    "[project]\nname = \"sample\"\nversion = \"0.2.0\"\n",
                    encoding="utf-8",
                )
                self.assertEqual(main(["verify"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["pack"], "python")
            self.assertEqual(verification["risk"]["risk"], "high")
            self.assertIn("protected-paths.json", "\n".join(verification["risk"]["policy_sources"]))
            self.assertTrue((run_dir / "artifacts" / "policies" / "risk-rules.merged.json").exists())
            self.assertIn("risk policy:", output.getvalue())

    def test_verify_repeated_equivalent_failure_marks_stagnation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".gitignore").write_text(".loopforge/\n", encoding="utf-8")
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", "README.md"],
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

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                checks_dir = repo / ".loopforge" / "packs" / "generic-code"
                checks_dir.mkdir(parents=True)
                (checks_dir / "checks.json").write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "checks": [
                                {
                                    "name": "always-fails",
                                    "command": [
                                        fixture_python(),
                                        "-c",
                                        "import sys; print('same failure'); sys.exit(7)",
                                    ],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Update README",
                            "--success-check",
                            "README contains the new line",
                        ]
                    ),
                    0,
                )
                (repo / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")

            first_error = io.StringIO()
            second_error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stderr(first_error),
            ):
                self.assertEqual(main(["verify"]), 1)
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stderr(second_error),
            ):
                self.assertEqual(main(["verify"]), 1)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = loopforge_home / "runs" / repo.name / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["status"], "verification_failed")
            self.assertEqual(verification["status"], "failed")
            self.assertTrue(verification["stagnated"])
            self.assertIn(
                "stagnation: repeated equivalent verification failure",
                "\n".join(run_json["blockers"]),
            )
            self.assertIn("pack check failed: always-fails", second_error.getvalue())

    def test_adapter_python_resolution_skips_windows_app_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            windows_apps = workspace / "AppData" / "Local" / "Microsoft" / "WindowsApps"
            windows_apps.mkdir(parents=True)
            alias = windows_apps / "python.exe"
            alias.write_text("", encoding="utf-8")
            real_python = workspace / "Python" / "python.exe"
            real_python.parent.mkdir()
            real_python.write_text("", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_PYTHON": str(real_python)}),
                mock.patch("loopforge.engine.sys.executable", str(alias)),
                mock.patch("loopforge.engine.shutil.which", return_value=str(alias)),
            ):
                self.assertEqual(usable_python_executable(), str(real_python))

    def test_imported_adapter_ignores_loopforge_runtime_metadata_for_clean_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
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
            (repo / ".loopforge").mkdir()
            (repo / ".loopforge" / "config.json").write_text("{}\n", encoding="utf-8")

            session = {
                "issue": 1,
                "risk": "low",
                "base_commit": base_commit,
                "workspace": str(repo.resolve()),
                "runner_id": "local-adapter-fixture",
                "preflight_sha256": hashlib.sha256(b"preflight").hexdigest(),
                "start_authorization_receipt_sha256": hashlib.sha256(b"start").hexdigest(),
            }
            session_path = workspace / "expected-session.json"
            session_path.write_text(json.dumps(session), encoding="utf-8")
            adapter = Path(__file__).resolve().parents[1] / ".agent" / "adapters" / "local_implementation_adapter.py"

            result = subprocess.run(
                [
                    fixture_python(),
                    str(adapter),
                    "--expected-session",
                    str(session_path),
                    "--workspace",
                    str(repo),
                    "--",
                    fixture_python(),
                    "-c",
                    "print('no workspace change')",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(
                payload["summary"],
                "Implementation command completed without workspace changes.",
            )

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
