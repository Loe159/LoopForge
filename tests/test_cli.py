from __future__ import annotations

import contextlib
import hashlib
import io
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from loopforge.cli import IssueReadResult, main, preparse_global_options
from loopforge.engine import (
    apply_initial_task_approval,
    apply_plan_approval,
    approve_review,
    command_for_attempt,
    current_guidance,
    current_status,
    loopforge_home,
    platform_cache_home,
    prepare_draft_publication,
    run_streaming_process,
    set_default_adapter,
    usable_python_executable,
)
from loopforge.cli.interactive import (
    InteractiveShell,
    SlashCommandCompleter,
    available_commands,
    contextual_commands,
    tui_dependency_state,
)
from loopforge.cli.ui import TerminalRenderer


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


def valid_research_markdown() -> str:
    return """---
artifact_version: 1
artifact: research
issue: 1
base_commit: 0000000000000000000000000000000000000000
status: complete
---

# Scope

Read-only repository orientation.

# Current State

The run is approved and ready for planning.

# Evidence

- task.md records the requested goal.

# Risks And Unknowns

- No workspace edits were made.

# Rejected Approaches

- Do not invent research without adapter output.

# Suggested Verification

- Generate a plan from this research.
"""


def valid_plan_markdown() -> str:
    return """---
artifact_version: 1
artifact: plan
issue: 1
base_commit: 0000000000000000000000000000000000000000
status: awaiting_approval
---

# Overview

Implement the approved task after human plan approval.

# Preconditions

- Research is complete.

# Implementation Steps

- Make the smallest bounded change.

# Files In Scope

- src/loopforge/engine.py

# Out Of Scope

- Publishing and deployment.

# Verification

- Run the targeted tests.

# Stop Conditions

- Stop before approval-sensitive transitions.
"""


def valid_review_markdown() -> str:
    return """---
artifact_version: 1
artifact: review
issue: 1
base_commit: 0000000000000000000000000000000000000000
status: complete
---

# Scope

Review the verified patch against the approved task and plan.

# Findings

- No blocking defect was found in the bounded patch.

# Plan Conformance

The patch remains inside the approved implementation scope.

# Test Coverage

Deterministic verification passed and the relevant checks are recorded.

# Risks And Unknowns

- External publication was not attempted.

# Recommendation

The patch is ready for explicit human review approval.
"""


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class CliTests(unittest.TestCase):
    def initialize_git_project(self, repo: Path) -> None:
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("# Project\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
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

    def approve_current_run(self, repo: Path, loopforge_home: Path) -> Path:
        config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
        run_dir = Path(config["run_root"]) / config["current_run_id"]
        run_json_path = run_dir / "run.json"
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_json = apply_initial_task_approval(
            run_json,
            approved=True,
            source="test",
        )
        run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
        return run_dir

    def approve_current_plan(self, run_dir: Path) -> None:
        run_json_path = run_dir / "run.json"
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_json["stage_statuses"]["research"] = "complete"
        run_json["stage_statuses"]["plan"] = "awaiting_approval"
        run_json["current_stage"] = "plan_ready"
        run_json["human_gates"]["plan_approval"] = {
            "required": True,
            "status": "pending",
        }
        (run_dir / "research.md").write_text(valid_research_markdown(), encoding="utf-8")
        (run_dir / "plan.md").write_text(valid_plan_markdown(), encoding="utf-8")
        run_json = apply_plan_approval(run_json, source="test")
        run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

    def approve_current_run_for_implementation(
        self,
        repo: Path,
        loopforge_home: Path,
    ) -> Path:
        run_dir = self.approve_current_run(repo, loopforge_home)
        self.approve_current_plan(run_dir)
        return run_dir

    def complete_current_review(self, run_dir: Path) -> None:
        run_json_path = run_dir / "run.json"
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_json["status"] = "verified"
        run_json["current_stage"] = "review_complete"
        run_json["stage_statuses"]["verification"] = "complete"
        run_json["stage_statuses"]["review"] = "complete"
        run_json.setdefault("verification", {})["status"] = "passed"
        run_json["human_gates"]["review_approval"] = {
            "required": True,
            "status": "pending",
        }
        run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
        (run_dir / "review.md").write_text(valid_review_markdown(), encoding="utf-8")

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
                    "project_id",
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
                str(loopforge_home() / "projects" / config["project_id"] / "runs"),
            )
            self.assertTrue(config["project_id"].startswith("project-"))
            self.assertIsNone(config["current_run_id"])
            self.assertEqual(config["default_adapter"], "codex")
            self.assertEqual(config["default_adapter_args"], [])
            self.assertTrue((repo / ".loopforge" / "templates" / "loop.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "memory.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "scratch.md").exists())
            self.assertTrue((repo / ".loopforge" / "templates" / "exchange.json").exists())
            self.assertTrue((repo / ".loopforge" / "memory.md").exists())
            self.assertIn("LoopForge project ready", output.getvalue())

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
            self.assertIn("Project already ready", output.getvalue())

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
            self.assertEqual(
                config["run_root"],
                str(loopforge_home / "projects" / config["project_id"] / "runs"),
            )

            run_dir = Path(config["run_root"]) / run_id
            self.assertTrue(run_dir.exists())
            self.assertFalse(run_dir.is_relative_to(repo))

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["run_id"], run_id)
            self.assertEqual(run_json["task_id"], run_id)
            self.assertEqual(run_json["task"], "Add a useful command")
            self.assertEqual(run_json["project_root"], str(repo.resolve()))
            self.assertEqual(run_json["base_commit"], base_commit)
            self.assertEqual(run_json["workspace"]["mode"], "git-worktree")
            workspace_dir = Path(run_json["workspace"]["path"])
            self.assertTrue(workspace_dir.exists())
            self.assertFalse(workspace_dir.is_relative_to(repo))
            workspace_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(workspace_head, base_commit)
            self.assertEqual(run_json["profile"], "supervised")
            self.assertEqual(run_json["pack"], "generic-code")
            self.assertEqual(run_json["status"], "loop_contract_draft")
            self.assertEqual(run_json["current_stage"], "task_draft")
            self.assertEqual(
                set(run_json["stage_statuses"]),
                {
                    "task",
                    "research",
                    "plan",
                    "implementation",
                    "verification",
                    "review",
                    "publication",
                },
            )
            self.assertEqual(run_json["stage_statuses"]["task"], "draft")
            self.assertEqual(
                run_json["approval"],
                {"approved": False, "source": "none", "approved_at": None},
            )
            self.assertEqual(
                run_json["risk"],
                {"level": "unknown", "route": "unknown", "reasons": []},
            )
            self.assertEqual(
                run_json["human_gates"]["initial_task_approval"]["status"],
                "pending",
            )
            self.assertTrue(run_json["human_gates"]["initial_task_approval"]["required"])
            self.assertEqual(run_json["human_gates"]["plan_approval"]["status"], "pending")
            self.assertTrue(run_json["human_gates"]["plan_approval"]["required"])
            self.assertEqual(run_json["human_gates"]["review_approval"]["status"], "pending")
            self.assertTrue(run_json["human_gates"]["review_approval"]["required"])
            self.assertFalse(run_json["publish_eligibility"]["eligible"])
            self.assertTrue(run_json["publish_eligibility"]["reasons"])
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
            self.assertIn("Run created", output.getvalue())

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
                self.assertEqual(main(["status", "--details"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            loop_contract = (run_dir / "loop.md").read_text(encoding="utf-8")

            self.assertEqual(run_json["pack"], "python")
            self.assertEqual(run_json["pack_contract"]["detection"], "auto")
            self.assertIn("python-testing", run_json["pack_contract"]["skills"])
            self.assertIn("pack:python:SKILL.md", loop_contract)
            self.assertIn("pack    python", output.getvalue())
            self.assertIn("pack skills: 8", output.getvalue())
            self.assertIn("pack agents: 4", output.getvalue())

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            self.assertIn("current | name | skills | agents | stages | kind", text)
            self.assertIn("generic-code", text)
            self.assertIn("node", text)
            self.assertIn("pack    node", text)

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            proposals = json.loads(
                (run_dir / "artifacts" / "memory" / "proposals.json").read_text(
                    encoding="utf-8"
                )
            )
            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")

            self.assertEqual(proposals["proposals"][0]["status"], "pending")
            self.assertRegex(output.getvalue(), r"pending\s+1")
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            self.assertRegex(output.getvalue(), r"pending\s+2")
            self.assertRegex(output.getvalue(), r"rejected\s+1")

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
                self.assertEqual(main(["status", "--details"]), 0)

            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")
            self.assertIn(
                "- Keep generated run artifacts outside repositories.",
                durable,
            )
            self.assertIn("human_approved", durable)
            self.assertRegex(output.getvalue(), r"promoted\s+1")
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            proposals = json.loads(
                (run_dir / "artifacts" / "memory" / "proposals.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(proposals["proposals"][0]["status"], "rejected")
            self.assertIn("secret", proposals["proposals"][0]["rejection_reason"])
            self.assertNotIn("abc123", durable)
            self.assertRegex(output.getvalue(), r"rejected\s+1")

    def test_run_auto_initializes_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            home = repo / "loopforge-home"
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--task", "Do the thing"]), 0)
            config_path = repo / ".loopforge" / "config.json"
            self.assertTrue(config_path.exists())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIsInstance(config["current_run_id"], str)
            self.assertIn("Initialized LoopForge metadata", output.getvalue())

    def test_status_reports_not_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with working_directory(Path(temp_dir)), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn("status   not initialized", text)
            self.assertIn("Next\nloopforge init", text)

    def test_status_reports_initialized_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--profile", "strict"]), 0)
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn("status   ready_for_run", text)
            self.assertIn("profile  strict", text)
            self.assertIn("run      none", text)
            self.assertIn("Next", text)

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
                self.assertEqual(main(["status", "--details"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            text = output.getvalue()
            self.assertIn(f"run     {config['current_run_id']}", text)
            self.assertIn("task    Add status output", text)
            self.assertIn("profile  supervised", text)
            self.assertIn("status  loop_contract_draft", text)
            self.assertIn("native artifacts: complete", text)
            self.assertIn("loop contract: valid", text)
            self.assertIn("success checks: 0", text)
            self.assertIn("legacy artifacts: valid", text)
            self.assertIn("legacy issue:", text)
            self.assertIn("blockers:\n- none", text)
            self.assertIn("Next", text)

    def test_status_details_handles_legacy_run_without_workflow_fields(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Read old run metadata"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_json_path = Path(config["run_root"]) / config["current_run_id"] / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            for key in (
                "current_stage",
                "stage_statuses",
                "approval",
                "risk",
                "human_gates",
                "publish_eligibility",
            ):
                run_json.pop(key, None)
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

            details_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(details_output),
            ):
                self.assertEqual(main(["status", "--details"]), 0)

            status = current_status(repo)
            guidance = current_guidance(repo)
            self.assertIsNotNone(status.run)
            assert status.run is not None
            self.assertEqual(status.run["current_stage"], "task_draft")
            self.assertEqual(status.run["stage_statuses"]["publication"], "pending")
            self.assertFalse(status.run["approval"]["approved"])
            self.assertEqual(guidance.state, "task_needs_input")
            self.assertIn("workflow stage: task_draft", details_output.getvalue())

    def test_status_default_is_compact_and_details_hold_artifacts(self) -> None:
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
                self.assertEqual(main(["run", "--task", "Check compact status"]), 0)

            compact_output = io.StringIO()
            details_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(compact_output),
            ):
                self.assertEqual(main(["status"]), 0)
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(details_output),
            ):
                self.assertEqual(main(["status", "--details"]), 0)

            compact_text = compact_output.getvalue()
            self.assertIn("Current loop", compact_text)
            self.assertIn("Next", compact_text)
            self.assertNotIn("legacy artifact directory", compact_text)
            self.assertLessEqual(len([line for line in compact_text.splitlines() if line]), 13)
            self.assertIn("legacy artifact directory", details_output.getvalue())

    def test_quiet_success_output_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with working_directory(Path(temp_dir)), contextlib.redirect_stdout(output):
                self.assertEqual(main(["init", "--quiet"]), 0)
            self.assertEqual(output.getvalue(), "")

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
                self.assertEqual(main(["shell", "--command", "/status details"]), 0)

            text = output.getvalue()
            self.assertIn("status   not initialized", text)
            self.assertIn("status   ready_for_run", text)
            self.assertIn("task    Add shell status", text)
            self.assertIn("status  loop_contract_draft", text)
            self.assertIn("native artifacts: complete", text)

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Add an interactive task")
            self.assertIn("Run created", output.getvalue())

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["status"], "loop_contract_ready")
            self.assertTrue((run_dir / "artifacts" / "memory" / "proposals.json").exists())
            text = output.getvalue()
            self.assertIn("Run created", text)
            self.assertIn("Memory proposals ready", text)

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["status"], "verified")
            self.assertIn("Verified", output.getvalue())
            self.assertIn("status  passed", output.getvalue())

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
                self.assertEqual(main(["shell", "--command", "/commands"]), 0)
                self.assertEqual(main(["shell", "--command", "/commands all"]), 0)
                self.assertEqual(main(["shell", "--command", "/model"]), 0)

            text = output.getvalue()
            useful_catalog, full_catalog = text.split("Use /commands all", 1)
            self.assertIn("/status", useful_catalog)
            self.assertNotIn("/model", useful_catalog)
            self.assertIn("/model", full_catalog)
            self.assertIn("/model is recognized but not supported yet", text)
            self.assertIn("Model selection is owned", text)

    def test_shell_discovery_is_contextual_and_hides_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            commands = contextual_commands(project)
            completer = SlashCommandCompleter(project_dir=project)

        self.assertIn("init", commands)
        self.assertNotIn("model", commands)
        self.assertNotIn("quit", commands)
        self.assertNotIn("adapters", commands)
        self.assertEqual(commands, completer.commands)

    def test_shell_preferences_are_user_scoped_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project = workspace / "project"
            project.mkdir()
            home = workspace / "home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(home)}):
                shell = InteractiveShell(project, output=io.StringIO())
                self.assertEqual(shell.dispatch("/theme dark").exit_code, 0)
                self.assertEqual(shell.dispatch("/statusline compact").exit_code, 0)
                self.assertEqual(shell.dispatch("/vim").exit_code, 0)
                restored = InteractiveShell(project, output=io.StringIO())

            preferences = json.loads((home / "preferences.json").read_text(encoding="utf-8"))

        self.assertEqual(preferences, {"keymap": "vim", "statusline": "compact", "theme": "dark"})
        self.assertEqual(restored.theme, "dark")
        self.assertEqual(restored.statusline, "compact")
        self.assertEqual(restored.editing_mode, "vim")

    def test_shell_completer_supports_prompt_toolkit_async_api(self) -> None:
        completer = SlashCommandCompleter(available_commands())

        self.assertTrue(hasattr(completer, "get_completions_async"))

    def test_renderer_plain_mode_does_not_emit_ansi(self) -> None:
        output = io.StringIO()
        renderer = TerminalRenderer(output, mode="plain")

        renderer.panel("LoopForge status", ["state: initialized"])

        text = output.getvalue()
        self.assertIn("LoopForge status", text)
        self.assertNotIn("\x1b[", text)

    def test_renderer_rich_mode_forces_styles_for_tests(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"TERM": "xterm-256color"},
            clear=True,
        ):
            renderer = TerminalRenderer(output, mode="rich")

            renderer.panel("LoopForge status", ["state: initialized"])

        self.assertIn("\x1b[", output.getvalue())

    def test_renderer_auto_mode_respects_no_color(self) -> None:
        output = TtyStringIO()

        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            renderer = TerminalRenderer(output, mode="auto")
            renderer.panel("LoopForge status", ["state: initialized"])

        text = output.getvalue()
        self.assertIn("LoopForge status", text)
        self.assertNotIn("\x1b[", text)

    def test_renderer_auto_mode_respects_loopforge_no_color_and_term_dumb(self) -> None:
        for env in ({"LOOPFORGE_NO_COLOR": "1"}, {"TERM": "dumb"}):
            output = TtyStringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                renderer = TerminalRenderer(output, mode="auto")
                renderer.panel("LoopForge status", ["state: initialized"])
            self.assertNotIn("\x1b[", output.getvalue())

    def test_plain_global_option_forces_plain_output_even_when_color_is_forced(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(main(["--plain", "status"]), 0)

        self.assertNotIn("\x1b[", output.getvalue())

    def test_plain_and_interactive_ui_are_global_options(self) -> None:
        options, argv = preparse_global_options(["--plain", "--interactive-ui", "status"])

        self.assertTrue(options.plain)
        self.assertTrue(options.interactive_ui)
        self.assertEqual(argv, ["status"])

    def test_plain_preserves_json_machine_output(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--plain", "status", "--format", "json"]), 0)

        self.assertIsInstance(json.loads(output.getvalue()), dict)

    def test_version_commands_report_runtime_details(self) -> None:
        for args in (["--version"], ["-V"], ["version"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 0)
            text = output.getvalue()
            self.assertIn("LoopForge 0.1.0", text)
            self.assertIn("python:", text)
            self.assertIn("LoopForge home:", text)

    def test_version_json_is_single_payload(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["version", "--json"]), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"]["loopforge_version"], "0.1.0")

    def test_help_command_supports_nested_topics_and_unknown_topic_errors(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["help", "pack", "list"]), 0)
        self.assertIn("usage: loopforge pack list", output.getvalue())

        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["help", "rnu"]), 2)
        text = error.getvalue()
        self.assertIn("LF_HELP_TOPIC_UNKNOWN", text)
        self.assertIn("loopforge help run", text)

    def test_help_describes_run_cockpit_without_workflow_flag(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["help"]), 0)
        text = output.getvalue()
        self.assertIn("run` is the cockpit", text)
        self.assertIn("one approved stage at a time", text)
        self.assertNotIn("--workflow", text)

        run_output = io.StringIO()
        with contextlib.redirect_stdout(run_output):
            self.assertEqual(main(["help", "run"]), 0)
        run_text = run_output.getvalue()
        self.assertIn("`loopforge run` is the cockpit", run_text)
        self.assertIn("task approval", run_text)
        self.assertIn("read-only research", run_text)
        self.assertIn("read-only plan", run_text)
        self.assertIn("plan approval", run_text)
        self.assertIn("deterministic verification", run_text)
        self.assertIn("review approval", run_text)
        self.assertIn("local draft PR publication artifact", run_text)
        self.assertIn("agent:approved", run_text)
        self.assertIn("Verification is evidence for review", run_text)
        self.assertIn("never approves, executes, or publishes", run_text)
        self.assertNotIn("--workflow", run_text)

    def test_readme_documents_run_cockpit_workflow(self) -> None:
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        readme_flat = " ".join(readme.split())
        self.assertIn("`loopforge run` is the cockpit", readme)
        self.assertIn("task approval", readme)
        self.assertIn("read-only research", readme)
        self.assertIn("read-only planning", readme)
        self.assertIn("approve the plan before implementation", readme)
        self.assertIn("deterministic verification", readme)
        self.assertIn("explicit review approval", readme)
        self.assertIn("local draft PR publication artifact", readme)
        self.assertIn("Verification produces local evidence for review", readme)
        self.assertIn("does not authorize publication", readme)
        self.assertIn("does not push branches, open PRs, or publish to the network", readme_flat)
        self.assertNotIn("--workflow", readme)

    def test_no_input_blocks_implicit_shell(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["--no-input"]), 2)
        self.assertIn("LF_INPUT_REQUIRED", error.getvalue())

    def test_run_without_task_errors_in_non_interactive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["run", "--no-input"]), 2)
            self.assertIn("LF_INPUT_REQUIRED", error.getvalue())

    def test_run_without_task_prompts_when_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            output = io.StringIO()
            answers = iter(
                [
                    "2",
                    "Prompted task",
                    "Fails on startup",
                    "Startup test passes",
                    "y",
                    "y",
                    "y",
                    "n",
                ]
            )
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Prompted task\n\nContext: Fails on startup")
            self.assertIn("Startup test passes", run_json["success_checks"])
            self.assertEqual(run_json["current_stage"], "task_approved")
            self.assertEqual(
                run_json["approval"]["source"],
                "local/manual",
            )
            self.assertIn("Next\nloopforge run", output.getvalue())

    def test_run_with_active_run_interactive_can_resume_without_creating_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "First task"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            first_run_id = config["current_run_id"]

            output = io.StringIO()
            answers = iter(["1"])
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            updated = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["current_run_id"], first_run_id)
            self.assertEqual(len(list((Path(config["run_root"])).iterdir())), 1)
            text = output.getvalue()
            self.assertIn("Active LoopForge run", text)
            self.assertIn("Current loop", text)
            self.assertIn(first_run_id, text)
            self.assertIn("Next", text)

    def test_run_with_active_run_no_input_reports_cockpit_text_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "First task"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            first_run_id = config["current_run_id"]

            text_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(text_output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            updated = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["current_run_id"], first_run_id)
            self.assertEqual(len(list((Path(config["run_root"])).iterdir())), 1)
            self.assertIn("Active run found", text_output.getvalue())
            self.assertIn(first_run_id, text_output.getvalue())

            json_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(json_output),
            ):
                self.assertEqual(main(["run", "--no-input", "--format", "json"]), 0)

            updated = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["current_run_id"], first_run_id)
            self.assertEqual(len(list((Path(config["run_root"])).iterdir())), 1)
            payload = json.loads(json_output.getvalue())
            self.assertEqual(payload["action"], "active_run")
            self.assertEqual(payload["status"]["config"]["current_run_id"], first_run_id)
            self.assertEqual(payload["status"]["run"]["run_id"], first_run_id)
            self.assertTrue(payload["guidance"]["recommended_actions"])

    def test_run_cockpit_does_not_offer_research_for_unapproved_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            fixture_code = f"import sys; sys.stdout.write({valid_research_markdown()!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(main(["run", "--task", "Needs approval first"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]

            answers = iter(["1"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["stage_statuses"]["research"], "pending")
            self.assertEqual(run_json["current_stage"], "task_draft")
            self.assertNotEqual(
                (run_dir / "research.md").read_text(encoding="utf-8"),
                valid_research_markdown(),
            )

    def test_run_cockpit_executes_research_with_fixture_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            fixture_code = f"import sys; sys.stdout.write({valid_research_markdown()!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(
                    main(["run", "--task", "Research the change", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            workspace_dir = Path(run_json["workspace"]["path"])
            git_status = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=workspace_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual((run_dir / "research.md").read_text(encoding="utf-8"), valid_research_markdown())
            self.assertEqual(git_status, "")
            self.assertEqual(run_json["current_stage"], "research_ready")
            self.assertEqual(run_json["stage_statuses"]["research"], "complete")
            self.assertIn("Research ready", output.getvalue())

    def test_incomplete_task_cannot_be_approved_or_researched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "Ambiguous change"]), 0)

            run_dir = self.approve_current_run(repo, loopforge_home)
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            guidance = current_guidance(repo)

            self.assertEqual(run_json["task_validation"]["status"], "needs_input")
            self.assertIn("objective success check", run_json["task_validation"]["missing"])
            self.assertFalse(run_json["approval"]["approved"])
            self.assertEqual(run_json["stage_statuses"]["task"], "draft")
            self.assertEqual(run_json["stage_statuses"]["research"], "pending")
            self.assertEqual(guidance.state, "task_needs_input")
            self.assertEqual(guidance.recommended_actions[0].id, "complete-task")

    def test_run_cockpit_executes_plan_with_fixture_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            fixture_code = f"import sys; sys.stdout.write({valid_plan_markdown()!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(
                    main(["run", "--task", "Plan the change", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["stage_statuses"]["research"] = "complete"
            run_json["current_stage"] = "research_ready"
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
            (run_dir / "research.md").write_text(valid_research_markdown(), encoding="utf-8")

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual((run_dir / "plan.md").read_text(encoding="utf-8"), valid_plan_markdown())
            self.assertEqual(run_json["current_stage"], "plan_ready")
            self.assertEqual(run_json["stage_statuses"]["plan"], "awaiting_approval")
            self.assertEqual(run_json["human_gates"]["plan_approval"]["status"], "pending")
            self.assertIn("Plan ready", output.getvalue())

    def test_run_cockpit_executes_review_with_fixture_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            fixture_code = f"import sys; sys.stdout.write({valid_review_markdown()!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(
                    main(["run", "--task", "Review the patch", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "verification_ready"
            run_json["stage_statuses"]["implementation"] = "complete"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "pending"
            run_json.setdefault("verification", {})["status"] = "passed"
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual((run_dir / "review.md").read_text(encoding="utf-8"), valid_review_markdown())
            self.assertEqual(run_json["current_stage"], "review_complete")
            self.assertEqual(run_json["stage_statuses"]["review"], "complete")
            self.assertEqual(run_json["human_gates"]["review_approval"]["status"], "pending")
            prompt = (run_dir / "artifacts" / "stages" / "review" / "prompt.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("- Agent: reviewer", prompt)
            self.assertIn("- Permission set: read-only", prompt)
            self.assertIn('"network": "deny"', prompt)
            self.assertIn("# Reviewer", prompt)
            self.assertIn("Review ready", output.getvalue())

    def test_run_cockpit_approves_plan_for_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Approve the plan", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["stage_statuses"]["research"] = "complete"
            run_json["stage_statuses"]["plan"] = "awaiting_approval"
            run_json["current_stage"] = "plan_ready"
            run_json["human_gates"]["plan_approval"] = {
                "required": True,
                "status": "pending",
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
            (run_dir / "plan.md").write_text(valid_plan_markdown(), encoding="utf-8")

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            plan_gate = run_json["human_gates"]["plan_approval"]
            self.assertEqual(run_json["current_stage"], "implementation_ready")
            self.assertEqual(run_json["stage_statuses"]["plan"], "approved")
            self.assertEqual(plan_gate["status"], "approved")
            self.assertEqual(plan_gate["source"], "local")
            self.assertTrue(plan_gate["approved_at"])
            self.assertEqual(run_json["blockers"], [])
            self.assertIn("Plan approved", output.getvalue())

    def test_run_no_input_does_not_approve_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Do not approve plan", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["stage_statuses"]["research"] = "complete"
            run_json["stage_statuses"]["plan"] = "awaiting_approval"
            run_json["current_stage"] = "plan_ready"
            run_json["human_gates"]["plan_approval"] = {
                "required": True,
                "status": "pending",
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
            (run_dir / "plan.md").write_text(valid_plan_markdown(), encoding="utf-8")

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual(run_json["current_stage"], "plan_ready")
            self.assertEqual(run_json["stage_statuses"]["plan"], "awaiting_approval")
            self.assertEqual(run_json["human_gates"]["plan_approval"]["status"], "pending")
            self.assertIn("Active run found", output.getvalue())

    def test_run_cockpit_approves_review_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

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
                            "Verify then review",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)
                self.complete_current_review(run_dir)

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            review_gate = run_json["human_gates"]["review_approval"]
            self.assertEqual(run_json["current_stage"], "review_ready")
            self.assertEqual(run_json["stage_statuses"]["verification"], "complete")
            self.assertEqual(run_json["stage_statuses"]["review"], "approved")
            self.assertEqual(review_gate["status"], "approved")
            self.assertEqual(review_gate["source"], "local")
            self.assertTrue(review_gate["approved_at"])
            self.assertTrue(run_json["publish_eligibility"]["eligible"])
            self.assertEqual(run_json["publish_eligibility"]["mode"], "draft")
            self.assertIn("Review approved", output.getvalue())

    def test_run_no_input_does_not_approve_review_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

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
                            "Verify without review approval",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual(run_json["current_stage"], "verification_ready")
            self.assertEqual(run_json["stage_statuses"]["verification"], "complete")
            self.assertEqual(run_json["stage_statuses"]["review"], "pending")
            self.assertEqual(run_json["human_gates"]["review_approval"]["status"], "pending")
            self.assertFalse(run_json["publish_eligibility"]["eligible"])
            self.assertIn("Active run found", output.getvalue())

    def test_run_cockpit_after_review_prepares_draft_pr_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

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
                            "Prepare a draft PR",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)
                self.complete_current_review(run_dir)

            answers = iter(["1", "y"])
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["run"]), 0)

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            artifact_path = run_dir / "artifacts" / "publication" / "draft-pr.json"
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            patch = run_json["verification"]["patch"]
            self.assertEqual(run_json["current_stage"], "draft_publication_ready")
            self.assertEqual(run_json["stage_statuses"]["publication"], "draft_prepared")
            self.assertEqual(run_json["publish_eligibility"]["status"], "prepared")
            self.assertEqual(run_json["publication"]["status"], "draft_prepared")
            self.assertEqual(run_json["blockers"], [])
            self.assertTrue(payload["draft"])
            self.assertTrue(payload["no_network"])
            self.assertFalse(payload["network"]["performed"])
            self.assertEqual(payload["publisher"], "local-draft-artifact")
            self.assertEqual(payload["task"], "Prepare a draft PR")
            self.assertEqual(payload["patch"]["path"], patch["path"])
            self.assertEqual(payload["patch"]["sha256"], patch["sha256"])
            self.assertEqual(payload["verification"]["patch"]["sha256"], patch["sha256"])
            self.assertEqual(payload["base_commit"], run_json["base_commit"])
            self.assertEqual(payload["branch"], f"loopforge/{run_json['run_id']}")
            self.assertIn("Draft publication prepared", output.getvalue())

    def test_run_no_input_after_review_does_not_prepare_draft_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

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
                            "Leave draft publication unprepared",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                self.assertEqual(main(["verify"]), 0)
                self.complete_current_review(run_dir)
                self.assertTrue(approve_review(repo, source="test").ok)

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            artifact_path = run_dir / "artifacts" / "publication" / "draft-pr.json"
            self.assertEqual(run_json["current_stage"], "review_ready")
            self.assertEqual(run_json["stage_statuses"]["publication"], "pending")
            self.assertFalse(artifact_path.exists())
            self.assertIn("Active run found", output.getvalue())

    def test_prepare_draft_publication_blocks_without_review_or_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

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
                            "Do not publish",
                            "--success-check",
                            "Tests pass",
                        ]
                    ),
                    0,
                )
                result = prepare_draft_publication(repo)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(result.ok)
            self.assertTrue(any("publish eligibility" in blocker for blocker in result.blockers))
            self.assertTrue(any("review approval" in blocker for blocker in result.blockers))
            self.assertTrue(any("verification" in blocker for blocker in result.blockers))
            self.assertTrue(any("patch" in blocker for blocker in result.blockers))
            self.assertEqual(run_json["stage_statuses"]["publication"], "pending")
            self.assertFalse((run_dir / "artifacts" / "publication" / "draft-pr.json").exists())

    def test_run_cockpit_blocks_readonly_stage_when_fixture_changes_worktree(self) -> None:
        for stage, artifact in (
            ("research", valid_research_markdown()),
            ("plan", valid_plan_markdown()),
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                repo = workspace / "project"
                repo.mkdir()
                self.initialize_git_project(repo)
                loopforge_home = workspace / "home"
                fixture_code = (
                    "from pathlib import Path; import sys; "
                    "Path('changed.txt').write_text('changed\\n', encoding='utf-8'); "
                    f"sys.stdout.write({artifact!r})"
                )
                with (
                    mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                    working_directory(repo),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(["init"]), 0)
                    self.assertTrue(
                        set_default_adapter(
                            repo,
                            "local-adapter-fixture",
                            [fixture_python(), "-c", fixture_code],
                        ).ok
                    )
                    self.assertEqual(
                        main(["run", "--task", f"{stage} change", "--success-check", "Tests pass"]),
                        0,
                    )
                run_dir = self.approve_current_run(repo, loopforge_home)
                run_json_path = run_dir / "run.json"
                if stage == "plan":
                    run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                    run_json["stage_statuses"]["research"] = "complete"
                    run_json["current_stage"] = "research_ready"
                    run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
                    (run_dir / "research.md").write_text(valid_research_markdown(), encoding="utf-8")

                answers = iter(["1", "y"])
                error = io.StringIO()
                with (
                    mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                    mock.patch("sys.stdin", TtyStringIO()),
                    mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                    working_directory(repo),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(error),
                ):
                    self.assertEqual(main(["run"]), 1)

                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                self.assertEqual(run_json["stage_statuses"][stage], "blocked")
                self.assertIn("changed the worktree", "\n".join(run_json["blockers"]))
                self.assertIn(f"{stage.title()} blocked", error.getvalue())
                self.assertNotEqual(
                    (run_dir / f"{stage}.md").read_text(encoding="utf-8"),
                    artifact,
                )

    def test_run_cockpit_blocks_readonly_stage_with_invalid_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            invalid_research = valid_research_markdown().replace(
                "issue: 1\nbase_commit: 0000000000000000000000000000000000000000\n",
                "",
            )
            fixture_code = f"import sys; sys.stdout.write({invalid_research!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(
                    main(["run", "--task", "Validate research", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)

            answers = iter(["1", "y"])
            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(error),
            ):
                self.assertEqual(main(["run"]), 1)

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            blockers = "\n".join(run_json["blockers"])
            self.assertEqual(run_json["stage_statuses"]["research"], "blocked")
            self.assertIn("frontmatter must include issue", blockers)
            self.assertIn("frontmatter must include base_commit", blockers)
            self.assertNotEqual(
                (run_dir / "research.md").read_text(encoding="utf-8"),
                invalid_research,
            )
            self.assertIn("Research blocked", error.getvalue())

    def test_run_no_input_does_not_execute_available_readonly_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "home"
            fixture_code = f"import sys; sys.stdout.write({valid_research_markdown()!r})"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertTrue(
                    set_default_adapter(
                        repo,
                        "local-adapter-fixture",
                        [fixture_python(), "-c", fixture_code],
                    ).ok
                )
                self.assertEqual(
                    main(["run", "--task", "Do not auto research", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run(repo, loopforge_home)

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["stage_statuses"]["research"], "pending")
            self.assertNotEqual(
                (run_dir / "research.md").read_text(encoding="utf-8"),
                valid_research_markdown(),
            )
            self.assertIn("Active run found", output.getvalue())

    def test_run_with_task_can_replace_active_current_run_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "First task"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            first_run_id = config["current_run_id"]

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--task", "Second explicit task"]), 0)

            updated = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertNotEqual(updated["current_run_id"], first_run_id)
            self.assertEqual(len(list((Path(config["run_root"])).iterdir())), 2)
            text = output.getvalue()
            self.assertIn("Previous current run", text)
            self.assertIn(f"Replaced {first_run_id}", text)

    def test_run_wizard_uses_selected_default_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            output = io.StringIO()
            answers = iter(
                [
                    "2",
                    "Adapter-neutral task",
                    "",
                    "Proof exists",
                    "y",
                    "y",
                    "y",
                    "n",
                ]
            )
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init"]), 0)
                update = set_default_adapter(
                    repo,
                    "claude-code",
                    ["--dangerously-skip-permissions"],
                )
                self.assertTrue(update.ok, update.message)
                self.assertEqual(main(["run"]), 0)

            text = output.getvalue()
            self.assertIn("Next\nloopforge run", text)
            self.assertNotIn("Launch Codex now", text)

    def test_run_with_task_remains_prompt_free_when_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=AssertionError("unexpected prompt")),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Scripted task",
                            "--success-check",
                            "tests pass",
                            "--allow-tool",
                            "Run tests only",
                        ]
                    ),
                    0,
                )
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Scripted task")
            self.assertEqual(run_json["success_checks"], ["tests pass"])

    def test_run_issue_id_uses_inferred_github_remote_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            issue = {
                "number": 42,
                "title": "Broken startup",
                "body": "Untrusted issue text",
                "url": "https://github.com/acme/app/issues/42",
                "labels": [{"name": "agent:approved"}],
            }
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("loopforge.cli.github_repo_from_remote", return_value=("acme", "app")),
                mock.patch("loopforge.cli.gh_issue_view", return_value=IssueReadResult(True, issue=issue)),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "42", "--no-input"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Resolve GitHub issue #42: Broken startup")
            self.assertEqual(
                run_json["evidence"]["source"]["reference"],
                "acme/app#42",
            )
            self.assertEqual(run_json["evidence"]["source"]["memory"], "not_promoted_to_durable_memory")
            self.assertEqual(run_json["current_stage"], "task_approved")
            self.assertEqual(
                run_json["approval"],
                {
                    "approved": True,
                    "source": "github",
                    "approved_at": run_json["approval"]["approved_at"],
                },
            )
            self.assertIsInstance(run_json["approval"]["approved_at"], str)
            self.assertEqual(
                run_json["human_gates"]["initial_task_approval"]["status"],
                "approved",
            )

    def test_run_issue_without_agent_approved_label_errors_before_creating_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            issue = {
                "number": 42,
                "title": "Broken startup",
                "body": "Untrusted issue text",
                "url": "https://github.com/acme/app/issues/42",
                "labels": [{"name": "bug"}],
            }
            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("loopforge.cli.github_repo_from_remote", return_value=("acme", "app")),
                mock.patch("loopforge.cli.gh_issue_view", return_value=IssueReadResult(True, issue=issue)),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["run", "42", "--no-input"]), 2)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertIsNone(config["current_run_id"])
            self.assertIn("LF_GITHUB_APPROVAL_REQUIRED", error.getvalue())

    def test_run_issue_id_without_remote_errors_non_interactively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("loopforge.cli.github_repo_from_remote", return_value=None),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["run", "123", "--no-input"]), 2)
            self.assertIn("LF_ISSUE_SOURCE_UNRESOLVED", error.getvalue())

    def test_run_issue_url_refuses_when_approval_cannot_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            error = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("loopforge.cli.shutil.which", return_value=None),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(["run", "https://github.com/acme/app/issues/5"]), 2)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertIsNone(config["current_run_id"])
            self.assertIn("LF_GITHUB_APPROVAL_UNAVAILABLE", error.getvalue())

    def test_run_can_select_open_github_issue_when_provider_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            answers = iter(["1", "", "1", "", "", "y", "y", "n"])
            issue_list = {
                "issues": [
                    {
                        "number": 7,
                        "title": "Open issue",
                        "url": "https://github.com/acme/app/issues/7",
                        "labels": ["agent:approved"],
                    }
                ]
            }
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("loopforge.cli.gh_issue_list", return_value=IssueReadResult(True, issue=issue_list)),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run"]), 0)
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["task"], "Resolve GitHub issue #7: Open issue")
            self.assertEqual(run_json["evidence"]["source"]["reference"], "acme/app#7")

    def test_status_json_has_no_human_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status", "--json"]), 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIn("status", payload)

    def test_runs_supports_table_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["run", "--task", "List runs"]), 0)

            json_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(json_output),
            ):
                self.assertEqual(main(["runs", "--format", "json"]), 0)
            payload = json.loads(json_output.getvalue())
            self.assertTrue(payload["rows"])

            csv_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(csv_output),
            ):
                self.assertEqual(main(["runs", "--format", "csv", "--columns", "run_id,status"]), 0)
            self.assertIn("run_id,status", csv_output.getvalue())

    def test_completion_outputs_shell_script(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["completion", "powershell"]), 0)
        self.assertIn("Register-ArgumentCompleter", output.getvalue())

    def test_discovery_commands_do_not_query_project_state(self) -> None:
        for args in (["version"], ["help"], ["completion", "bash"]):
            output = io.StringIO()
            with (
                mock.patch("loopforge.cli.current_status", side_effect=AssertionError),
                mock.patch("loopforge.cli.current_guidance", side_effect=AssertionError),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(args), 0)

    def test_global_flags_work_after_command_and_before_adapter_separator(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["status", "--json", "--quiet"]), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])

        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            loopforge_home_dir = repo / "home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home_dir)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Keep adapter separator",
                            "--success-check",
                            "adapter runs",
                        ]
                    ),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home_dir)
                self.assertEqual(
                    main(
                        [
                            "continue",
                            "--adapter",
                            "local-adapter-fixture",
                            "--",
                            fixture_python(),
                            "-c",
                            "import sys; print('--json' in sys.argv)",
                            "--json",
                        ]
                    ),
                    1,
                )
            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            attempt_stdout = run_dir / "attempts" / "attempt-001" / "adapter.stdout"
            self.assertIn("True", attempt_stdout.read_text(encoding="utf-8"))

    def test_loopforge_home_prefers_env_then_legacy_then_platform_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            env_home = home / "env-home"
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(env_home)}):
                self.assertEqual(loopforge_home(), env_home)

            legacy = home / "LoopForge"
            legacy.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch("loopforge.engine.Path.home", return_value=home),
            ):
                self.assertEqual(loopforge_home(), legacy)

            legacy.rmdir()
            data_home = home / "xdg-data"
            cache_home = home / "xdg-cache"
            with (
                mock.patch.dict(
                    os.environ,
                    {"XDG_DATA_HOME": str(data_home), "XDG_CACHE_HOME": str(cache_home)},
                    clear=True,
                ),
                mock.patch("loopforge.engine.sys.platform", "linux"),
                mock.patch("loopforge.engine.Path.home", return_value=home),
            ):
                self.assertEqual(loopforge_home(), data_home / "loopforge")
                self.assertEqual(platform_cache_home(), cache_home / "loopforge")

    def test_streaming_process_terminates_child_on_keyboard_interrupt(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.terminated = False
                self.killed = False
                self.waits = 0

            def wait(self, timeout=None):  # type: ignore[no-untyped-def]
                self.waits += 1
                if self.waits == 1:
                    raise KeyboardInterrupt
                return 130

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.killed = True

        fake = FakeProcess()
        with (
            mock.patch("loopforge.engine.subprocess.Popen", return_value=fake),
            mock.patch("loopforge.engine.isolated_process_module") as isolated,
        ):
            isolated.return_value.load_policy.return_value = {"max_timeout_seconds": 60}
            isolated.return_value.build_child_environment.return_value = {}
            with self.assertRaises(KeyboardInterrupt):
                run_streaming_process(["fake"], Path.cwd(), 60)
        self.assertTrue(fake.terminated)
        self.assertFalse(fake.killed)

    def test_streaming_process_records_cooperative_cancellation(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.terminated = False

            def wait(self, timeout=None):  # type: ignore[no-untyped-def]
                return 130

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                raise AssertionError("cooperative cancellation should terminate first")

        fake = FakeProcess()
        cancelled = threading.Event()
        cancelled.set()
        with (
            mock.patch("loopforge.engine.subprocess.Popen", return_value=fake),
            mock.patch("loopforge.engine.isolated_process_module") as isolated,
        ):
            isolated.return_value.load_policy.return_value = {"max_timeout_seconds": 60}
            isolated.return_value.build_child_environment.return_value = {}
            result = run_streaming_process(["fake"], Path.cwd(), 60, cancel_event=cancelled)
        self.assertTrue(fake.terminated)
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["returncode"], 130)

    def test_guidance_reports_not_initialized_and_cli_guide(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            guidance = current_guidance(repo)
            output = io.StringIO()

            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["guide"]), 0)
                self.assertEqual(main(["status", "--details"]), 0)

            self.assertEqual(guidance.state, "not_initialized")
            self.assertEqual(guidance.recommended_actions[0].id, "init")
            text = output.getvalue()
            self.assertIn("Guide", text)
            self.assertIn("Do this", text)
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
                self.assertEqual(current_guidance(repo).recommended_actions[0].id, "complete-task")

                self.assertEqual(
                    main(["run", "--task", "Ready run", "--success-check", "proof exists"]),
                    0,
                )
                ready = current_guidance(repo)
                self.assertEqual(ready.state, "task_awaiting_approval")
                self.assertEqual(ready.recommended_actions[0].id, "approve-task")
                self.approve_current_run_for_implementation(repo, loopforge_home)

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
                self.assertEqual(blocked.state, "implementation_blocked")
                self.assertEqual(blocked.recommended_actions[0].id, "retry-attempt")
                self.assertEqual(blocked.recommended_actions[1].id, "inspect-attempt")

                self.assertEqual(
                    main(["run", "--task", "Verify run", "--success-check", "README changed"]),
                    0,
                )
                run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
                (repo / "README.md").write_text("# Project\n\nChanged.\n", encoding="utf-8")
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                run_json["status"] = "ready_for_verification"
                run_json["stage_statuses"]["implementation"] = "complete"
                run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
                self.assertEqual(current_guidance(repo).recommended_actions[0].id, "verify")

                self.assertEqual(main(["verify"]), 1)
                failed = current_guidance(repo)
                self.assertEqual(failed.state, "verification_blocked")
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
                run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                run_json["status"] = "ready_for_verification"
                run_json["stage_statuses"]["implementation"] = "complete"
                run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text(
                    "# Project\n\nVerified.\n", encoding="utf-8"
                )
                self.assertEqual(main(["verify"]), 0)
                verified = current_guidance(repo)
                self.assertEqual(verified.state, "review_pending")
                self.assertEqual(verified.recommended_actions[0].id, "run-review")

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
                self.assertEqual(main(["shell", "--command", "/do approve-task"]), 1)
                self.assertEqual(main(["shell", "--command", "/do missing"]), 1)

            self.assertTrue((repo / ".loopforge" / "config.json").exists())
            text = output.getvalue()
            self.assertIn("Actions", text)
            self.assertIn("Next", text)
            self.assertIn("Why", text)
            self.assertIn("Guide", text)
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
            self.assertIn("current  local-adapter-fixture", text)
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
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(repo / "loopforge-home")}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["shell", "--script", str(script)]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["profile"], "strict")
            self.assertEqual(config["default_adapter"], "claude-code")
            self.assertEqual(config["default_adapter_args"], ["--dangerously-skip-permissions"])
            text = output.getvalue()
            self.assertIn("theme  dark", text)
            self.assertIn("tui  plain", text)
            self.assertIn("keymap  vim", text)
            self.assertIn("statusline  compact", text)
            self.assertIn("title  Focus", text)

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
                self.approve_current_run_for_implementation(repo, loopforge_home)
                self.assertEqual(main(["shell", "--command", "/continue"]), 0)
                self.assertEqual(main(["shell", "--command", "/stats"]), 0)
                self.assertEqual(main(["shell", "--command", "/usage"]), 0)
                self.assertEqual(main(["shell", "--command", "/cost"]), 0)
                self.assertEqual(main(["shell", "--command", "/tasks"]), 0)
                self.assertEqual(main(["shell", "--command", "/ps"]), 0)
                self.assertEqual(main(["shell", "--command", "/raw latest stdout"]), 0)

            text = output.getvalue()
            self.assertIn("tokens", text)
            self.assertIn("not reported", text)
            self.assertIn("LoopForge attempts", text)
            self.assertIn("raw hello", text)

    def test_metrics_record_writes_compact_json_without_inventing_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"

            record_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Measure one run", "--success-check", "record exists"]),
                    0,
                )
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(record_output),
            ):
                self.assertEqual(
                    main(
                        [
                            "metrics",
                            "record",
                            "--model",
                            "gpt-test",
                            "--input-tokens",
                            "12",
                            "--output-tokens",
                            "8",
                            "--cost-microunits",
                            "1234",
                            "--cost-currency",
                            "usd",
                            "--human-corrections",
                            "2",
                            "--final-disposition",
                            "accepted",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )

            payload = json.loads(record_output.getvalue())
            record_path = Path(payload["record_path"])
            record = payload["record"]

            self.assertTrue(record_path.exists())
            self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), record)
            self.assertEqual(record["model"], {"id": "gpt-test", "status": "reported"})
            self.assertEqual(record["tokens"]["input_tokens"], 12)
            self.assertEqual(record["tokens"]["output_tokens"], 8)
            self.assertEqual(record["tokens"]["total_tokens"], 20)
            self.assertEqual(record["cost"]["amount_microunits"], 1234)
            self.assertEqual(record["cost"]["currency"], "USD")
            self.assertEqual(record["patch"]["status"], "unavailable")
            self.assertIsNone(record["patch"]["size_bytes"])
            self.assertEqual(record["human_corrections"]["count"], 2)
            self.assertEqual(record["final_disposition"]["status"], "accepted")

    def test_metrics_summarize_compares_runs_without_treating_unknowns_as_zero(self) -> None:
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
                    main(["run", "--task", "Known patch run", "--success-check", "patch measured"]),
                    0,
                )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            first_run_id = config["current_run_id"]
            first_run_dir = Path(config["run_root"]) / first_run_id
            first_run_path = first_run_dir / "run.json"
            first_run = json.loads(first_run_path.read_text(encoding="utf-8"))
            first_run["status"] = "verified"
            first_run["verification"] = {
                "status": "passed",
                "finished_at": first_run["created_at"],
                "patch": {
                    "generated": True,
                    "status": "generated",
                    "path": "artifacts/patches/complete.patch",
                    "size_bytes": 20,
                    "sha256": "a" * 64,
                },
                "checks_passed": 1,
                "checks_total": 1,
            }
            first_run_path.write_text(json.dumps(first_run, indent=2), encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    main(
                        [
                            "metrics",
                            "record",
                            "--run-id",
                            first_run_id,
                            "--input-tokens",
                            "10",
                            "--output-tokens",
                            "5",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Unknown patch run",
                            "--success-check",
                            "record exists",
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["metrics", "record"]), 0)

            summary_output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(summary_output),
            ):
                self.assertEqual(main(["metrics", "summarize", "--format", "json"]), 0)

            payload = json.loads(summary_output.getvalue())
            summary = payload["summary"]

            self.assertEqual(summary["record_count"], 2)
            self.assertEqual(summary["patch_size_bytes"]["known_count"], 1)
            self.assertEqual(summary["patch_size_bytes"]["unknown_count"], 1)
            self.assertEqual(summary["patch_size_bytes"]["sum"], 20)
            self.assertEqual(summary["patch_size_bytes"]["average"], 20)
            self.assertEqual(summary["tokens"]["total_tokens"]["known_count"], 1)
            self.assertEqual(summary["tokens"]["total_tokens"]["unknown_count"], 1)
            self.assertEqual(summary["tokens"]["total_tokens"]["sum"], 15)
            self.assertEqual(summary["verification_results"]["passed"], 1)
            self.assertEqual(summary["verification_results"]["unknown"], 1)
            self.assertEqual(summary["final_dispositions"]["pending"], 1)
            self.assertEqual(summary["final_dispositions"]["verified"], 1)

    def test_dashboard_json_handles_project_states(self) -> None:
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
                self.assertEqual(main(["dashboard", "--format", "json"]), 0)
            payload = json.loads(output.getvalue())
            dashboard = payload["dashboard"]
            self.assertFalse(dashboard["project"]["initialized"])
            self.assertEqual(dashboard["next_human_action"]["id"], "init")

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["dashboard", "--format", "json"]), 0)
            payload = json.loads(output.getvalue())
            dashboard = payload["dashboard"]
            self.assertTrue(dashboard["project"]["initialized"])
            self.assertFalse(dashboard["current_loop"]["available"])
            self.assertEqual(dashboard["next_human_action"]["id"], "create-run")

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    main(["run", "--task", "Dashboard run", "--success-check", "state exists"]),
                    0,
                )
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["dashboard", "--format", "json"]), 0)
            payload = json.loads(output.getvalue())
            dashboard = payload["dashboard"]
            run_id = dashboard["project"]["current_run_id"]
            self.assertTrue(dashboard["current_loop"]["available"])
            self.assertEqual(dashboard["current_loop"]["run_id"], run_id)
            self.assertEqual(dashboard["current_loop"]["task"], "Dashboard run")

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_json_path = Path(config["run_root"]) / run_id / "run.json"
            run_json_path.unlink()
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["dashboard", "--format", "json"]), 0)
            payload = json.loads(output.getvalue())
            dashboard = payload["dashboard"]
            self.assertFalse(dashboard["current_loop"]["available"])
            self.assertTrue(
                any(
                    "current run metadata not found" in blocker
                    for blocker in dashboard["blockers"]
                )
            )

    def test_dashboard_text_shell_and_read_only_contract(self) -> None:
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
                    main(
                        [
                            "run",
                            "--task",
                            "Dashboard evidence",
                            "--success-check",
                            "dashboard prints evidence",
                        ]
                    ),
                    0,
                )

            config_path = repo / ".loopforge" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json_path = run_dir / "run.json"
            proposal_path = run_dir / "artifacts" / "memory" / "proposals.json"
            proposal_path.parent.mkdir(parents=True, exist_ok=True)
            proposal_path.write_text(
                json.dumps(
                    {
                        "proposals": [
                            {
                                "id": "p1",
                                "status": "pending",
                                "category": "Stable Project Facts",
                                "source": "test",
                                "text": "Tests use unittest discovery.",
                            },
                            {
                                "id": "p2",
                                "status": "rejected",
                                "category": "Known Pitfalls",
                                "source": "test",
                                "text": "Do not remember secrets.",
                                "rejection_reason": "secret-like content",
                            },
                            {
                                "id": "p3",
                                "status": "promoted",
                                "category": "Verification Patterns",
                                "source": "test",
                                "text": "Run unittest discovery.",
                                "promotion_reason": "human approval",
                            },
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            record_path = run_dir / "metrics" / "record.json"
            record_path.write_text(
                json.dumps(
                    {
                        "run_id": config["current_run_id"],
                        "timing": {"duration_seconds": 30},
                        "adapter": {"id": "codex"},
                        "attempts": {"count": 2},
                        "tokens": {"total_tokens": 15},
                        "cost": {"amount_microunits": 100, "currency": "USD"},
                        "patch": {"size_bytes": 20},
                        "verification": {"status": "passed"},
                        "final_disposition": {"status": "verified"},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            verification_path = run_dir / "verification.md"
            watched_paths = [
                config_path,
                run_json_path,
                proposal_path,
                record_path,
                verification_path,
            ]
            before = {path: path.read_text(encoding="utf-8") for path in watched_paths}

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["dashboard"]), 0)
                self.assertEqual(main(["shell", "--command", "/dashboard"]), 0)

            text = output.getvalue()
            for label in (
                "Recent runs",
                "Current run",
                "Verification",
                "Memory",
                "Next human action",
            ):
                self.assertIn(label, text)
            self.assertIn("1 pending, 1 promoted, 1 rejected", text)
            self.assertIn("action   approve-task", text)

            after = {path: path.read_text(encoding="utf-8") for path in watched_paths}
            self.assertEqual(after, before)

    def test_dashboard_adapter_comparison_preserves_unknowns(self) -> None:
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

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_root = Path(config["run_root"])
            known_record = run_root / "known" / "metrics" / "record.json"
            unknown_record = run_root / "unknown" / "metrics" / "record.json"
            known_record.parent.mkdir(parents=True)
            unknown_record.parent.mkdir(parents=True)
            known_record.write_text(
                json.dumps(
                    {
                        "run_id": "known",
                        "timing": {"duration_seconds": 40},
                        "adapter": {"id": "codex"},
                        "attempts": {"count": 2},
                        "tokens": {"total_tokens": 12},
                        "cost": {"amount_microunits": 500, "currency": "USD"},
                        "patch": {"size_bytes": 80},
                        "verification": {"status": "passed"},
                        "final_disposition": {"status": "verified"},
                    }
                ),
                encoding="utf-8",
            )
            unknown_record.write_text(
                json.dumps(
                    {
                        "run_id": "unknown",
                        "timing": {"duration_seconds": None},
                        "adapter": {"id": None},
                        "attempts": {"count": None},
                        "tokens": {"total_tokens": None},
                        "cost": {"amount_microunits": None, "currency": None},
                        "patch": {"size_bytes": None},
                        "verification": {"status": None},
                        "final_disposition": {"status": "pending"},
                    }
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["dashboard", "--format", "json"]), 0)

            payload = json.loads(output.getvalue())
            groups = {
                group["adapter"]: group
                for group in payload["dashboard"]["adapter_comparison"]["groups"]
            }
            self.assertEqual(groups["codex"]["duration_seconds"]["average"], 40)
            self.assertEqual(groups["codex"]["total_tokens"]["sum"], 12)
            self.assertEqual(groups["codex"]["patch_size_bytes"]["sum"], 80)
            self.assertEqual(groups["codex"]["cost"]["known_count"], 1)
            self.assertEqual(groups["unknown"]["duration_seconds"]["known_count"], 0)
            self.assertEqual(groups["unknown"]["duration_seconds"]["unknown_count"], 1)
            self.assertIsNone(groups["unknown"]["duration_seconds"]["average"])
            self.assertEqual(groups["unknown"]["patch_size_bytes"]["unknown_count"], 1)
            self.assertEqual(groups["unknown"]["cost"]["unknown_count"], 1)

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
            self.assertIn("Memory", text)
            self.assertIn("LoopForge skills", text)
            self.assertIn("Allowed tools", text)
            self.assertIn("git | allowed", text)
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            run_json_path = Path(config["run_root"]) / config["current_run_id"] / "run.json"
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
            self.assertIn(f"project  {repo}", text)
            self.assertIn(f"added context dir: {extra}", text)
            self.assertIn(f"mentioned: {mentioned}", text)
            self.assertIn("session context dirs:", text)
            self.assertIn("session mentions:", text)

    def test_shell_doctor_reports_missing_tui_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with (
                mock.patch(
                    "loopforge.cli.interactive.importlib.util.find_spec",
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
                self.approve_current_run_for_implementation(repo, loopforge_home)
                self.assertEqual(main(["continue"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            self.assertIn("Contract validation", output.getvalue())
            self.assertIn("adapter   not executed", output.getvalue())

    def test_continue_blocks_when_plan_is_awaiting_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            fixture_code = (
                "from pathlib import Path; "
                "Path('should-not-exist.txt').write_text('changed\\n', encoding='utf-8')"
            )

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
                            "Block implementation",
                            "--success-check",
                            "should-not-exist.txt exists",
                        ]
                    ),
                    0,
                )
                run_dir = self.approve_current_run(repo, loopforge_home)
                run_json_path = run_dir / "run.json"
                run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
                run_json["stage_statuses"]["research"] = "complete"
                run_json["stage_statuses"]["plan"] = "awaiting_approval"
                run_json["current_stage"] = "plan_ready"
                run_json["human_gates"]["plan_approval"] = {
                    "required": True,
                    "status": "pending",
                }
                run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
                (run_dir / "plan.md").write_text(valid_plan_markdown(), encoding="utf-8")
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
                                fixture_code,
                            ]
                        ),
                        1,
                    )

            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["attempt_count"], 0)
            self.assertFalse((repo / "should-not-exist.txt").exists())
            self.assertIn("approved plan", error.getvalue())

    def test_continue_runs_when_plan_is_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            loopforge_home = workspace / "loopforge-home"
            fixture_code = (
                "from pathlib import Path; "
                "Path('approved-plan.txt').write_text('changed\\n', encoding='utf-8')"
            )

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
                            "Run approved implementation",
                            "--success-check",
                            "approved-plan.txt exists",
                        ]
                    ),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_json["attempt_count"], 1)
            self.assertEqual(run_json["stage_statuses"]["plan"], "approved")
            self.assertTrue((repo / "approved-plan.txt").exists())

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
            self.assertIn("Contract blocked", text)
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
                self.approve_current_run_for_implementation(repo, loopforge_home)
                self.assertEqual(main(["continue"]), 0)

            self.assertIn("Contract validation", output.getvalue())

    def test_assist_profile_blocks_adapter_execution(self) -> None:
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
                self.assertEqual(main(["init", "--profile", "assist"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Update README",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
                                "from pathlib import Path; Path('README.md').write_text('changed')",
                            ]
                        ),
                        1,
                    )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

            self.assertEqual(run_json["profile"], "assist")
            self.assertEqual(run_json["attempt_count"], 0)
            self.assertFalse((repo / "README.md").exists())
            self.assertIn("assist profile blocks adapter attempt", error.getvalue())

    def test_autonomous_profile_stops_on_publication_request(self) -> None:
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
                            "Publish the release notes",
                            "--success-check",
                            "release notes contain the version",
                        ]
                    ),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home)
                with contextlib.redirect_stderr(error):
                    self.assertEqual(
                        main(["continue", "--adapter", "local-adapter-fixture", "--", fixture_python(), "-c", "print('unused')"]),
                        1,
                    )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

            self.assertEqual(run_json["attempt_count"], 0)
            self.assertIn("autonomous profile stops before publication", error.getvalue())

    def test_strict_profile_requires_confirm_for_verify_and_memory_promotion(self) -> None:
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

            verify_error = io.StringIO()
            learn_error = io.StringIO()
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["init", "--profile", "strict"]), 0)
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--task",
                            "Update README",
                            "--success-check",
                            "README contains the update",
                        ]
                    ),
                    0,
                )
                (repo / "README.md").write_text("# Project\n\nUpdated.\n", encoding="utf-8")
                with contextlib.redirect_stderr(verify_error):
                    self.assertEqual(main(["verify"]), 1)
                self.assertEqual(main(["verify", "--confirm"]), 0)
                with contextlib.redirect_stderr(learn_error):
                    self.assertEqual(
                        main(
                            [
                                "learn",
                                "--approve",
                                "--note",
                                "Fact: Tests use unittest discovery.",
                            ]
                        ),
                        1,
                    )
                self.assertEqual(
                    main(
                        [
                            "learn",
                            "--approve",
                            "--confirm",
                            "--note",
                            "Fact: Tests use unittest discovery.",
                        ]
                    ),
                    0,
                )

            durable = (repo / ".loopforge" / "memory.md").read_text(encoding="utf-8")
            self.assertIn("- Tests use unittest discovery.", durable)
            self.assertIn("strict profile requires --confirm before verification", verify_error.getvalue())
            self.assertIn(
                "strict profile requires --confirm before memory promotion",
                learn_error.getvalue(),
            )
            self.assertIn("Verified", output.getvalue())

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
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            self.assertIn("Attempt completed", output.getvalue())

    def test_continue_fixture_adapter_uses_git_worktree_workspace(self) -> None:
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
            fixture_code = (
                "from pathlib import Path\n"
                "Path('adapter-output.txt').write_text('changed\\n', encoding='utf-8')\n"
            )

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
                            "Create output in worktree",
                            "--success-check",
                            "adapter-output.txt exists",
                        ]
                    ),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            workspace_dir = Path(run_json["workspace"]["path"])

            self.assertEqual(run_json["status"], "ready_for_verification")
            self.assertTrue((workspace_dir / "adapter-output.txt").exists())
            self.assertFalse((repo / "adapter-output.txt").exists())
            self.assertEqual(run_json["last_attempt"]["workspace"], str(workspace_dir))
            prompt_path = run_dir / run_json["last_attempt"]["prompt_path"]
            prompt_text = prompt_path.read_text(encoding="utf-8")
            self.assertIn(str(run_dir), prompt_text)
            self.assertIn(str(workspace_dir), prompt_text)
            self.assertIn("Create output in worktree", prompt_text)

    def test_codex_attempt_command_uses_exec_and_stdin_prompt(self) -> None:
        self.assertEqual(
            command_for_attempt(adapter="codex", adapter_args=[]),
            ["codex", "exec", "--json", "--color", "never", "-s", "workspace-write", "-"],
        )
        self.assertEqual(
            command_for_attempt(adapter="codex", adapter_args=["-m", "gpt-5"]),
            [
                "codex",
                "exec",
                "--json",
                "--color",
                "never",
                "-s",
                "workspace-write",
                "-m",
                "gpt-5",
                "-",
            ],
        )
        self.assertEqual(
            command_for_attempt(adapter="codex", adapter_args=["exec", "-s", "workspace-write"]),
            ["codex", "exec", "--json", "--color", "never", "-s", "workspace-write", "-"],
        )
        command = command_for_attempt(
            adapter="codex",
            adapter_args=[],
            workspace_dir=Path("workspace"),
            run_dir=Path("run"),
        )
        self.assertIn("--cd", command)
        self.assertIn("workspace", command)
        self.assertIn("--add-dir", command)
        self.assertIn("run", command)

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
                self.approve_current_run_for_implementation(repo, loopforge_home)
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt_dir = run_dir / "attempts" / "attempt-001"

            self.assertEqual(run_json["status"], "adapter_blocked")
            self.assertEqual(run_json["attempt_count"], 1)
            self.assertIn("reported failed", run_json["blockers"][0])
            self.assertIn("bad fixture", (attempt_dir / "adapter.stderr").read_text())
            self.assertIn("Attempt blocked", error.getvalue())
            self.assertIn("Fixture command failed with return code 3.", error.getvalue())
            self.assertIn("Adapter diagnostic", error.getvalue())
            self.assertNotIn("adapter stderr tail:", error.getvalue())

    def test_continue_can_retry_after_blocked_attempt_without_archiving(self) -> None:
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
                    main(["run", "--task", "Retry blocked work", "--success-check", "file exists"]),
                    0,
                )
                self.approve_current_run_for_implementation(repo, loopforge_home)
                self.assertEqual(
                    main(
                        [
                            "continue",
                            "--adapter",
                            "local-adapter-fixture",
                            "--",
                            fixture_python(),
                            "-c",
                            "print('no changes')",
                        ]
                    ),
                    1,
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
                            (
                                "from pathlib import Path; "
                                "Path('retried.txt').write_text('ok\\n', encoding='utf-8')"
                            ),
                        ]
                    ),
                    0,
                )

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

            self.assertEqual(run_json["status"], "ready_for_verification")
            self.assertEqual(run_json["attempt_count"], 2)
            self.assertEqual(run_json["attempts"][0]["status"], "blocked")
            self.assertEqual(run_json["attempts"][1]["status"], "completed")
            self.assertTrue((repo / "retried.txt").exists())

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
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text(
                    "# Project\n\nUpdated.\n",
                    encoding="utf-8",
                )
                self.assertEqual(main(["verify"]), 0)
                self.assertEqual(main(["status", "--details"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["status"], "verified")
            self.assertEqual(run_json["current_stage"], "verification_ready")
            self.assertEqual(run_json["stage_statuses"]["verification"], "complete")
            self.assertEqual(run_json["stage_statuses"]["review"], "pending")
            self.assertEqual(run_json["human_gates"]["review_approval"]["status"], "pending")
            self.assertFalse(run_json["publish_eligibility"]["eligible"])
            self.assertEqual(verification["status"], "passed")
            self.assertEqual(verification["diff_policy"]["allowed"], True)
            self.assertEqual(verification["risk"]["risk"], "low")
            self.assertEqual(verification["checks_passed"], 1)
            self.assertTrue((run_dir / "artifacts" / "patches" / "complete.patch").exists())
            self.assertIn("README.md", (run_dir / "artifacts" / "patches" / "complete.patch").read_text())
            self.assertIn("Verified", output.getvalue())
            self.assertIn("status  passed", output.getvalue())
            self.assertIn("risk    low", output.getvalue())

    def test_run_cockpit_approves_verified_work_for_review(self) -> None:
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
                    main(["run", "--task", "Review verified work", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "verification_ready"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "pending"
            run_json["human_gates"]["review_approval"] = {
                "required": True,
                "status": "pending",
            }
            run_json["publish_eligibility"] = {
                "eligible": False,
                "reasons": ["review approval is required before draft publication"],
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
            (run_dir / "verification.md").write_text("# Verification\n\nPassed.\n", encoding="utf-8")
            self.complete_current_review(run_dir)

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            review_gate = run_json["human_gates"]["review_approval"]
            self.assertEqual(run_json["current_stage"], "review_ready")
            self.assertEqual(run_json["stage_statuses"]["review"], "approved")
            self.assertEqual(review_gate["status"], "approved")
            self.assertEqual(review_gate["source"], "local")
            self.assertTrue(review_gate["approved_at"])
            self.assertTrue(run_json["publish_eligibility"]["eligible"])
            self.assertEqual(run_json["publish_eligibility"]["mode"], "draft")
            self.assertIn("Review approved", output.getvalue())

    def test_run_no_input_does_not_approve_review(self) -> None:
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
                    main(["run", "--task", "Leave review pending", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "verification_ready"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "pending"
            run_json["human_gates"]["review_approval"] = {
                "required": True,
                "status": "pending",
            }
            run_json["publish_eligibility"] = {
                "eligible": False,
                "reasons": ["review approval is required before draft publication"],
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")
            (run_dir / "verification.md").write_text("# Verification\n\nPassed.\n", encoding="utf-8")

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual(run_json["current_stage"], "verification_ready")
            self.assertEqual(run_json["stage_statuses"]["review"], "pending")
            self.assertEqual(run_json["human_gates"]["review_approval"]["status"], "pending")
            self.assertFalse(run_json["publish_eligibility"]["eligible"])
            self.assertIn("Active run found", output.getvalue())

    def test_run_cockpit_prepares_draft_publication_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Prepare draft PR", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            patch_path = run_dir / "artifacts" / "patches" / "complete.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_bytes = b"diff --git a/README.md b/README.md\n"
            patch_path.write_bytes(patch_bytes)
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "review_ready"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "approved"
            run_json["human_gates"]["review_approval"] = {
                "required": True,
                "status": "approved",
                "source": "test",
                "approved_at": "2026-07-11T00:00:00Z",
            }
            run_json["verification"] = {
                "status": "passed",
                "checks_passed": 1,
                "checks_total": 1,
                "patch": {
                    "generated": True,
                    "path": "artifacts/patches/complete.patch",
                    "sha256": hashlib.sha256(patch_bytes).hexdigest(),
                    "size_bytes": len(patch_bytes),
                    "status": "generated",
                },
            }
            run_json["publish_eligibility"] = {
                "eligible": True,
                "mode": "draft",
                "reasons": ["verified work has explicit review approval"],
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

            answers = iter(["1", "y"])
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                mock.patch("sys.stdin", TtyStringIO()),
                mock.patch("builtins.input", side_effect=lambda _: next(answers)),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run"]), 0)

            draft_path = run_dir / "artifacts" / "publication" / "draft-pr.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertEqual(run_json["current_stage"], "draft_publication_ready")
            self.assertEqual(run_json["stage_statuses"]["publication"], "draft_prepared")
            self.assertEqual(run_json["publication"]["network"], {"performed": False})
            self.assertTrue(draft["draft"])
            self.assertEqual(draft["network"]["performed"], False)
            self.assertEqual(draft["kind"], "draft_pr_publication")
            self.assertEqual(draft["publisher"], "local-draft-artifact")
            self.assertTrue(draft["no_network"])
            self.assertIn("Prepare draft PR", draft["title"])
            self.assertEqual(draft["base_commit"], run_json["base_commit"])
            self.assertEqual(draft["patch"]["path"], "artifacts/patches/complete.patch")
            self.assertEqual(draft["patch"]["sha256"], hashlib.sha256(patch_bytes).hexdigest())
            self.assertIn("Draft publication prepared", output.getvalue())

    def test_run_no_input_does_not_prepare_draft_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"

            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Do not publish", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            patch_path = run_dir / "artifacts" / "patches" / "complete.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "review_ready"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "approved"
            run_json["human_gates"]["review_approval"] = {
                "required": True,
                "status": "approved",
            }
            run_json["verification"] = {
                "status": "passed",
                "checks_passed": 1,
                "checks_total": 1,
                "patch": {
                    "generated": True,
                    "path": "artifacts/patches/complete.patch",
                    "sha256": "abc123",
                    "size_bytes": patch_path.stat().st_size,
                    "status": "generated",
                },
            }
            run_json["publish_eligibility"] = {
                "eligible": True,
                "mode": "draft",
                "reasons": ["verified work has explicit review approval"],
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["run", "--no-input"]), 0)

            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            self.assertNotEqual(run_json["stage_statuses"]["publication"], "draft_prepared")
            self.assertFalse((run_dir / "artifacts" / "publication" / "draft-pr.json").exists())
            self.assertIn("Active run found", output.getvalue())

    def test_prepare_draft_publication_blocks_without_review_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            repo = workspace / "project"
            repo.mkdir()
            self.initialize_git_project(repo)
            loopforge_home = workspace / "loopforge-home"
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}),
                working_directory(repo),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(
                    main(["run", "--task", "Blocked publication", "--success-check", "Tests pass"]),
                    0,
                )
            run_dir = self.approve_current_run_for_implementation(repo, loopforge_home)
            patch_path = run_dir / "artifacts" / "patches" / "complete.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
            run_json_path = run_dir / "run.json"
            run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
            run_json["status"] = "verified"
            run_json["current_stage"] = "verification_ready"
            run_json["stage_statuses"]["verification"] = "complete"
            run_json["stage_statuses"]["review"] = "pending"
            run_json["verification"] = {
                "status": "passed",
                "patch": {
                    "generated": True,
                    "path": "artifacts/patches/complete.patch",
                    "sha256": "abc123",
                    "size_bytes": patch_path.stat().st_size,
                    "status": "generated",
                },
            }
            run_json["publish_eligibility"] = {
                "eligible": False,
                "mode": "draft",
                "reasons": ["review approval is required before draft publication"],
            }
            run_json_path.write_text(json.dumps(run_json), encoding="utf-8")

            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(loopforge_home)}):
                result = prepare_draft_publication(repo)

            self.assertFalse(result.ok)
            self.assertIn("review approval", "\n".join(result.blockers))
            self.assertIn("draft publish eligibility", "\n".join(result.blockers))
            self.assertFalse((run_dir / "artifacts" / "publication" / "draft-pr.json").exists())

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
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "pyproject.toml").write_text(
                    "[project]\nname = \"sample\"\nversion = \"0.2.0\"\n",
                    encoding="utf-8",
                )
                self.assertEqual(main(["verify"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["pack"], "python")
            self.assertEqual(verification["risk"]["risk"], "high")
            self.assertIn("protected-paths.json", "\n".join(verification["risk"]["policy_sources"]))
            self.assertTrue((run_dir / "artifacts" / "policies" / "risk-rules.merged.json").exists())
            self.assertIn("risk    high", output.getvalue())

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
                config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
                run_dir = Path(config["run_root"]) / config["current_run_id"]
                run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                workspace_dir = Path(run_json["workspace"]["path"])
                (workspace_dir / "README.md").write_text(
                    "# Project\n\nUpdated.\n",
                    encoding="utf-8",
                )

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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            verification = run_json["verification"]

            self.assertEqual(run_json["status"], "verification_failed")
            self.assertEqual(run_json["current_stage"], "verification_blocked")
            self.assertEqual(run_json["stage_statuses"]["verification"], "blocked")
            self.assertEqual(run_json["stage_statuses"]["review"], "pending")
            self.assertFalse(run_json["publish_eligibility"]["eligible"])
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
            adapter = (
                Path(__file__).resolve().parents[1]
                / ".agent"
                / "adapters"
                / "local_implementation_adapter.py"
            )

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

    def test_imported_adapter_streams_child_output_to_result_file_mode(self) -> None:
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
            result_path = workspace / "result.json"
            adapter = (
                Path(__file__).resolve().parents[1]
                / ".agent"
                / "adapters"
                / "local_implementation_adapter.py"
            )

            result = subprocess.run(
                [
                    fixture_python(),
                    str(adapter),
                    "--expected-session",
                    str(session_path),
                    "--workspace",
                    str(repo),
                    "--result-output",
                    str(result_path),
                    "--",
                    fixture_python(),
                    "-c",
                    (
                        "from pathlib import Path; import sys; "
                        "print('stream stdout'); "
                        "print('stream stderr', file=sys.stderr); "
                        "Path('changed.txt').write_text('ok\\n', encoding='utf-8')"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("stream stdout", result.stdout)
            self.assertIn("stream stderr", result.stderr)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertTrue(payload["workspace_changed"])

    def test_imported_adapter_formats_codex_json_stream(self) -> None:
        adapter = (
            Path(__file__).resolve().parents[1]
            / ".agent"
            / "adapters"
            / "local_implementation_adapter.py"
        )
        spec = importlib.util.spec_from_file_location("local_implementation_adapter_test", adapter)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        output = io.StringIO()
        presenter = module.StreamPresenter(output, parse_codex_json=True)
        presenter.write(
            (
                json.dumps({"type": "item.started", "item": {"type": "reasoning"}})
                + "\n"
                + json.dumps({"type": "function_call", "name": "exec_command"})
                + "\n"
                + json.dumps(
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Done cleanly."}],
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        presenter.close()

        text = output.getvalue()
        self.assertIn("Reflexion en cours", text)
        self.assertIn("Outil: exec_command", text)
        self.assertIn("Message", text)
        self.assertIn("Done cleanly.", text)

    def test_imported_adapter_streams_before_child_exits(self) -> None:
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
            result_path = workspace / "result.json"
            adapter = (
                Path(__file__).resolve().parents[1]
                / ".agent"
                / "adapters"
                / "local_implementation_adapter.py"
            )
            child_code = (
                "from pathlib import Path\n"
                "import time\n"
                "print('first streamed line', flush=True)\n"
                "time.sleep(2)\n"
                "Path('changed.txt').write_text('ok\\n', encoding='utf-8')\n"
                "print('second streamed line', flush=True)\n"
            )

            started = time.monotonic()
            process = subprocess.Popen(
                [
                    fixture_python(),
                    str(adapter),
                    "--expected-session",
                    str(session_path),
                    "--workspace",
                    str(repo),
                    "--result-output",
                    str(result_path),
                    "--",
                    fixture_python(),
                    "-u",
                    "-c",
                    child_code,
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            first_line = process.stdout.readline().strip()
            elapsed = time.monotonic() - started
            stdout, stderr = process.communicate(timeout=10)

            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertEqual(first_line, "first streamed line")
            self.assertLess(elapsed, 1.5)
            self.assertIn("second streamed line", stdout)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")

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
                self.assertEqual(main(["status", "--details"]), 0)

            config = json.loads((repo / ".loopforge" / "config.json").read_text(encoding="utf-8"))
            run_dir = Path(config["run_root"]) / config["current_run_id"]
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
            run_dir = Path(config["run_root"]) / config["current_run_id"]
            run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            (Path(run_json["legacy"]["artifact_dir"]) / "review.md").unlink()

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status", "--details"]), 0)

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
            (Path(config["run_root"]) / config["current_run_id"] / "run.json").unlink()

            output = io.StringIO()
            with working_directory(repo), contextlib.redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)

            text = output.getvalue()
            self.assertIn(f"run      {config['current_run_id']}", text)
            self.assertIn("current run metadata not found", text)
            self.assertIn("Next", text)

    def test_unknown_command_still_exits_with_parser_error(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(main(["unknown"]), 2)
        self.assertIn("LF_USAGE", output.getvalue())
        self.assertIn("invalid choice", output.getvalue())


if __name__ == "__main__":
    unittest.main()
