from __future__ import annotations

import io
import json
import unittest
import tomllib
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from loopforge.adapters.commands import headless_implementation_command
from loopforge.adapters.local_implementation_adapter import (
    StreamPresenter,
    adapter_event_lines,
    structured_final_message,
    structured_stream_format,
)
from loopforge.cli.run_artifacts import _agent_output, load_run_agent_snapshot
from loopforge.cli.textual_app.run_presenter import transcript_text
from loopforge.engine.adapter_runtime import command_for_readonly_stage
from loopforge.adapters.observation import TerminalObservation, retire_terminal_transcript
from loopforge.adapters.observation_hook import record_hook
from loopforge.engine.terminal import launch_terminal_session, TerminalSessionResult
from loopforge.cli.models import RunAgentSnapshot
from loopforge.cli.operations import OperationController
from loopforge.cli.state_store import StateStore
from loopforge.engine import current_status


class AgentTranscriptTests(unittest.TestCase):
    def test_all_machine_harnesses_request_native_events(self):
        for adapter, expected in (("codex", "codex"), ("claude-code", "claude"),
                                  ("kilo-code", "kilo"), ("opencode", "opencode")):
            with self.subTest(adapter=adapter):
                command = headless_implementation_command(adapter=adapter, adapter_args=[])
                self.assertEqual(structured_stream_format(command), expected)
                self.assertNotIn("--dangerously-skip-permissions", command)

    def test_claude_messages_tools_and_errors_survive_bytewise_streaming(self):
        events = [
            {"type": "system", "subtype": "init", "apiKey": "must-not-appear"},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "Vérifier les entrées.", "signature": "hidden"},
                {"type": "redacted_thinking", "data": "hidden"},
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "python -m unittest", "password": "private-value"}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                 "content": [{"type": "text", "text": "One test failed\nCheck fixture"}]},
            ]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Réparé."}]}},
            {"type": "result", "result": "Réparé.", "is_error": False},
        ]
        wire = "\n".join(json.dumps(event, ensure_ascii=False) for event in events).encode()
        output = io.StringIO()
        presenter = StreamPresenter(output, stream_format="claude")
        for byte in wire:
            presenter.write(bytes([byte]))
        presenter.close()
        rendered = output.getvalue()
        self.assertIn("Reasoning\n  Vérifier les entrées.", rendered)
        self.assertIn("Tool call · Bash", rendered)
        self.assertIn("Tool result (failed)", rendered)
        self.assertIn("Check fixture", rendered)
        self.assertEqual(rendered.count("Réparé."), 1)
        for private in ("hidden", "private-value", "must-not-appear", "\ufffd"):
            self.assertNotIn(private, rendered)
        self.assertEqual(structured_final_message(wire, "claude").decode(), "Réparé.")
        self.assertEqual(_agent_output(wire.decode()), _agent_output(rendered))

    def test_opencode_uses_part_contract_and_deduplicates(self):
        event = {"type": "tool_use", "part": {"id": "tool1", "type": "tool", "tool": "read",
                 "state": {"status": "completed", "input": {"filePath": "README.md"},
                           "output": "# Project\nDetails"}}}
        state = {}
        lines = adapter_event_lines(event, state)
        self.assertIn("Tool call (completed) · read", lines)
        self.assertEqual(adapter_event_lines(event, state), [])
        self.assertIn("README.md", "\n".join(lines))

    def test_readonly_claude_keeps_plan_permissions_and_extracts_artifact(self):
        command = command_for_readonly_stage(adapter="claude-code", adapter_args=[], workspace_dir=Path("."))
        self.assertIn("plan", command)
        self.assertEqual(structured_stream_format(command), "claude")
        wire = b'{"type":"result","result":"# Research\\nFindings","is_error":false}\n'
        self.assertEqual(structured_final_message(wire, "claude"), b"# Research\nFindings")

    def test_plain_fallback_keeps_all_lines(self):
        output = io.StringIO()
        presenter = StreamPresenter(output, plain_text=True)
        presenter.write(b"First line\nSecond line\nThird")
        presenter.close()
        self.assertEqual(output.getvalue(), "First line\n\nSecond line\n\nThird\n\n")

    def test_readable_blocks_survive_outer_subprocess_chunk_boundaries(self):
        output = io.StringIO()
        presenter = StreamPresenter(output, text_blocks=True)
        for part in (b"Tool ca", b"ll\n  $ pytest\n  R\xc3", b"\xa9ussi\n\nAgent message\n  Done"):
            presenter.write(part)
        presenter.close()
        self.assertEqual(output.getvalue(), "Tool call\n  $ pytest\n  Réussi\nAgent message\n  Done")

    def test_transcript_hierarchy_preserves_indentation_and_literal_markup(self):
        value = "Reasoning\n  Inspect [red]literal[/red].\nTool call (completed)\n  $ pytest\n    OK"
        stored = _agent_output(value)
        self.assertIn("\n    OK", stored)
        rendered = transcript_text(stored)
        self.assertIn("\n\nTool call", rendered.plain)
        self.assertIn("[red]literal[/red]", rendered.plain)
        self.assertTrue(any("bold" in str(span.style) for span in rendered.spans))

    def test_terminal_and_structured_journal_observe_the_same_session(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            native = root / ".codex/sessions/session.jsonl"
            native.parent.mkdir(parents=True)
            native.write_text(json.dumps({"type": "event_msg", "payload": {
                "type": "agent_reasoning", "text": "Inspect the existing tests."}}) + "\n")
            chunks = []
            def launch(request):
                self.assertEqual(request.command[-1], "Run prompt")
                self.assertNotIn("--dangerously-bypass-hook-trust", request.command)
                spool = Path(request.environment["LOOPFORGE_OBSERVATION_DIR"])
                for name in ("SessionStart", "PreToolUse", "PostToolUse"):
                    record_hook({"cwd": str(workspace), "session_id": "one",
                                 "transcript_path": str(native), "hook_event_name": name,
                                 "tool_name": "Bash", "tool_input": {"command": "pytest"},
                                 "tool_response": "3 passed"}, spool, workspace)
                request.output_chunk_callback("stdout", b"\x1b[Hrepaint noise")
                return TerminalSessionResult(launched=True, returncode=0, output=b"raw console")
            with mock.patch("pathlib.Path.home", return_value=root):
                result = launch_terminal_session(command=("codex", "Run prompt"), cwd=workspace,
                    title="Run", timeout_seconds=30, artifacts_dir=root / "artifacts",
                    terminal_launcher=mock.Mock(launch=launch),
                    output_chunk_callback=lambda stream, data: chunks.append(data))
            text = b"".join(chunks).decode()
            journal = (root / "artifacts/agent-transcript.log").read_text()
            self.assertEqual(result.output, b"raw console")
            self.assertIn("Reasoning\n  Inspect the existing tests.", journal)
            self.assertIn("Tool call · Bash", journal)
            self.assertIn("3 passed", journal)
            self.assertNotIn("repaint noise", text)
            self.assertEqual(journal, text)

    def test_hook_rejects_another_workspace_and_observer_rejects_another_session(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            observation = TerminalObservation(("claude", "prompt"), root, root / "artifacts", None)
            observation.prepare()
            record_hook({"cwd": str(root / "other"), "hook_event_name": "PreToolUse"}, observation.spool, root)
            self.assertFalse(observation.events_path.exists())
            observation.consume({"session_id": "one", "hook_event_name": "SessionStart",
                                 "transcript_path": str(root / "secret.jsonl")})
            self.assertIsNone(observation.native_path)
            observation.consume({"session_id": "two", "hook_event_name": "PreToolUse",
                                 "tool_name": "unrelated"})
            self.assertNotIn("unrelated", observation.journal.read_text())

    def test_opencode_and_kilo_plugins_are_local_and_scoped(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for adapter, variable in (("kilo", "KILO_CONFIG_CONTENT"), ("opencode", "OPENCODE_CONFIG_CONTENT")):
                observation = TerminalObservation((adapter, "prompt"), root, root / adapter, None)
                observation.prepare()
                config = json.loads(observation.environment[variable])
                self.assertTrue(config["plugin"][0].startswith("file://"))
                self.assertNotIn("permission", config)
                event = {"type": "text", "part": {"id": "msg1", "type": "text", "text": "Done."}}
                observation.events_path.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n")
                observation.close()
                self.assertEqual(observation.journal.read_text().count("Done."), 1)

    def test_unavailable_terminal_does_not_mask_headless_fallback(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            result = launch_terminal_session(command=("codex", "prompt"), cwd=root,
                title="Run", timeout_seconds=30, artifacts_dir=root / "artifacts",
                terminal_launcher=mock.Mock(launch=mock.Mock(return_value=TerminalSessionResult(
                    launched=False, returncode=None))))
            self.assertFalse(result.launched)
            self.assertFalse((root / "artifacts/agent-transcript.log").exists())

    def test_headless_retry_retires_previous_terminal_journal(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            journal = root / "agent-transcript.log"
            journal.write_text("Old terminal output")
            retire_terminal_transcript(root)
            self.assertFalse(journal.exists())
            self.assertEqual(next(root.glob("previous-agent-transcript-*.log")).read_text(), "Old terminal output")

    def test_live_journal_refreshes_after_the_initial_session_snapshot(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            current = RunAgentSnapshot(system_prompt="Prompt", has_live_transcript=True,
                                       agent_output="Reasoning\n  First")
            loader = mock.Mock(side_effect=lambda *_: current)
            store = StateStore(root, status_loader=lambda _: current_status(root),
                runs_loader=lambda _: SimpleNamespace(runs=[], blockers=[]),
                projects_loader=lambda: SimpleNamespace(projects=[]),
                global_runs_loader=lambda: SimpleNamespace(runs=[]),
                branch_loader=lambda _: "main", run_agent_loader=loader)
            store.refresh()
            operation = OperationController("Run")
            store.set_operation(operation)
            operation.emit({"kind": "attempt_started", "artifact": "attempts/attempt-001"})
            store.record_operation_events(operation)
            store.flush()
            current = replace(current, agent_output="Tool result\n  Finished")
            operation.emit({"kind": "adapter_output", "message": "New journal event"})
            store.record_operation_events(operation)
            snapshot = store.flush()
            self.assertIn("Finished", snapshot.run.agent.agent_output)

    def test_codex_hook_overrides_are_valid_toml_and_keep_trust_enabled(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            observer = TerminalObservation(("codex", "prompt"), root, root / "artifacts", None)
            observer.prepare()
            parsed = [tomllib.loads(observer.command[index + 1])
                      for index, value in enumerate(observer.command) if value == "-c"]
            self.assertEqual(len(parsed), 4)
            self.assertTrue(all("hooks" in config for config in parsed))
            self.assertNotIn("--dangerously-bypass-hook-trust", observer.command)
            for config in parsed:
                handler = next(iter(config["hooks"].values()))[0]["hooks"][0]
                self.assertEqual(handler["timeout"], 3)
                self.assertNotIn(str(observer.spool), handler["command"])

    def test_claude_settings_keep_existing_hooks_and_permissions(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            original = {"permissions": {"deny": ["Bash(rm *)"]},
                        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                            {"type": "command", "command": "existing-validator"}]}]}}
            source = root / "settings.json"
            source.write_text(json.dumps(original))
            observer = TerminalObservation(("claude", "--settings", "settings.json", "prompt"),
                                           root, root / "artifacts", None)
            observer.prepare()
            index = observer.command.index("--settings")
            merged = json.loads(Path(observer.command[index + 1]).read_text())
            self.assertEqual(merged["permissions"], original["permissions"])
            self.assertEqual(merged["hooks"]["PreToolUse"][0], original["hooks"]["PreToolUse"][0])
            self.assertEqual(len(merged["hooks"]["PreToolUse"]), 2)
            self.assertEqual(json.loads(source.read_text()), original)
            self.assertEqual(observer.command[-1], "prompt")

    def test_observation_limit_is_explicit_and_bounded(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            observer = TerminalObservation(("kilo", "prompt"), root, root / "artifacts", None)
            observer.prepare()
            for _ in range(40):
                observer.publish(["Agent message", "  " + "x" * 7000])
            text = observer.journal.read_text()
            self.assertLessEqual(observer.journal.stat().st_size, 131_072)
            self.assertEqual(text.count("Observation limit reached"), 1)

    def test_reopened_run_prefers_recent_journal_over_terminal_repaints(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            attempt = root / "attempts/attempt-001"
            attempt.mkdir(parents=True)
            (attempt / "adapter.stdout").write_text("raw terminal repaint")
            (attempt / "agent-transcript.log").write_text(
                "old output\n" * 2000 + "Tool result (completed)\n  Latest result\n")
            status = SimpleNamespace(run_dir=root, run={"attempts": [{"number": 1}]})
            snapshot = load_run_agent_snapshot(status)
            self.assertTrue(snapshot.has_live_transcript)
            self.assertIn("Latest result", snapshot.agent_output)
            self.assertIn("Earlier output omitted", snapshot.agent_output)
            self.assertNotIn("raw terminal repaint", snapshot.agent_output)

    def test_exit_drains_event_bursts_larger_than_one_read(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            observer = TerminalObservation(("kilo", "prompt"), root, root / "artifacts", None)
            observer.prepare()
            filler = json.dumps({"type": "step_start", "padding": "x" * 36_000}) + "\n"
            last = json.dumps({"type": "text", "part": {
                "id": "last", "type": "text", "text": "Final event was drained."}}) + "\n"
            observer.events_path.write_text(filler * 2 + last)
            observer.close()
            self.assertIn("Final event was drained.", observer.journal.read_text())


if __name__ == "__main__":
    unittest.main()
