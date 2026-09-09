"""Phase-1 shared presentation and action contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from threading import Event, Thread
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from loopforge.cli.actions import action_descriptors, primary_action
from loopforge.cli.models import UiSnapshot
from loopforge.cli.operations import OperationController
from loopforge.cli.presentation import shell_snapshot, shell_snapshot_from_status, state_family, workflow_progress
from loopforge.cli.run_artifacts import load_run_agent_snapshot
from loopforge.cli.state_store import StateStore
from loopforge.cli.textual_app.run_presenter import activity_event_message
from loopforge.cli.textual_app.workers import load_project_snapshot
from loopforge.engine import GuidedAction, GuidanceResult, StatusResult, current_guidance, current_status, guidance_from_status


class CliPresentationTests(unittest.TestCase):
    def test_live_adapter_event_redacts_secrets_and_terminal_controls(self) -> None:
        rendered = activity_event_message(
            "adapter output",
            "plan stdout: password=visible-password\n\x1b]0;forged title\x07\u009dsafe",
        )

        self.assertIn("safe", rendered)
        self.assertNotIn("visible-password", rendered)
        self.assertNotIn("forged title", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("\u009d", rendered)

    def test_engine_guidance_maps_to_immutable_action_descriptors(self) -> None:
        guidance = self._guidance(
            GuidedAction(
                id="approve-plan",
                label="Review and approve the implementation plan",
                command="loopforge run",
                risk="low",
                requires_confirmation=True,
                why="Implementation requires a human plan approval.",
            )
        )

        actions = action_descriptors(guidance)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].executor_key, "approve-plan")
        self.assertEqual(actions[0].command_fallback, "loopforge run")
        self.assertTrue(actions[0].requires_confirmation)
        self.assertEqual(primary_action(guidance), actions[0])

    def test_snapshot_uses_pack_workflow_for_stage_and_actor(self) -> None:
        project_dir = Path("/workspace/LoopForge")
        workflow = [
            {"id": "task", "title": "Validate task", "actor": {"id": "intake"}},
            {"id": "research", "title": "Research", "actor": {"id": "researcher"}},
            {"id": "plan", "title": "Plan", "actor": {"id": "planner"}},
        ]
        status = StatusResult(
            project_dir=project_dir,
            config_path=project_dir / ".loopforge" / "config.json",
            initialized=True,
            config={"profile": "supervised"},
            run_dir=project_dir / "runs" / "run-1",
            run_json_path=None,
            run={
                "run_id": "run-1234567890",
                "task": "Improve the command view",
                "pack": "generic-code",
                "status": "awaiting_approval",
                "pack_contract": {"workflow": workflow},
                "stage_statuses": {"task": "approved", "research": "complete", "plan": "awaiting_approval"},
            },
            native_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=None,
            next_step="loopforge run",
            blockers=[],
        )
        guidance = self._guidance(
            GuidedAction(
                id="approve-plan",
                label="Approve plan",
                command="loopforge run",
                risk="low",
                requires_confirmation=True,
                why="The plan waits for approval.",
            ),
            state="plan_awaiting_approval",
        )

        snapshot = shell_snapshot(status, guidance)
        progress, actor, _ = workflow_progress(status.run or {})

        self.assertEqual(snapshot.family, "needs_human")
        self.assertEqual(snapshot.run.short_id, "run-12345678")
        self.assertEqual(snapshot.stages[-1].actor, "human-approver")
        self.assertEqual(snapshot.stages[-1].family, "needs_human")
        self.assertEqual(progress, "3/3 Plan")
        self.assertEqual(actor, "human-approver")

    def test_state_family_keeps_blockers_and_archives_distinct(self) -> None:
        self.assertEqual(state_family("verification_pending"), "ready")
        self.assertEqual(state_family("verification_pending", blocked=True), "blocked")
        self.assertEqual(state_family("draft_publication_ready", archived=True), "archived")

    def test_current_guidance_is_a_single_status_compatibility_wrapper(self) -> None:
        project = Path("/workspace/LoopForge")
        status = current_status(project)
        with (
            mock.patch("loopforge.engine.current_status", return_value=status) as status_read,
            mock.patch("loopforge.engine.guidance_from_status", wraps=guidance_from_status) as from_status,
        ):
            current_guidance(project)

        status_read.assert_called_once_with(project)
        from_status.assert_called_once_with(status)

    def test_snapshot_from_status_does_not_reload_status(self) -> None:
        status = current_status(Path("/workspace/LoopForge"))
        with mock.patch("loopforge.engine.current_status") as status_read:
            shell_snapshot_from_status(status)

        status_read.assert_not_called()

    def test_state_store_publishes_immutable_snapshots_only_for_current_navigation(self) -> None:
        project = Path("/workspace/LoopForge")
        other_project = Path("/workspace/Other")
        status = current_status(project)
        runs = SimpleNamespace(runs=[], blockers=[])
        projects = SimpleNamespace(projects=[])
        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: runs,
            projects_loader=lambda: projects,
            global_runs_loader=lambda: SimpleNamespace(runs=[{"run_id": "recent", "task": "Recent work"}]),
            branch_loader=lambda _: "main",
        )
        published: list[UiSnapshot] = []
        store.subscribe(published.append)

        first = store.refresh()
        again = store.refresh()

        self.assertEqual(first.revision, again.revision)
        self.assertEqual(first.home.runs[0]["run_id"], "recent")
        self.assertEqual(len(published), 1)
        with self.assertRaises(TypeError):
            first.home.projects[0]["name"] = "mutated"  # type: ignore[index]

        late_load = store.begin_load()
        store.select_project(other_project)
        after_navigation = store.snapshot
        discarded = store.publish_loaded(late_load, status, runs, projects)

        self.assertEqual(discarded.selected_project, other_project.resolve())
        self.assertEqual(discarded.revision, after_navigation.revision)

    def test_state_store_uses_canonical_run_metrics_and_bounds_activity_history(self) -> None:
        project = Path("/workspace/LoopForge")
        run_dir = project / ".loopforge" / "runs" / "run-metrics"
        status = StatusResult(
            project_dir=project,
            config_path=project / ".loopforge" / "config.json",
            initialized=True,
            config={"profile": "supervised"},
            run_dir=run_dir,
            run_json_path=run_dir / "run.json",
            run={
                "run_id": "run-metrics",
                "task": "Render reported metrics",
                "status": "task_awaiting_approval",
                "created_at": "2026-09-08T10:00:00Z",
                "attempts": [
                    {"number": number, "status": "completed"}
                    for number in range(1, 21)
                ],
            },
            native_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=None,
            next_step="loopforge run",
            blockers=[],
        )
        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
            projects_loader=lambda: SimpleNamespace(projects=[]),
            global_runs_loader=lambda: SimpleNamespace(runs=[]),
            branch_loader=lambda _: "master",
            metrics_loader=lambda _: (
                {"run_id": "run-metrics", "tokens": {"total_tokens": 4200}},
                None,
            ),
        )

        snapshot = store.refresh()

        self.assertEqual(snapshot.run.created_at, "2026-09-08T10:00:00Z")
        self.assertEqual(snapshot.run.total_tokens, 4200)
        self.assertEqual(len(snapshot.run.attempts), 12)
        self.assertEqual(snapshot.run.attempts[0]["number"], 9)

        missing_metrics = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
            projects_loader=lambda: SimpleNamespace(projects=[]),
            branch_loader=lambda _: "master",
            metrics_loader=lambda _: ({}, None),
        ).refresh()
        self.assertIsNone(missing_metrics.run.total_tokens)

    def test_state_store_loads_prompt_agent_output_and_contract_for_latest_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            run_dir = Path(temp_dir) / "runs" / "run-artifacts"
            attempt_dir = run_dir / "attempts" / "attempt-001"
            attempt_dir.mkdir(parents=True)
            (attempt_dir / "adapter-prompt.md").write_text(
                "System prompt for the visible attempt.",
                encoding="utf-8",
            )
            (attempt_dir / "adapter.stdout").write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "reasoning",
                            "text": "Inspect the configuration flow.",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "pytest --quiet",
                            "aggregated_output": "12 passed",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "Implementation complete.",
                        },
                    }
                )
                + "\n"
                + "password=visible-password\x1b]0;forged title\x07\u009d\n",
                encoding="utf-8",
            )
            (attempt_dir / "result.json").write_text(
                json.dumps(
                    {
                        "result_version": 1,
                        "purpose": "implementation_session_result",
                        "status": "completed",
                        "summary": "Adjusted the configuration button.",
                        "workspace_changed": True,
                        "next_action": "deterministic_patch_generation",
                        "workspace": "private-workspace-marker",
                    }
                ),
                encoding="utf-8",
            )
            status = StatusResult(
                project_dir=project,
                config_path=project / ".loopforge" / "config.json",
                initialized=True,
                config={"profile": "supervised"},
                run_dir=run_dir,
                run_json_path=run_dir / "run.json",
                run={
                    "run_id": "run-artifacts",
                    "task": "Show the harness transcript",
                    "status": "implementation_running",
                    "attempts": [
                        {
                            "number": 1,
                            "adapter": "codex",
                            "execution_mode": "headless",
                            "result_origin": "adapter",
                            "attempt_dir": str(attempt_dir),
                            "prompt_path": "attempts/attempt-001/adapter-prompt.md",
                            "stdout_path": "attempts/attempt-001/adapter.stdout",
                            "result_path": "attempts/attempt-001/result.json",
                        }
                    ],
                },
                native_artifacts=None,
                loop_contract=None,
                verification=None,
                memory=None,
                next_step="loopforge continue",
                blockers=[],
            )
            run_agent_loader = mock.Mock(side_effect=load_run_agent_snapshot)
            store = StateStore(
                project,
                status_loader=lambda _: status,
                runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
                projects_loader=lambda: SimpleNamespace(projects=[]),
                global_runs_loader=lambda: SimpleNamespace(runs=[]),
                branch_loader=lambda _: "main",
                metrics_loader=lambda _: ({}, None),
                run_agent_loader=run_agent_loader,
            )

            snapshot = store.refresh()

            self.assertEqual(snapshot.run.agent.attempt_number, 1)
            self.assertEqual(snapshot.run.agent.adapter, "codex")
            self.assertIn("System prompt for the visible attempt", snapshot.run.agent.system_prompt)
            self.assertIn("Reasoning", snapshot.run.agent.agent_output)
            self.assertIn("Inspect the configuration flow.", snapshot.run.agent.agent_output)
            self.assertIn("$ pytest --quiet", snapshot.run.agent.agent_output)
            self.assertIn("12 passed", snapshot.run.agent.agent_output)
            self.assertIn("Implementation complete.", snapshot.run.agent.agent_output)
            self.assertNotIn("visible-password", snapshot.run.agent.agent_output)
            self.assertNotIn("forged title", snapshot.run.agent.agent_output)
            self.assertNotIn("\x1b", snapshot.run.agent.agent_output)
            self.assertIn("Adjusted the configuration button", snapshot.run.agent.implementation_contract)
            self.assertNotIn("private-workspace-marker", snapshot.run.agent.implementation_contract)

            outside_prompt = Path(temp_dir) / "outside-prompt.md"
            outside_prompt.write_text("outside-prompt-marker", encoding="utf-8")
            escaped_attempt = dict(status.run["attempts"][0])
            escaped_attempt["prompt_path"] = "../../outside-prompt.md"
            escaped_status = replace(
                status,
                run={**status.run, "attempts": [escaped_attempt]},
            )
            escaped = load_run_agent_snapshot(escaped_status)
            self.assertNotIn("outside-prompt-marker", escaped.system_prompt)

            live_dir = run_dir / "attempts" / "attempt-002"
            live_dir.mkdir()
            (live_dir / "adapter-prompt.md").write_text(
                "Live system prompt.",
                encoding="utf-8",
            )
            operation = OperationController("Implementation")
            store.set_operation(operation)
            operation.emit(
                {
                    "kind": "attempt_started",
                    "message": "Starting codex implementation attempt attempt-002.",
                    "artifact": str(live_dir),
                }
            )
            store.record_operation_events(operation)
            live = store.flush()

            self.assertEqual(live.run.agent.attempt_number, 2)
            self.assertEqual(live.run.agent.system_prompt, "Live system prompt.")
            self.assertEqual(live.run.agent.implementation_contract, "")
            loads_after_session_started = run_agent_loader.call_count

            operation.emit(
                {
                    "kind": "adapter_output",
                    "message": "adapter stdout: Reasoning\n  Inspecting the run.",
                }
            )
            store.record_operation_events(operation)

            self.assertEqual(run_agent_loader.call_count, loads_after_session_started)

    def test_run_agent_snapshot_keeps_full_prompt_and_hides_terminal_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            attempt_dir = Path(temp_dir) / "runs" / "run-prompt" / "attempts" / "attempt-001"
            attempt_dir.mkdir(parents=True)
            prompt = "System prompt\n" + ("x" * 40_000) + "\nPrompt end marker"
            (attempt_dir / "adapter-prompt.md").write_text(prompt, encoding="utf-8")
            (attempt_dir / "result.json").write_text(
                json.dumps(
                    {
                        "result_version": 1,
                        "purpose": "implementation_session_result",
                        "status": "completed",
                        "summary": "Synthetic terminal summary.",
                    }
                ),
                encoding="utf-8",
            )
            run_dir = attempt_dir.parents[1]
            status = StatusResult(
                project_dir=project,
                config_path=project / ".loopforge" / "config.json",
                initialized=True,
                config={"profile": "supervised"},
                run_dir=run_dir,
                run_json_path=run_dir / "run.json",
                run={
                    "run_id": "run-prompt",
                    "attempts": [
                        {
                            "number": 1,
                            "adapter": "codex",
                            "execution_mode": "terminal",
                            "result_origin": "loopforge",
                            "attempt_dir": str(attempt_dir),
                            "prompt_path": "attempts/attempt-001/adapter-prompt.md",
                            "result_path": "attempts/attempt-001/result.json",
                        }
                    ],
                },
                native_artifacts=None,
                loop_contract=None,
                verification=None,
                memory=None,
                next_step="loopforge continue",
                blockers=[],
            )

            snapshot = load_run_agent_snapshot(status)

            self.assertEqual(snapshot.system_prompt, prompt)
            self.assertIn("Prompt end marker", snapshot.system_prompt)
            self.assertEqual(snapshot.implementation_contract, "")

    def test_run_agent_snapshot_loads_readonly_stage_prompt_and_codex_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            run_dir = Path(temp_dir) / "runs" / "run-stage-artifacts"
            stage_dir = run_dir / "artifacts" / "stages" / "plan"
            stage_dir.mkdir(parents=True)
            (stage_dir / "prompt.md").write_text(
                "Plan system prompt for the current run.",
                encoding="utf-8",
            )
            (stage_dir / "adapter.stdout").write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "reasoning",
                            "text": "Read the repository before planning.",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "rg --files",
                            "aggregated_output": "DESIGN.md\nsrc/loopforge/engine/stages.py",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (stage_dir / "execution.json").write_text(
                json.dumps({"adapter": "codex", "stream_format": "codex-jsonl"}),
                encoding="utf-8",
            )
            status = StatusResult(
                project_dir=project,
                config_path=project / ".loopforge" / "config.json",
                initialized=True,
                config={"profile": "supervised"},
                run_dir=run_dir,
                run_json_path=run_dir / "run.json",
                run={
                    "run_id": "run-stage-artifacts",
                    "task": "Show the planning harness transcript",
                    "status": "plan_running",
                    "attempts": [],
                },
                native_artifacts=None,
                loop_contract=None,
                verification=None,
                memory=None,
                next_step="loopforge run",
                blockers=[],
            )

            snapshot = load_run_agent_snapshot(status)

            self.assertIsNone(snapshot.attempt_number)
            self.assertEqual(snapshot.adapter, "codex")
            self.assertIn("Plan system prompt", snapshot.system_prompt)
            self.assertIn("Reasoning", snapshot.agent_output)
            self.assertIn("Read the repository before planning.", snapshot.agent_output)
            self.assertIn("$ rg --files", snapshot.agent_output)
            self.assertIn("DESIGN.md", snapshot.agent_output)
            self.assertEqual(snapshot.implementation_contract, "")

            kilo_reasoning = {
                "type": "reasoning",
                "sessionID": "kilo-session",
                "part": {
                    "id": "reasoning-1",
                    "type": "reasoning",
                    "text": "Inspect the Kilo workspace.",
                },
            }
            kilo_tool = {
                "type": "tool_use",
                "sessionID": "kilo-session",
                "part": {
                    "id": "tool-1",
                    "type": "tool",
                    "tool": "glob",
                    "state": {
                        "status": "completed",
                        "input": {"pattern": "*"},
                        "output": "README.md",
                    },
                },
            }
            kilo_answer = {
                "type": "text",
                "sessionID": "kilo-session",
                "part": {
                    "id": "text-1",
                    "type": "text",
                    "text": "Kilo completed the read-only stage.",
                },
            }
            (stage_dir / "adapter.stdout").write_text(
                "\n".join(
                    json.dumps(value)
                    for value in (
                        kilo_reasoning,
                        kilo_reasoning,
                        kilo_tool,
                        kilo_tool,
                        kilo_answer,
                        kilo_answer,
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (stage_dir / "execution.json").write_text(
                json.dumps({"adapter": "kilo-code", "stream_format": "kilo-jsonl"}),
                encoding="utf-8",
            )

            kilo_snapshot = load_run_agent_snapshot(status)

            self.assertEqual(kilo_snapshot.adapter, "kilo-code")
            self.assertEqual(kilo_snapshot.agent_output.count("Inspect the Kilo workspace."), 1)
            self.assertIn("Tool call (completed) · glob", kilo_snapshot.agent_output)
            self.assertIn("README.md", kilo_snapshot.agent_output)
            self.assertEqual(
                kilo_snapshot.agent_output.count("Kilo completed the read-only stage."),
                1,
            )

    def test_state_store_discards_load_that_becomes_stale_during_metrics_read(self) -> None:
        project = Path("/workspace/LoopForge")
        other = Path("/workspace/Other")
        run_dir = project / ".loopforge" / "runs" / "run-race"
        status = StatusResult(
            project_dir=project,
            config_path=project / ".loopforge" / "config.json",
            initialized=True,
            config={"profile": "supervised"},
            run_dir=run_dir,
            run_json_path=run_dir / "run.json",
            run={"run_id": "run-race", "task": "Keep navigation fresh"},
            native_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=None,
            next_step="loopforge run",
            blockers=[],
        )
        metrics_started = Event()
        release_metrics = Event()

        def load_metrics(_: Path) -> tuple[dict[str, object], str | None]:
            metrics_started.set()
            release_metrics.wait(1)
            return {"run_id": "run-race", "tokens": {"total_tokens": 42}}, None

        store = StateStore(
            project,
            branch_loader=lambda _: "master",
            metrics_loader=load_metrics,
        )
        identity = store.begin_load()
        worker = Thread(
            target=lambda: store.publish_loaded(
                identity,
                status,
                SimpleNamespace(runs=[], blockers=[]),
                SimpleNamespace(projects=[]),
            )
        )
        worker.start()
        self.assertTrue(metrics_started.wait(1))
        store.select_project(other)
        release_metrics.set()
        worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(store.snapshot.selected_project, other.resolve())
        self.assertIsNone(store.snapshot.run.shell)

    def test_textual_worker_publishes_projects_before_loading_global_runs(self) -> None:
        project = Path("/workspace/LoopForge")
        status = current_status(project)
        projects = SimpleNamespace(
            projects=[
                {
                    "name": "LoopForge",
                    "path": str(project),
                    "initialized": False,
                    "run_count": 0,
                    "attention": "ready",
                }
            ]
        )
        publications: list[UiSnapshot] = []
        publication_count_at_global_load: list[int] = []

        def load_global_runs() -> SimpleNamespace:
            publication_count_at_global_load.append(len(publications))
            return SimpleNamespace(runs=[{"run_id": "recent", "task": "Recent work"}])

        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
            projects_loader=lambda: projects,
            global_runs_loader=load_global_runs,
            branch_loader=lambda _: "main",
        )
        store.subscribe(publications.append)

        final = load_project_snapshot(store, lazy_global_runs=True)

        self.assertEqual(publication_count_at_global_load, [1])
        self.assertGreaterEqual(len(publications), 2)
        self.assertEqual(publications[0].home.projects[0]["name"], "LoopForge")
        self.assertEqual(publications[0].home.runs, ())
        self.assertEqual(final.home.runs[0]["run_id"], "recent")

        stale_identity = store.begin_load()
        store.select_project(Path("/workspace/other"))
        loads_before_stale_refresh = len(publication_count_at_global_load)
        store.refresh_global_runs(stale_identity)
        self.assertEqual(
            len(publication_count_at_global_load),
            loads_before_stale_refresh,
            "A stale worker must not start the global run scan.",
        )

    def test_state_store_coalesces_operation_events_until_the_ui_turn_flushes(self) -> None:
        project = Path("/workspace/LoopForge")
        status = current_status(project)
        store = StateStore(
            project,
            status_loader=lambda _: status,
            runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
            projects_loader=lambda: SimpleNamespace(projects=[]),
            global_runs_loader=lambda: SimpleNamespace(runs=[]),
            branch_loader=lambda _: "main",
        )
        store.refresh()
        published: list[UiSnapshot] = []
        store.subscribe(published.append)
        operation = OperationController("Refresh")
        store.set_operation(operation)
        operation.emit({"kind": "activity", "message": "First"})
        operation.emit({"kind": "activity", "message": "Second"})

        store.record_operation_events(operation)

        self.assertEqual(len(published), 1)
        snapshot = store.flush()
        self.assertEqual(len(published), 2)
        self.assertEqual([event.message for event in snapshot.operation.events], ["First", "Second"])

    @staticmethod
    def _guidance(action: GuidedAction, *, state: str = "plan_awaiting_approval") -> GuidanceResult:
        return GuidanceResult(
            project_dir=Path("/workspace/LoopForge"),
            state=state,
            summary="A test guidance state.",
            priority="test",
            diagnostics=[],
            recommended_actions=[action],
            blocked_reasons=[],
            evidence=[],
        )
