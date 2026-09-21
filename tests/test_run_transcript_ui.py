"""Readable run journal: native identity, disclosure, and completion receipts."""

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.text import Text
from rich.console import Group
from rich.console import Console
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Static

from loopforge.adapters.local_implementation_adapter import adapter_event_lines
from loopforge.adapters.observation import TerminalObservation
from loopforge.cli.textual_app.run_presenter import (
    agent_body_renderable,
    run_activity_text,
    transcript_entries,
)
from loopforge.cli.textual_app.widgets import RunAgentOutput, RunToolEntry


def codex_call(identity, status, command="pytest", output=""):
    return "\n".join(adapter_event_lines({"type": "item.updated", "item": {
        "id": identity, "type": "command_execution", "status": status,
        "command": command, "aggregated_output": output,
        "exit_code": 0 if status == "completed" else None,
    }}, {}))


class TranscriptReductionTests(unittest.TestCase):
    def test_agent_body_highlights_explicit_fenced_code(self):
        rendered = agent_body_renderable(
            "Before\n```python\nprint('[red]literal[/red]')\n```\nAfter"
        )
        self.assertIsInstance(rendered, Group)
        syntax = next(part for part in rendered.renderables if isinstance(part, Syntax))
        self.assertEqual(syntax.lexer.name, "Python")
        self.assertIn("print", syntax.code)
        self.assertNotIn("```", syntax.code)

    def test_agent_body_highlights_partial_live_code_and_unknown_languages_safely(self):
        rendered = agent_body_renderable("```future-language\nvalue = 1")
        self.assertIsInstance(rendered, Syntax)
        self.assertEqual(rendered.lexer.name, "Text only")
        self.assertEqual(rendered.code, "value = 1")

    def test_fences_support_installed_lexers_and_metadata(self):
        for language, code in (("rust", 'fn main() { println!("hello"); }'),
                               ("c++", "int main() { return 0; }"),
                               ("go", "package main")):
            with self.subTest(language=language):
                rendered = agent_body_renderable(f"~~~{language} title=example\n{code}\n~~~")
                self.assertIsInstance(rendered, Syntax)
                self.assertNotEqual(rendered.lexer.name, "Text only")
                self.assertEqual(rendered.code, code)
                self.assertGreater(len(rendered.highlight(code).spans), 1)

    def test_nested_and_mismatched_fences_stay_inside_code(self):
        rendered = agent_body_renderable("````markdown\n```python\nprint(1)\n```\n~~~\n````")
        self.assertIsInstance(rendered, Syntax)
        self.assertEqual(rendered.code, "```python\nprint(1)\n```\n~~~")

    def test_transcript_keeps_code_blank_lines_and_indentation(self):
        body = "Before\n\n  ```python\n  def example():\n\n      return 1\n  ```\nAfter"
        value = "\n".join(adapter_event_lines({"type": "item.completed", "item": {
            "type": "agent_message", "text": body}}, {}))
        entry, = transcript_entries(value)
        self.assertEqual(entry.body, body)
        rendered = agent_body_renderable(entry.body)
        syntax = next(part for part in rendered.renderables if isinstance(part, Syntax))
        self.assertEqual(syntax.code, "def example():\n\n    return 1")

    def test_tool_commands_and_json_are_colored_without_changing_text(self):
        value = '$ echo "[red]literal[/red]"\nArguments: {\n  "count": 2,\n  "enabled": true\n}\nOutput: unchanged'
        rendered = agent_body_renderable(value, tool_output=True)
        self.assertEqual(rendered.plain, value)
        styles = {str(span.style) for span in rendered.spans}
        self.assertGreater(len(styles), 1)
        self.assertEqual(agent_body_renderable(value).spans, [])
        incomplete = 'Input: {"count":\nOutput: unfinished'
        self.assertEqual(agent_body_renderable(incomplete, tool_output=True).plain, incomplete)

    def test_no_color_rendering_preserves_literal_content(self):
        rendered = agent_body_renderable("```python\nprint('[red]literal[/red]')\n```")
        console = Console(no_color=True, force_terminal=False, width=60)
        with console.capture() as captured:
            console.print(rendered)
        self.assertIn("[red]literal[/red]", captured.get())
        self.assertNotIn("\x1b", captured.get())

    def test_native_identity_updates_parallel_calls_without_merging_them(self):
        entries = transcript_entries("\n".join([
            codex_call("a", "in_progress"), codex_call("b", "in_progress"),
            "Agent message\n  Testing both configurations.",
            codex_call("b", "completed", output="B passed"),
            codex_call("a", "completed", output="A passed"),
        ]))
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.key for e in entries[:2]], ["call:a", "call:b"])
        self.assertTrue(all(e.status == "completed" for e in entries[:2]))
        self.assertIn("A passed", entries[0].body)
        self.assertNotIn("B passed", entries[0].body)
        self.assertEqual(entries[0].title, "Shell")
        self.assertEqual(entries[0].summary, "pytest")
        self.assertNotIn("Call ID", entries[0].body)

    def test_claude_result_retains_name_and_input(self):
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "a.py"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "Permission denied", "is_error": True}]}},
        ]
        entries = transcript_entries("\n".join("\n".join(adapter_event_lines(e, {})) for e in events))
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].title, entries[0].status), ("Read", "failed"))
        self.assertIn("a.py", entries[0].body)
        self.assertIn("Permission denied", entries[0].body)

    def test_opencode_and_kilo_lifecycle(self):
        events = [{"type": "tool_use", "part": {"id": "p", "callID": "c", "tool": "read",
                   "type": "tool", "state": {"status": status, "input": {"filePath": "a.py"}}}}
                  for status in ("pending", "running", "completed")]
        entries = transcript_entries("\n".join("\n".join(adapter_event_lines(e, {})) for e in events))
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].key, entries[0].status), ("call:c", "completed"))

    def test_legacy_calls_only_merge_when_unambiguous(self):
        start = "Tool call (in_progress)\n  $ pytest"
        end = "Tool call (completed, exit 0)\n  $ pytest\n  OK"
        self.assertEqual(len(transcript_entries(start + "\n" + end)), 1)
        self.assertEqual(len(transcript_entries(start + "\n" + start + "\n" + end)), 3)
        self.assertEqual(len(transcript_entries(end + "\n" + end)), 2)

    def test_failed_exit_and_late_start_do_not_hide_failure(self):
        value = codex_call("a", "completed").replace("exit 0", "exit 2")
        entries = transcript_entries(value + "\n" + codex_call("a", "in_progress"))
        self.assertEqual(entries[0].status, "failed")
        self.assertIn("Exit code: 2", entries[0].body)

    def test_hook_updates_and_duplicate_result_have_one_body(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            observer = TerminalObservation(("claude", "prompt"), root, root / "artifacts", None)
            observer.prepare()
            event = {"session_id": "one", "tool_use_id": "call", "tool_name": "Read",
                     "tool_input": {"file_path": "a.py"}, "tool_response": "File contents"}
            for kind in ("PreToolUse", "PostToolUse", "PostToolUse"):
                observer.consume(dict(event, hook_event_name=kind))
            entries = [e for e in transcript_entries(observer.journal.read_text()) if e.kind == "tool"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Read")
            self.assertEqual(entries[0].body.count("File contents"), 1)

    def test_mcp_identity_and_error_are_preserved(self):
        events = [{"type": "item." + phase, "item": {"id": "mcp1", "type": "mcp_tool_call",
                   "server": "repo", "tool": "read", "arguments": {"path": "a.py"},
                   "error": "Permission denied" if phase == "completed" else None}}
                  for phase in ("started", "completed")]
        entries = transcript_entries("\n".join("\n".join(adapter_event_lines(e, {})) for e in events))
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].title, entries[0].status), ("repo.read", "failed"))

    def test_tool_names_are_not_status_metadata(self):
        entries = transcript_entries("Tool call (running) · inspect_errors_completed\n  Input: {}")
        self.assertEqual(entries[0].status, "running")
        self.assertEqual(transcript_entries("Tool call examples are documented here.")[0].kind, "info")

    def test_completion_receipts_deduplicate_within_operation_only(self):
        events = tuple(SimpleNamespace(kind="completed", operation_id=identity, message="Private details")
                       for identity in ("one", "one", "two"))
        snapshot = SimpleNamespace(run=SimpleNamespace(shell=SimpleNamespace(run=object()),
            agent=SimpleNamespace(agent_output="", has_live_transcript=False)),
            operation=SimpleNamespace(events=events))
        result = run_activity_text(snapshot, include_operation_events=True).plain
        self.assertEqual(result.count("Operation completed."), 2)
        self.assertNotIn("Private details", result)

    def test_completed_artifact_does_not_repeat_live_messages(self):
        value = "Agent message\n  Done."
        snapshot = SimpleNamespace(run=SimpleNamespace(shell=SimpleNamespace(run=object()),
            agent=SimpleNamespace(agent_output=value, has_live_transcript=False)),
            operation=SimpleNamespace(finished=True, events=(
                SimpleNamespace(kind="adapter_output", message="adapter stdout: " + value),)))
        result = run_activity_text(snapshot, include_operation_events=True).plain
        self.assertEqual(result.count("Done."), 1)


class TranscriptApp(App):
    CSS_PATH = str(Path(__file__).resolve().parents[1] / "src/loopforge/cli/textual_app/styles.tcss")

    def compose(self) -> ComposeResult:
        yield RunAgentOutput(id="run-agent-output")


class TranscriptWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_code_and_tool_details_render_in_narrow_run_output(self):
        app = TranscriptApp()
        async with app.run_test(size=(60, 24)) as pilot:
            output = app.query_one(RunAgentOutput)
            partial = "Agent message\n  ~~~rust\n  fn main() {"
            output.update(Text(partial))
            await pilot.pause()
            message = app.query_one(".run-entry-message", Static)
            syntax = message.content.renderables[1]
            self.assertIsInstance(syntax, Syntax)
            self.assertEqual(syntax.lexer.name, "Rust")
            output.update(Text(partial + '\n      println!("hello");\n  }\n  ~~~\n'
                               + codex_call("a", "completed", 'echo "[red]literal[/red]"')))
            await pilot.pause()
            self.assertEqual(len(app.query(".run-entry-message")), 1)
            message = app.query_one(".run-entry-message", Static)
            self.assertIn('println!("hello")', message.content.renderables[1].code)
            tool = app.query_one(RunToolEntry)
            tool.collapsed = False
            await pilot.pause()
            self.assertIn("[red]literal[/red]", tool.detail.content.plain)
            self.assertTrue(tool.detail.content.spans)
            self.assertLessEqual(message.size.width, 60)

    async def test_tool_updates_preserve_expansion_focus_and_literal_details(self):
        app = TranscriptApp()
        async with app.run_test(size=(60, 24)) as pilot:
            output = app.query_one(RunAgentOutput)
            start = codex_call("a", "in_progress", "echo '[red]literal[/red]'")
            output.update(Text(start + "\nAgent message\n  I am checking the result."))
            await pilot.pause()
            tool = app.query_one(RunToolEntry)
            self.assertTrue(tool.collapsed)
            self.assertEqual(tool.size.height, 1)
            title = tool.query_one("CollapsibleTitle")
            title.focus()
            await pilot.press("enter")
            self.assertFalse(tool.collapsed)
            finish = codex_call("a", "completed", "echo '[red]literal[/red]'", "All good")
            output.update(Text(start + "\nAgent message\n  I am checking the result.\n" + finish))
            await pilot.pause()
            self.assertIs(tool, app.query_one(RunToolEntry))
            self.assertIs(app.focused, title)
            self.assertFalse(tool.collapsed)
            self.assertEqual(tool.entry.status, "completed")
            self.assertIn("All good", str(tool.detail.render()))
            self.assertIn("[red]literal[/red]", tool.title.plain)
            self.assertEqual(len(app.query(RunToolEntry)), 1)
            message = app.query_one(".run-entry-message", Static)
            self.assertIn("I am checking", str(message.render()))
            await pilot.press("enter")
            self.assertTrue(tool.collapsed)
            await pilot.click("CollapsibleTitle")
            self.assertFalse(tool.collapsed)

    async def test_unknown_result_stops_spinner_and_ascii_stays_ascii(self):
        with patch.dict("os.environ", {"LOOPFORGE_ASCII": "1"}):
            app = TranscriptApp()
            async with app.run_test(size=(60, 24)) as pilot:
                output = app.query_one(RunAgentOutput)
                value = Text(codex_call("a", "in_progress"))
                output.update(value)
                await pilot.pause()
                tool = app.query_one(RunToolEntry)
                phase = tool.phase
                await pilot.pause(0.2)
                self.assertGreater(tool.phase, phase)
                output.update(value, active=False)
                await pilot.pause()
                phase = tool.phase
                await pilot.pause(0.2)
                self.assertEqual(tool.phase, phase)
                self.assertEqual(tool.entry.status, "unknown")
                self.assertIn("No result received", tool.title.plain)
                self.assertTrue(tool.title.plain.isascii())

    async def test_same_native_id_in_another_run_does_not_inherit_expansion(self):
        app = TranscriptApp()
        async with app.run_test(size=(60, 24)) as pilot:
            output = app.query_one(RunAgentOutput)
            value = Text(codex_call("a", "completed"))
            output.update(value, scope="run-one")
            await pilot.pause()
            first = app.query_one(RunToolEntry)
            first.collapsed = False
            output.update(value, scope="run-two")
            await pilot.pause()
            self.assertIsNot(first, app.query_one(RunToolEntry))
            self.assertTrue(app.query_one(RunToolEntry).collapsed)

    async def test_artifact_refresh_keeps_chronology_without_replacing_tools(self):
        app = TranscriptApp()
        async with app.run_test(size=(60, 24)) as pilot:
            output = app.query_one(RunAgentOutput)
            call = codex_call("a", "completed")
            output.update(Text(call))
            await pilot.pause()
            tool = app.query_one(RunToolEntry)
            output.update(Text("Agent message\n  Earlier explanation.\n" + call))
            self.assertTrue(output.children[0].has_class("run-entry-message"))
            self.assertIs(output.children[1], tool)
            await pilot.pause()
            self.assertIs(tool, app.query_one(RunToolEntry))
            self.assertTrue(output.children[0].has_class("run-entry-message"))
