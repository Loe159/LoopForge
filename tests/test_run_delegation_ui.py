"""Typed delegation projection and terminal-native disclosure regression tests."""
from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets._collapsible import CollapsibleTitle

from loopforge.adapters.event_store import normalize_event
from loopforge.cli.run_projection import project_events
from loopforge.cli.textual_app.run_presenter import TranscriptEntry
from loopforge.cli.textual_app.widgets import RunAgentOutput, RunDelegationEntry, RunToolEntry


def observed():
    return (
        {"kind": "message", "native_id": "m0", "body": "Starting review", "order": 0},
        {"kind": "delegation", "native_id": "native-p", "call_id": "p", "title": "Security review",
         "body": "Inspect ACL", "status": "running", "order": 1},
        {"kind": "tool", "call_id": "read-a", "parent_id": "native-p", "title": "Read",
         "category": "read", "status": "completed", "order": 2},
        {"kind": "tool", "call_id": "read-b", "parent_id": "native-p", "title": "Read",
         "category": "read", "status": "completed", "order": 3},
        {"kind": "message", "native_id": "other", "body": "Unrelated parent text", "order": 4},
        {"kind": "message", "native_id": "child-message", "parent_id": "native-p",
         "body": "Review [red]literal[/red]", "order": 5},
        {"kind": "tool", "call_id": "fail", "parent_id": "native-p",
         "title": "Shell", "body": "exit 3", "status": "failed", "order": 6},
    )


class DelegationProjectionTests(unittest.TestCase):
    def test_native_relationship_and_focused_nested_read_group(self):
        entries = project_events(observed())
        self.assertEqual(len(entries), 3)
        parent = entries[1]
        self.assertEqual(parent.kind, "delegation")
        self.assertEqual(parent.source_ids, ("p", "native-p"))
        self.assertEqual([child.kind for child in parent.children], ["group", "message", "tool"])
        self.assertEqual(parent.children[0].title, "Read 2 files")
        self.assertEqual(parent.children[-1].status, "failed")
        self.assertEqual(entries[2].body, "Unrelated parent text")
        all_entries = project_events(observed(), mode="All")
        self.assertEqual(len(all_entries), 7)
        self.assertFalse(all_entries[1].children)
        self.assertEqual([entry.kind for entry in all_entries][1:4],
                         ["delegation", "tool", "tool"])

    def test_no_inference_from_text_and_duplicate_native_id(self):
        unlinked = project_events((
            {"kind": "delegation", "call_id": "p", "title": "spawn_agent", "order": 0},
            {"kind": "message", "body": "spawn_agent p says finished", "order": 1},
            {"kind": "tool", "parent_id": "missing", "title": "Read", "order": 2},
        ))
        self.assertFalse(unlinked[0].children)
        self.assertEqual(len(unlinked), 3)
        ambiguous = project_events((
            {"kind": "delegation", "call_id": "p", "native_id": "alias", "order": 0},
            {"kind": "delegation", "call_id": "q", "native_id": "alias", "order": 1},
            {"kind": "message", "parent_id": "alias", "body": "Must stay top level", "order": 2},
        ))
        self.assertEqual(len(ambiguous), 3)
        self.assertFalse(ambiguous[0].children)
        self.assertFalse(ambiguous[1].children)

    def test_concurrency_native_updates_and_unknown_after_close(self):
        events = (
            {"kind": "delegation", "call_id": "p1", "title": "Review", "status": "running", "order": 0},
            {"kind": "delegation", "call_id": "p2", "title": "Review", "status": "running", "order": 1},
            {"kind": "tool", "call_id": "t2", "parent_id": "p2", "title": "Shell", "order": 2},
            {"kind": "tool", "call_id": "t1", "parent_id": "p1", "title": "Read", "order": 3},
            {"kind": "delegation", "call_id": "p1", "title": "Review", "status": "completed", "order": 4},
        )
        items = project_events(events, session_closed=True)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].status, "completed")
        self.assertEqual(items[1].status, "unknown")
        self.assertEqual(items[0].children[0].key, "tool:t1")
        self.assertEqual(items[1].children[0].key, "tool:t2")
        self.assertEqual(items[0].children[0].status, "unknown")

    def test_nested_derived_relation_and_cycle_do_not_drop_events(self):
        nested = project_events((
            {"kind": "delegation", "call_id": "a", "title": "Primary", "order": 0},
            {"kind": "delegation", "call_id": "b", "parent_id": "a", "title": "Secondary", "order": 1},
            {"kind": "message", "parent_id": "b", "body": "Done", "order": 2},
        ))
        self.assertEqual(len(nested), 1)
        self.assertEqual(nested[0].children[0].children[0].body, "Done")
        cyclic = project_events((
            {"kind": "delegation", "call_id": "a", "parent_id": "b", "order": 0},
            {"kind": "delegation", "call_id": "b", "parent_id": "a", "order": 1},
        ))
        self.assertTrue(cyclic)
        self.assertEqual(len(cyclic), 1)
        self.assertEqual(cyclic[0].children[0].kind, "delegation")

    def test_native_codex_collaboration_and_part_parent_id(self):
        start, = normalize_event({"type": "item.started", "item": {
            "type": "collab_tool_call", "id": "agent-p", "tool": "spawn_agent",
            "prompt": "Review ACL", "status": "in_progress",
        }})
        self.assertEqual(start["kind"], "delegation")
        self.assertEqual(start["body"], "Review ACL")
        child, = normalize_event({"type": "message.part.updated", "part": {
            "type": "text", "id": "child-1", "parentID": "agent-p",
            "text": "Native child event",
        }})
        self.assertEqual(child["parent_id"], "agent-p")
        self.assertIn("Native child event", project_events((start, child))[0].children[0].body)

    def test_claude_task_start_result_joins_native_call_id(self):
        start, = normalize_event({"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Task", "id": "task-1", "input": {"prompt": "Review"},
        }]}})
        result, = normalize_event({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": "task-1", "content": "Done",
        }]}})
        entries = project_events((start, result))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, "delegation")
        self.assertEqual(entries[0].status, "completed")


class DelegationApp(App):
    CSS_PATH = str(Path(__file__).resolve().parents[1] / "src/loopforge/cli/textual_app/styles.tcss")
    def compose(self) -> ComposeResult:
        yield RunAgentOutput(id="run-agent-output")


class DelegationWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_disclosure_keyboard_mouse_updates_and_scope(self):
        app = DelegationApp()
        events = observed()
        async with app.run_test(size=(80, 30)) as pilot:
            output = app.query_one(RunAgentOutput)
            output.update(Text(""), scope="attempt-1", entries=project_events(events))
            await pilot.pause()
            parent = app.query_one(RunDelegationEntry)
            self.assertTrue(parent.collapsed)
            title = parent.query_one(CollapsibleTitle)
            title.focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(parent.collapsed)
            self.assertIs(app.focused, title)
            self.assertEqual(len(parent.query(RunToolEntry)), 2)  # group + failed tool
            self.assertIn("[red]literal",
                          parent.query_one(".run-delegation-message").content.renderables[1].markup)
            updated = tuple(dict(e) for e in events)
            updated[1]["status"] = "completed"
            output.update(Text(""), scope="attempt-1", entries=project_events(updated))
            await pilot.pause()
            self.assertIs(app.query_one(RunDelegationEntry), parent)
            self.assertFalse(parent.collapsed)
            self.assertIs(app.focused, title)
            self.assertIn("Completed", parent.title.plain)
            await pilot.click(title)
            await pilot.pause()
            self.assertTrue(parent.collapsed)
            output.update(Text(""), scope="attempt-2", entries=project_events(updated))
            await pilot.pause()
            self.assertIsNot(app.query_one(RunDelegationEntry), parent)
            self.assertTrue(app.query_one(RunDelegationEntry).collapsed)

    async def test_compact_unlinked_ascii_and_narrow_width(self):
        from unittest.mock import patch
        entry = TranscriptEntry("d:1", "delegation", "Review permissions and security boundaries",
                                "Native arguments [red]literal[/red]", "unknown")
        with patch.dict("os.environ", {"LOOPFORGE_ASCII": "1"}):
            app = DelegationApp()
            async with app.run_test(size=(52, 24)) as pilot:
                output = app.query_one(RunAgentOutput)
                output.update(Text(""), entries=(entry,), scope="ascii")
                await pilot.pause()
                parent = app.query_one(RunDelegationEntry)
                self.assertIn("Delegation", parent.title.plain)
                self.assertIn("Unknown", parent.title.plain)
                self.assertFalse(parent.entry.children)
                self.assertLessEqual(parent.size.width, 52)
                parent.query_one(CollapsibleTitle).focus()
                await pilot.press("enter")
                await pilot.pause()
                self.assertIn("[red]literal[/red]", parent.detail.content.renderables[1].plain)


class DelegationFocusContrastTests(unittest.IsolatedAsyncioTestCase):
    async def test_lavender_focus_restyles_every_rich_text_span_and_blur_restores_it(self):
        from rich.console import Console
        from rich.text import Text

        def rgb(label: Text, offset: int) -> tuple[int, int, int]:
            color = label.get_style_at_offset(Console(), offset).color
            assert color is not None and color.triplet is not None
            return tuple(color.triplet)

        for width in (52, 80, 120):
            with self.subTest(width=width):
                app = DelegationApp()
                child = TranscriptEntry("failed-tool", "tool", "Shell", "exit 1", "failed")
                entry = TranscriptEntry("delegate", "delegation", "Security review", "", "running",
                                        children=(child,))
                other = TranscriptEntry("other", "delegation", "Other task", "", "unknown")
                async with app.run_test(size=(width, 25)) as pilot:
                    output = app.query_one(RunAgentOutput)
                    output.update(Text(""), entries=(entry, other), scope="focus-case")
                    await pilot.pause()
                    first, second = list(app.query(RunDelegationEntry))
                    self.assertEqual(rgb(first.title, 0), (231, 224, 237))
                    self.assertEqual(rgb(first.title, first.title.plain.index("Running")), (208, 188, 255))
                    title = first.query_one(CollapsibleTitle)
                    title.focus()
                    await pilot.pause()
                    self.assertIs(app.focused, title)
                    self.assertEqual(rgb(first.title, 0), (10, 10, 10))
                    self.assertEqual(rgb(first.title, first.title.plain.index("Running")), (36, 27, 53))
                    self.assertEqual(rgb(first.title, first.title.plain.index("Child error")), (116, 42, 36))
                    self.assertEqual(title.styles.background.rgb, (208, 188, 255))
                    for status, expected in (("completed", (32, 83, 43)),
                                             ("failed", (116, 42, 36)),
                                             ("unknown", (63, 56, 72)),
                                             ("running", (36, 27, 53))):
                        output.update(Text(""), scope="focus-case", entries=(
                            replace(entry, status=status), other))
                        await pilot.pause()
                        self.assertIs(app.focused, title)
                        self.assertEqual(rgb(first.title, 0), (10, 10, 10))
                        self.assertEqual(rgb(first.title, first.title.plain.index(status.title())), expected)
                    second.query_one(CollapsibleTitle).focus()
                    await pilot.pause()
                    self.assertEqual(rgb(first.title, 0), (231, 224, 237))
                    self.assertEqual(rgb(first.title, first.title.plain.index("Running")), (208, 188, 255))
                    self.assertEqual(rgb(second.title, 0), (10, 10, 10))


class RealRunDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_run_keyboard_escape_follow_and_responsive(self):
        from tools.demo_sub_agent import SubAgentDemo
        for width, height in ((48, 24), (52, 24), (60, 24), (80, 30),
                              (100, 30), (120, 35), (160, 35)):
            with self.subTest(terminal=(width, height)):
                app = SubAgentDemo()
                async with app.run_test(size=(width, height)) as pilot:
                    await pilot.pause()
                    entry = app.query(RunDelegationEntry).first()
                    self.assertEqual(app._screen, "run")
                    self.assertTrue(entry.collapsed)
                    self.assertEqual(entry.entry.status, "running")
                    self.assertIn("Running", entry.title.plain)
                    self.assertLessEqual(entry.size.width, width)
                    title = entry.query_one(CollapsibleTitle)
                    title.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertFalse(entry.collapsed)
                    self.assertFalse(app._run_follow_tail)
                    self.assertIs(app.focused, title)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertTrue(entry.collapsed)
                    self.assertEqual(app._screen, "run")
                    self.assertIs(app.focused, title)
                    await pilot.click(title)
                    await pilot.pause()
                    self.assertFalse(entry.collapsed)
                    self.assertTrue(app.query_one("#run-command-bar").display)
                    # Only one focus-owning entry; sidebar stays within the run.
                    self.assertLessEqual(entry.region.right, width)
