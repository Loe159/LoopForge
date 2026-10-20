"""Synthetic Textual pilot exercise of the new read-only run cockpit."""
from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.models import RunAgentSnapshot, RunSnapshot
from loopforge.cli.presentation import ProjectSummary, RunSummary, ShellSnapshot, StageView


def synthetic_run(app):
    project = ProjectSummary("test-project", Path.cwd(), True, "supervised", "default")
    running = RunSummary("r1", "r1", "Inspect run observation", "running", "running",
                         "research", "engine", False, None)
    stages = (StageView("research", "Research repository", "agent", "active",
                        "running", "●", "Research", "read_only"),)
    shell = ShellSnapshot(project, running, stages, (), (), "ready", "running")
    agent = RunAgentSnapshot(adapter="codex", stage_id="research",
             session_id="artifacts/stages/research", session_dir="artifacts/stages/research",
             structured_events=(
                 {"kind": "message", "title": "Agent", "body": "Inspecting code.", "order": 0},
                 {"kind": "tool", "title": "Read", "call_id": "read-1", "body": "README.md",
                  "status": "completed", "category": "read", "order": 1},
             ), event_count=2)
    return replace(app.snapshot, selected_run_id="r1",
                   run=RunSnapshot(state="ready", shell=shell, agent=agent,
                                   sessions=({"stage_id": "research", "session_id": "artifacts/stages/research",
                                              "label": "Session 01"},)),
                   project=replace(app.snapshot.project, state="ready", shell=shell, branch="master"))


class CockpitPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_wide_context_pinned_and_structured_live_feed(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import RunAgentOutput
        shell = SimpleNamespace(project_dir=Path.cwd(), theme="dark")
        app = LoopForgeApp(shell, load_on_mount=False)
        async with app.run_test(size=(160, 36)) as pilot:
            fake = synthetic_run(app)
            app._screen = "run"
            app._render_snapshot(fake)
            await pilot.pause()
            self.assertTrue(app.query_one("#run-context").display)
            self.assertTrue(app.query_one("#run-view-tabs").display)
            self.assertTrue(app.query_one("#run-command-bar").display)
            self.assertEqual(app.query_one("#run-session-select").value,
                             "artifacts/stages/research")
            self.assertEqual(len(app.query_one(RunAgentOutput)._entries), 2)
            self.assertTrue(app.query_one("#run-activity-feed").display)
            self.assertFalse(app.query_one("#run-document-view").display)

    async def test_live_feed_variant_a_has_no_outer_frame(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import RunToolEntry

        for width in (60, 80, 120, 160):
            with self.subTest(columns=width):
                app = LoopForgeApp(
                    SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                    load_on_mount=False,
                )
                async with app.run_test(size=(width, 30)) as pilot:
                    app._screen = "run"
                    app._render_snapshot(synthetic_run(app))
                    await pilot.pause()
                    panel = app.query_one("#run-agent-output-panel")
                    self.assertFalse(panel.styles.border)
                    self.assertEqual(panel.styles.padding.left, 0)
                    self.assertEqual(panel.styles.padding.right, 0)
                    agent = app.query_one(".run-entry-message")
                    tool = app.query_one(RunToolEntry)
                    self.assertEqual(agent.styles.border.left[0], "solid")
                    self.assertEqual(
                        tool.query_one(".run-tool-content").styles.border.left[0], "solid"
                    )
                    self.assertTrue(app.query_one("#run-activity-feed").display)

    async def test_file_change_group_expands_and_opens_changes(self):
        from tools.demo_file_changed import FileChangedDemo
        from loopforge.cli.textual_app.widgets import RunFileChangeEntry
        for width in (60, 80, 120, 160):
            with self.subTest(columns=width):
                app = FileChangedDemo()
                async with app.run_test(size=(width, 35)) as pilot:
                    await pilot.pause()
                    entry = app.query_one(RunFileChangeEntry)
                    self.assertTrue(entry.collapsed)
                    entry.query_one("CollapsibleTitle").focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertFalse(entry.collapsed)
                    self.assertEqual(len(entry.query(".run-file-change-row")), 3)
                    self.assertEqual(
                        [s.render().plain for s in entry.query(".run-file-change-stats")],
                        ["+24  -8", "+86  -0", "+0  -42"],
                    )
                    await pilot.click(".run-file-changes-link")
                    await pilot.pause()
                    self.assertEqual(app._snapshot.run.reading.view, "Changes")

    async def test_compact_supervision_overlay_and_escape(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.screens import RunSupervisionScreen
        shell = SimpleNamespace(project_dir=Path.cwd(), theme="dark")
        app = LoopForgeApp(shell, load_on_mount=False)
        async with app.run_test(size=(60, 24)) as pilot:
            app._screen = "run"
            app._render_snapshot(synthetic_run(app))
            await pilot.pause()
            self.assertFalse(app.query_one("#run-context").display)
            self.assertTrue(app.query_one("#run-compact-tabs").display)
            await pilot.press("f6")
            await pilot.pause()
            self.assertIsInstance(app.screen, RunSupervisionScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, RunSupervisionScreen)

    async def test_context_changes_evidence_views_do_not_mix_details(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.run_reading import RunReading
        from loopforge.cli.run_context import RunContextSection, RunContextSnapshot
        from loopforge.cli.run_changes import RunChangesSnapshot, RunFileChange
        from loopforge.cli.run_evidences import RunEvidencesSnapshot, RunEvidenceSection
        from loopforge.cli.textual_app.widgets import RunDocumentView
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                           load_on_mount=False)
        async with app.run_test(size=(120, 28)) as pilot:
            app._screen = "run"
            source = synthetic_run(app)
            context = RunContextSnapshot(
                sections=(RunContextSection("mission", "Mission", "Fix tests",
                                            source="captured prompt", authority="declared-in-prompt"),),
                raw_prompt="## Objective\nFix tests", capture_state="complete", hash_valid=True)
            changes = RunChangesSnapshot(capture_state="complete",
                files=(RunFileChange(path="src/a.py", status="modified",
                                     additions=1, deletions=1, diff="@@ -1 +1 @@\n-a\n+b"),),
                source="runner-workspace-snapshots", message="Observed")
            evidence = RunEvidencesSnapshot((RunEvidenceSection("checks", "Tests & verification",
                                         "Passed: 2", True),))
            for name, payload in (("Context", {"context": context}),
                                  ("Changes", {"changes": changes}),
                                  ("Evidences", {"evidences": evidence})):
                fake = replace(source, run=replace(source.run,
                    reading=RunReading(view=name), **payload))
                app._render_snapshot(fake)
                await pilot.pause()
                view = app.query_one("#run-document-view", RunDocumentView)
                self.assertTrue(view.display)
                self.assertFalse(app.query_one("#run-activity-feed").display)
                self.assertGreaterEqual(len(view._items), 1, name)
                if name == "Context":
                    self.assertIn("mission", view._items)
                    self.assertIn("raw", view._items)
                elif name == "Changes":
                    self.assertIn("change-0", view._items)
                    self.assertNotIn("mission", view._items)
                else:
                    self.assertIn("checks", view._items)
                    self.assertNotIn("change-0", view._items)
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            self.assertFalse(app.query_one("#run-context").display)
            await pilot.resize_terminal(160, 35)
            await pilot.pause()
            self.assertTrue(app.query_one("#run-context").display)

    async def test_action_banner_and_command_input_are_both_visible(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from dataclasses import replace
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                           load_on_mount=False)
        async with app.run_test(size=(120, 24)) as pilot:
            app._screen = "run"
            fake = synthetic_run(app)
            action = SimpleNamespace(label="Approve task", description="Human approval required")
            active_run = replace(fake.run.shell.run, next_action=action)
            shell = replace(fake.run.shell, run=active_run, family="needs_human")
            fake = replace(fake, run=replace(fake.run, shell=shell))
            app._render_snapshot(fake)
            await pilot.pause()
            self.assertTrue(app.query_one("#run-required-action").display)
            self.assertTrue(app.query_one("#run-command-bar").display)
            self.assertIn("Approval", str(app.query_one("#run-action-title").render()))
