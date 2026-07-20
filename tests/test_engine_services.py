from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import loopforge
from loopforge.adapters import local_implementation_adapter
from loopforge.adapters import kilo_code
from loopforge.contracts import policy_path
from loopforge.checks import diff_policy, isolated_process
from loopforge.engine import (
    create_run,
    codex_workspace_preflight_blockers,
    current_status,
    initialize_project,
    list_runs,
    list_registered_projects,
    list_runs_all_projects,
    open_project,
    prepare_run_workspace,
    read_json,
    rebuild_indexes,
    write_json_atomic,
)
from loopforge.engine.metrics import MetricsService
from loopforge.engine.packs import PackRegistry
from loopforge.engine.storage import JsonStore
from loopforge.engine.git_state import GitStateService


class JsonStoreTests(unittest.TestCase):
    def test_write_object_is_readable_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = JsonStore()

            store.write_object(path, {"name": "LoopForge", "version": 1})

            self.assertEqual(store.read_object(path), {"name": "LoopForge", "version": 1})
            self.assertEqual(list(path.parent.glob(".state.json.*.tmp")), [])

    def test_read_object_rejects_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                JsonStore().read_object(path)


class GitStateServiceTests(unittest.TestCase):
    def _repository(self, root: Path, *, branch: str = "main", head: str = "a" * 40) -> Path:
        project = root / "project"
        git_dir = project / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / branch).write_text(f"{head}\n", encoding="utf-8")
        return project

    def test_normal_branch_read_uses_head_files_without_a_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._repository(Path(temp_dir))
            service = GitStateService()

            with mock.patch("loopforge.engine.git_state.subprocess.run") as run:
                state = service.get(project)

            self.assertEqual(state.state, "ready")
            self.assertEqual(state.branch, "main")
            self.assertEqual(state.head, "a" * 40)
            run.assert_not_called()

    def test_worktree_gitdir_file_resolves_branch_and_head(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "worktree"
            git_dir = root / "metadata" / "worktree"
            (git_dir / "refs" / "heads").mkdir(parents=True)
            project.mkdir()
            (project / ".git").write_text("gitdir: ../metadata/worktree\n", encoding="utf-8")
            (git_dir / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
            (git_dir / "refs" / "heads" / "feature").write_text("b" * 40, encoding="utf-8")

            state = GitStateService().get(project)

            self.assertEqual(state.state, "ready")
            self.assertEqual(state.branch, "feature")
            self.assertEqual(state.head, "b" * 40)

    def test_detached_head_and_non_git_directory_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._repository(root)
            (project / ".git" / "HEAD").write_text("c" * 40, encoding="utf-8")
            service = GitStateService()

            detached = service.get(project)
            missing = service.get(root / "not-a-repository")

            self.assertEqual(detached.state, "detached")
            self.assertIsNone(detached.branch)
            self.assertEqual(detached.head, "c" * 40)
            self.assertEqual(missing.state, "not_repository")

    def test_branch_change_invalidates_cached_head_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._repository(Path(temp_dir), branch="main")
            git_dir = project / ".git"
            (git_dir / "refs" / "heads" / "release").write_text("d" * 40, encoding="utf-8")
            service = GitStateService()
            first = service.get(project)
            (git_dir / "HEAD").write_text("ref: refs/heads/release\n", encoding="utf-8")

            changed = service.get(project)

            self.assertEqual(first.branch, "main")
            self.assertEqual(changed.branch, "release")
            self.assertNotEqual(first.signature, changed.signature)

    def test_timeout_returns_stale_cached_state_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._repository(Path(temp_dir))
            service = GitStateService(fallback_timeout=0.001)
            cached = service.get(project)
            (project / ".git" / "HEAD").unlink()

            with mock.patch(
                "loopforge.engine.git_state.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["git"], 0.001),
            ):
                stale = service.refresh(project)

            self.assertEqual(cached.state, "ready")
            self.assertEqual(stale.state, "stale")
            self.assertEqual(stale.branch, "main")

    def test_unreadable_head_uses_the_bounded_fallback_in_a_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            (project / ".git").mkdir(parents=True)
            service = GitStateService()

            with mock.patch(
                "loopforge.engine.git_state.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess([], 0, stdout="main\n"),
                    subprocess.CompletedProcess([], 0, stdout="e" * 40 + "\n"),
                ],
            ) as run:
                state = service.refresh_background(project).result(timeout=1)

            self.assertEqual(state.state, "ready")
            self.assertEqual(state.branch, "main")
            self.assertEqual(state.head, "e" * 40)
            self.assertEqual(run.call_count, 2)

    def test_deleted_project_is_not_a_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._repository(Path(temp_dir))
            project.rename(project.with_name("removed"))

            state = GitStateService().get(project)

            self.assertEqual(state.state, "not_repository")


class RunWorkspaceTests(unittest.TestCase):
    def test_worktree_creation_uses_portable_long_path_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            with (
                mock.patch("loopforge.engine.git_toplevel", return_value=project),
                mock.patch("loopforge.engine.default_workspace_root", return_value=root / "workspaces"),
                mock.patch("loopforge.engine.subprocess.run") as run,
            ):
                run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
                prepare_run_workspace(
                    project_dir=project,
                    run_id="run-001",
                    base_commit="a" * 40,
                    now="2026-07-17T00:00:00Z",
                )

            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["git", "-c", "core.longpaths=true", "-c"])
            self.assertEqual(command[5:8], ["worktree", "add", "--detach"])
            self.assertNotIn("--relative-paths", command)

    def test_public_create_run_creates_a_git_worktree_with_supported_git_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True, text=True)
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
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )

            initialize_project(project, home=root / "home")
            result = create_run(project, "Create a portable workspace", success_checks=["workspace exists"])

            self.assertEqual(result.run["workspace"]["mode"], "git-worktree")
            self.assertTrue(Path(result.run["workspace"]["path"]).is_dir())

    def test_failed_worktree_creation_removes_partial_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            workspace = Path(temp_dir) / "home" / "projects" / "project-id" / "workspaces" / "run-001"

            def failed_add(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if command[1:5] == ["-c", "core.longpaths=true", "-c", f"safe.directory={project.as_posix()}"]:
                    workspace.mkdir(parents=True)
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="fatal: path too long")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with (
                mock.patch("loopforge.engine.git_toplevel", return_value=project),
                mock.patch("loopforge.engine.default_workspace_root", return_value=workspace.parent),
                mock.patch("loopforge.engine.subprocess.run", side_effect=failed_add),
            ):
                with self.assertRaisesRegex(ValueError, "could not create run worktree"):
                    prepare_run_workspace(
                        project_dir=project,
                        run_id="run-001",
                        base_commit="a" * 40,
                        now="2026-07-17T00:00:00Z",
                        project_id="project-id",
                    )

            self.assertFalse(workspace.exists())

    def test_create_run_removes_artifacts_when_workspace_preparation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            initialized = initialize_project(project, home=root / "home")

            with mock.patch(
                "loopforge.engine.prepare_run_workspace",
                side_effect=ValueError("could not create run worktree: fatal"),
            ):
                with self.assertRaisesRegex(ValueError, "could not create run worktree"):
                    create_run(project, "Create a resilient worktree", success_checks=["tests pass"])

            run_root = Path(initialized.config["run_root"])
            self.assertEqual([path for path in run_root.iterdir() if path.is_dir()], [])


class ProjectRegistryTests(unittest.TestCase):
    def test_same_named_projects_get_distinct_id_scoped_storage_and_global_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home_root = home / "LoopForge"
            first = root / "one" / "LoopForge"
            second = root / "two" / "LoopForge"
            first.mkdir(parents=True)
            second.mkdir(parents=True)

            first_result = initialize_project(first, home=home)
            second_result = initialize_project(second, home=home)

            self.assertNotEqual(first_result.config["project_id"], second_result.config["project_id"])
            self.assertNotEqual(first_result.config["run_root"], second_result.config["run_root"])
            self.assertEqual(
                first_result.config["run_root"],
                str(home_root / "projects" / first_result.config["project_id"] / "runs"),
            )
            projects = list_registered_projects(home)
            self.assertEqual([project["name"] for project in projects.projects], ["LoopForge", "LoopForge"])
            self.assertEqual({project["path"] for project in projects.projects}, {str(first), str(second)})

    def test_legacy_run_root_is_copied_before_config_moves_to_id_scoped_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            home_root = home / "LoopForge"
            project = root / "project"
            project.mkdir()
            initial = initialize_project(project, home=home)
            legacy_root = home_root / "runs" / project.name
            legacy_run = legacy_root / "legacy-run"
            legacy_run.mkdir(parents=True)
            write_json_atomic(legacy_run / "run.json", {"run_id": "legacy-run", "task": "Keep me"})
            config = read_json(initial.config_path)
            config["run_root"] = str(legacy_root)
            config["current_run_id"] = "legacy-run"
            write_json_atomic(initial.config_path, config)

            migrated = initialize_project(project, home=home)

            self.assertEqual(migrated.migrated_run_root, legacy_root)
            new_root = Path(migrated.config["run_root"])
            self.assertTrue((legacy_run / "run.json").exists())
            self.assertTrue((new_root / "legacy-run" / "run.json").exists())

    def test_duplicate_identity_requires_explicit_clone_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            original = root / "original"
            clone = root / "clone"
            original.mkdir()
            clone.mkdir()
            initial = initialize_project(original, home=home)
            clone_config = read_json(initial.config_path)
            clone_config_path = clone / ".loopforge" / "config.json"
            clone_config_path.parent.mkdir()
            write_json_atomic(clone_config_path, clone_config)

            blocked = open_project(str(clone), current_project_dir=clone, home=home)
            self.assertFalse(blocked.ok)
            self.assertIn("already registered", blocked.blockers[0])

            resolved = open_project(
                str(clone),
                current_project_dir=clone,
                home=home,
                identity_resolution="clone",
            )
            self.assertTrue(resolved.ok)
            assert resolved.init is not None
            self.assertNotEqual(resolved.init.config["project_id"], initial.config["project_id"])

    def test_global_runs_include_project_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            init = initialize_project(project, home=home)
            create_run(project, "List every project run", success_checks=["tests pass"])

            result = list_runs_all_projects(home)

            self.assertEqual(len(result.runs), 1)
            self.assertEqual(result.runs[0]["project_id"], init.config["project_id"])
            self.assertEqual(result.runs[0]["project"], project.name)

    def test_warm_run_listing_reads_the_compact_index_not_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            initial = initialize_project(project, home=root / "home")
            create_run(project, "Indexed run", success_checks=["tests pass"])

            store = __import__("loopforge.engine", fromlist=["DEFAULT_JSON_STORE"]).DEFAULT_JSON_STORE
            original = store.read_object
            with mock.patch.object(store, "read_object", wraps=original) as read_object:
                result = list_runs(project)

            self.assertEqual(len(result.runs), 1)
            read_paths = [str(call.args[0]) for call in read_object.call_args_list]
            self.assertIn(str(Path(initial.config["run_root"]) / "index.json"), read_paths)
            self.assertNotIn(str(Path(initial.config["run_root"]) / result.runs[0]["run_id"] / "run.json"), read_paths)

    def test_corrupt_run_index_is_safely_rebuilt_from_authoritative_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            initial = initialize_project(project, home=root / "home")
            created = create_run(project, "Recover index", success_checks=["tests pass"])
            index_path = Path(initial.config["run_root"]) / "index.json"
            index_path.write_text("not json", encoding="utf-8")

            result = list_runs(project)

            self.assertEqual([run["run_id"] for run in result.runs], [created.run["run_id"]])
            self.assertEqual(read_json(index_path)["index_version"], 1)
            repaired = rebuild_indexes(project)
            self.assertTrue(repaired.ok)
            self.assertTrue(created.run_json_path.exists())


class PackagedRuntimeLayoutTests(unittest.TestCase):
    def test_runtime_scripts_and_contracts_are_product_owned(self) -> None:
        package_root = Path(loopforge.__file__).resolve().parent

        self.assertEqual(Path(diff_policy.__file__).resolve().parent, package_root / "checks")
        self.assertEqual(
            Path(local_implementation_adapter.__file__).resolve().parent,
            package_root / "adapters",
        )
        self.assertEqual(
            local_implementation_adapter.POLICY_PATH,
            policy_path("local-implementation-adapter.json"),
        )
        self.assertTrue(policy_path("diff-policy.json").is_file())

    def test_isolated_environment_prefers_canonical_allowed_variable_names(self) -> None:
        policy = isolated_process.load_policy()

        selected = isolated_process.select_allowed_parent_environment(
            {
                "path": "lower",
                "PATH": "canonical",
                "HTTPS_PROXY": "secret-boundary",
            },
            policy,
        )

        self.assertEqual(selected, {"PATH": "canonical"})

    def test_codex_windows_runtime_environment_is_path_only_and_credential_safe(self) -> None:
        policy = isolated_process.load_policy()
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            parent = {
                "PATH": "safe-path",
                "APPDATA": str(profile),
                "LOCALAPPDATA": str(profile),
                "USERPROFILE": str(profile),
                "CODEX_API_KEY": "must-not-pass",
                "HTTPS_PROXY": "must-not-pass",
            }

            child = isolated_process.build_codex_windows_child_environment(
                parent,
                policy,
                windows=True,
            )

        self.assertEqual(child["APPDATA"], str(profile))
        self.assertEqual(child["LOCALAPPDATA"], str(profile))
        self.assertEqual(child["USERPROFILE"], str(profile))
        self.assertEqual(child["PATH"], "safe-path")
        self.assertNotIn("CODEX_API_KEY", child)
        self.assertNotIn("HTTPS_PROXY", child)

    def test_codex_windows_runtime_environment_rejects_missing_or_invalid_paths(self) -> None:
        policy = isolated_process.load_policy()
        with self.assertRaisesRegex(ValueError, "requires APPDATA"):
            isolated_process.codex_windows_runtime_environment({}, policy, windows=True)
        with self.assertRaisesRegex(ValueError, "existing absolute directory"):
            isolated_process.codex_windows_runtime_environment(
                {
                    "APPDATA": "relative",
                    "LOCALAPPDATA": "relative",
                    "USERPROFILE": "relative",
                },
                policy,
                windows=True,
            )

    def test_codex_windows_runtime_preflight_reports_the_environment_before_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with (
                mock.patch("loopforge.engine.git_toplevel", return_value=workspace),
                mock.patch("loopforge.engine.isolated_process_module") as isolated,
            ):
                isolated.return_value.load_policy.return_value = {}
                isolated.return_value.codex_windows_runtime_environment.side_effect = ValueError(
                    "Codex Windows runtime requires APPDATA"
                )
                blockers = codex_workspace_preflight_blockers(
                    "codex",
                    workspace,
                    implementation=True,
                )

        self.assertEqual(
            blockers,
            [
                "Codex Windows sandbox runtime preflight failed: "
                "Codex Windows runtime requires APPDATA"
            ],
        )
        isolated.return_value.codex_windows_runtime_environment.assert_called_once()

    def test_codex_windows_sandbox_helper_failure_is_classified(self) -> None:
        stderr = (
            b"ERROR codex_core::exec: exec error: windows sandbox:\n"
            b"orchestrator_helper_launch_failed: setup refresh failed to launch helper"
        )

        self.assertEqual(
            local_implementation_adapter.classify_codex_windows_sandbox_failure(stderr),
            "codex_windows_sandbox_helper_launch_failed",
        )
        self.assertIn(
            "sandbox helper failed to launch",
            local_implementation_adapter.summary_for(
                "failed",
                subprocess.CompletedProcess(["codex"], 1, stderr=stderr),
                False,
                False,
                local_implementation_adapter.load_policy(),
                stderr=stderr,
            ),
        )

    def test_adapter_retains_raw_child_stderr_as_evidence(self) -> None:
        policy = local_implementation_adapter.load_policy()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            session_path = workspace / "expected-session.json"
            child_stderr_path = workspace / "adapter-child.stderr"
            session_path.write_text(
                json.dumps(
                    {
                        "issue": 1,
                        "risk": "low",
                        "base_commit": "0" * 40,
                        "workspace": str(workspace.resolve()),
                        "runner_id": "local-adapter-fixture",
                        "recovery_authorized": False,
                        "preflight_sha256": "1" * 64,
                        "start_authorization_receipt_sha256": "2" * 64,
                    }
                ),
                encoding="utf-8",
            )

            local_implementation_adapter.run_adapter(
                session_path,
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('full child stderr'); sys.exit(3)",
                ],
                workspace,
                policy,
                child_stderr_output=child_stderr_path,
            )

            self.assertEqual(child_stderr_path.read_bytes(), b"full child stderr")

    def test_kilo_code_is_allowlisted_and_receives_the_loopforge_prompt(self) -> None:
        policy = local_implementation_adapter.load_policy()
        self.assertIn("kilo", policy["allowed_command_basenames"])
        self.assertIn("kilo.exe", policy["allowed_command_basenames"])

        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "adapter-prompt.md"
            prompt_path.write_text("Implement the bounded task.\n", encoding="utf-8")

            command = local_implementation_adapter.command_with_kilo_prompt(
                ["kilo", "run", "--model", "openai/gpt-5"], prompt_path
            )

        self.assertEqual(command[:-1], ["kilo", "run", "--model", "openai/gpt-5"])
        self.assertEqual(command[-1], "Implement the bounded task.\n")
        self.assertEqual(
            kilo_code.command_with_prompt(["kilo", "run", "--agent", "read-only"], "Inspect only."),
            ["kilo", "run", "--agent", "read-only", "Inspect only."],
        )
        self.assertEqual(
            kilo_code.headless_run_command([], default_agent=kilo_code.DEFAULT_READONLY_AGENT),
            ["kilo", "run", "--agent", "ask"],
        )
        self.assertEqual(
            kilo_code.headless_run_command(
                ["run", "--agent=architect"],
                default_agent=kilo_code.DEFAULT_IMPLEMENTATION_AGENT,
            ),
            ["kilo", "run", "--agent=architect"],
        )


class PackRegistryTests(unittest.TestCase):
    def test_bundled_python_pack_inherits_skills_agents_permissions_and_workflow(self) -> None:
        package_root = Path(__file__).resolve().parents[1] / "src" / "loopforge"
        registry = PackRegistry(
            package_root,
            bundled_root=package_root,
            bundled_packs_root=package_root / "packs",
            store=JsonStore(),
        )

        contract = registry.load_contract("python")

        self.assertEqual(contract["inherited_from"], ["generic-code"])
        self.assertEqual(len(contract["agents"]), 4)
        self.assertEqual(set(contract["permission_sets"]), {
            "read-only",
            "workspace-write",
            "deterministic-validator",
        })
        self.assertEqual([stage["id"] for stage in contract["workflow"]], [
            "task",
            "research",
            "plan",
            "implementation",
            "verification",
            "review",
            "publication",
        ])
        self.assertIn("repository-research", contract["skills"])
        self.assertIn("python-testing", contract["skills"])
        self.assertEqual(len(contract["skill_definition_files"]), 7)

    def test_contract_rejects_agent_with_unknown_permission_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack_dir = root / "project" / ".loopforge" / "packs" / "broken"
            pack_dir.mkdir(parents=True)
            (pack_dir / "pack.json").write_text(
                json.dumps(
                    {
                        "name": "broken",
                        "agents_file": "agents.json",
                        "permissions_file": "permissions.json",
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "agents.json").write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "id": "researcher",
                                "stages": ["research"],
                                "permission_set": "missing",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "permissions.json").write_text(
                json.dumps({"permission_sets": {"read-only": {}}}),
                encoding="utf-8",
            )
            registry = PackRegistry(
                root / "project",
                bundled_root=root / "bundled",
                store=JsonStore(),
            )

            with self.assertRaisesRegex(ValueError, "unknown permission set missing"):
                registry.load_contract("broken")

    def test_project_local_contract_overrides_bundled_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            bundled_root = root / "bundled"
            project_pack = project_dir / ".loopforge" / "packs" / "python"
            bundled_pack = bundled_root / ".loopforge" / "packs" / "python"
            project_pack.mkdir(parents=True)
            bundled_pack.mkdir(parents=True)
            (project_pack / "pack.json").write_text(
                json.dumps(
                    {
                        "name": "python",
                        "version": 1,
                        "description": "local",
                        "priority": 10,
                        "detection": {"files_any": ["local.marker"]},
                        "skills": ["local-skill"],
                    }
                ),
                encoding="utf-8",
            )
            (bundled_pack / "pack.json").write_text(
                json.dumps(
                    {
                        "name": "python",
                        "version": 1,
                        "description": "bundled",
                        "priority": 1,
                        "detection": {},
                        "skills": ["bundled-skill"],
                    }
                ),
                encoding="utf-8",
            )
            (project_dir / "local.marker").write_text("", encoding="utf-8")
            registry = PackRegistry(
                project_dir,
                bundled_root=bundled_root,
                store=JsonStore(),
            )

            self.assertEqual(registry.load_contract("python")["description"], "local")
            self.assertEqual(registry.detect()["name"], "python")
            self.assertEqual(registry.detect()["detection_score"], 30)
            self.assertEqual(registry.skill_entries(registry.detect()), ["local-skill"])

    def test_load_checks_and_protected_paths_normalizes_contract_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            pack_dir = project_dir / ".loopforge" / "packs" / "demo"
            pack_dir.mkdir(parents=True)
            (pack_dir / "checks.json").write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "name": "unit",
                                "command": ["python", "-m", "unittest"],
                                "env": {"MODE": "test"},
                                "timeout_seconds": 10,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "protected-paths.json").write_text(
                json.dumps(
                    {
                        "high_path_patterns": ["infra/**"],
                        "medium_path_patterns": ["docs/**"],
                    }
                ),
                encoding="utf-8",
            )
            registry = PackRegistry(
                project_dir,
                bundled_root=root / "bundled",
                store=JsonStore(),
            )

            self.assertEqual(registry.load_checks("demo")["checks"][0]["name"], "unit")
            self.assertEqual(
                registry.load_protected_paths("demo")["high_path_patterns"],
                ["infra/**"],
            )


class MetricsServiceTests(unittest.TestCase):
    def test_summary_keeps_unknown_values_out_of_averages(self) -> None:
        service = MetricsService(JsonStore())
        summary = service.build_summary(
            [
                {
                    "run_id": "one",
                    "timing": {"duration_seconds": 10},
                    "attempts": {"count": 1},
                    "patch": {"size_bytes": 20},
                    "verification": {"status": "passed"},
                    "final_disposition": {"status": "verified"},
                },
                {
                    "run_id": "two",
                    "timing": {"duration_seconds": None},
                    "attempts": {"count": 2},
                    "patch": {"size_bytes": None},
                    "verification": {"status": None},
                    "final_disposition": {"status": "pending"},
                },
            ]
        )

        self.assertEqual(summary["duration_seconds"]["average"], 10)
        self.assertEqual(summary["duration_seconds"]["unknown_count"], 1)
        self.assertEqual(summary["patch_size_bytes"]["sum"], 20)
        self.assertEqual(summary["verification_results"], {"passed": 1, "unknown": 1})


class StatusReadTests(unittest.TestCase):
    def test_status_does_not_recreate_missing_project_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            initialize_project(project, home=root / "home")
            memory_path = project / ".loopforge" / "memory.md"
            memory_path.unlink()

            status = current_status(project)

            self.assertEqual(status.memory["durable_status"], "missing")
            self.assertFalse(memory_path.exists())


if __name__ == "__main__":
    unittest.main()
