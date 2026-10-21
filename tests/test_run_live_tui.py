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

    async def test_file_change_inline_diffs_keyboard_and_context(self):
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
                    rows = list(entry.query(".run-file-change-row"))
                    self.assertEqual(len(rows), 3)
                    self.assertTrue(all(row.collapsed for row in rows))
                    self.assertIn("+1", rows[0].title.plain)
                    self.assertFalse(app.query(".run-file-changes-link"))
                    rows[0].query_one("CollapsibleTitle").focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertFalse(rows[0].collapsed)
                    self.assertTrue(rows[1].collapsed)
                    diff = rows[0].query_one(".run-file-diff-text").render()
                    self.assertIn("   4 -", diff.plain)
                    self.assertIn("   4 +", diff.plain)
                    self.assertIn("   1  ", diff.plain)
                    self.assertIn("   7  ", diff.plain)
                    self.assertNotIn("@@ -", diff.plain)
                    self.assertGreater(len(diff.spans), 20)
                    self.assertEqual(app._snapshot.run.reading.view, "Live")
                    self.assertNotIn("Loading agent output", app._snapshot.run.agent.agent_output)

    async def test_changes_explorer_selects_files_and_preserves_evidence_scope(self):
        from loopforge.cli.textual_app import LoopForgeApp
        from loopforge.cli.textual_app.widgets import RunChangesExplorer
        from loopforge.cli.run_changes import RunChangesSnapshot, RunFileChange
        from loopforge.cli.run_reading import RunReading
        for width in (60, 80, 120, 160):
            with self.subTest(width=width):
                app = LoopForgeApp(
                    SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                    load_on_mount=False)
                async with app.run_test(size=(width, 35)) as pilot:
                    source = synthetic_run(app)
                    changes = RunChangesSnapshot(
                        capture_state="complete", message="Observed execution",
                        source="runner-workspace-snapshots",
                        files=(
                            RunFileChange("src/a.py", "modified", additions=1, deletions=1,
                                diff="--- a/src/a.py\n+++ b/src/a.py\n@@ -1,3 +1,3 @@\n"
                                     " def main():\n-    return False\n+    return True\n pass\n"),
                            RunFileChange("docs/old_notes.md", "deleted",
                                additions=0, deletions=2,
                                diff="--- a/docs/old_notes.md\n+++ /dev/null\n"
                                     "@@ -1,2 +0,0 @@\n-# Old notes\n-Deprecated flag\n"),
                            RunFileChange("logo.bin", "added", binary=True),
                        ),
                    )
                    app._screen = "run"
                    fake = replace(source, run=replace(
                        source.run, reading=RunReading(view="Changes"),
                        changes=changes))
                    app._render_snapshot(fake)
                    await pilot.pause()
                    explorer = app.query_one(RunChangesExplorer)
                    picker = explorer.query_one("#run-changes-file-list")
                    self.assertTrue(explorer.display)
                    self.assertFalse(app.query_one("#run-document-view").display)
                    self.assertEqual(len(picker.options), 5)
                    self.assertEqual(explorer._selected_path, "src/a.py")
                    self.assertIn("return True", explorer.query_one(
                        "#run-changes-diff-text").render().plain)
                    self.assertGreater(explorer.query_one(
                        "#run-changes-preview").size.height, 0)
                    if width <= 80:
                        await pilot.click("#run-changes-tree-toggle")
                        await pilot.pause()
                    picker.focus()
                    picker.highlighted = next(
                        i for i, option in enumerate(picker.options)
                        if option.id == "change-file-1")
                    await pilot.pause()
                    self.assertEqual(explorer._selected_path, "docs/old_notes.md")
                    self.assertIn("Old notes", explorer.query_one(
                        "#run-changes-diff-text").render().plain)
                    # Updating the same retained capture must not reset selection.
                    app._render_snapshot(fake)
                    await pilot.pause()
                    self.assertEqual(explorer._selected_path, "docs/old_notes.md")
                    picker.highlighted = next(
                        i for i, option in enumerate(picker.options)
                        if option.id == "change-file-2")
                    await pilot.pause()
                    self.assertEqual(explorer._selected_path, "logo.bin")
                    self.assertIn("Binary change", explorer.query_one(
                        "#run-changes-diff-text").render().plain)
                    cumulative = replace(changes, scope="run cumulative",
                        source="deterministic-verification-patch", stale=True,
                        message="Earlier verification candidate.",
                        files=(RunFileChange("src/a.py", "modified", additions=2,
                            deletions=0, diff="--- a/src/a.py\n+++ b/src/a.py\n"
                                                "@@ -1,0 +1,2 @@\n+hello\n+world\n"),))
                    # Switch scope: selection and provenance must follow the patch,
                    # never reuse a file from the previous attempt.
                    app._render_snapshot(replace(fake, run=replace(
                        fake.run, reading=RunReading(view="Changes", cumulative=True),
                        changes=cumulative)))
                    await pilot.pause()
                    self.assertEqual(explorer._selected_path, "src/a.py")
                    summary = explorer.query_one("#run-changes-summary").render().plain
                    self.assertIn("Cumulative patch", summary)
                    self.assertIn("STALE", summary)
                    self.assertIn("Earlier verification candidate.", summary)
                    self.assertEqual(len(picker.options), 2)
                    renamed = replace(changes, files=(
                        RunFileChange("src/new_name.py", "renamed",
                            previous_path="src/old_name.py", additions=1, deletions=1,
                            truncated=True, diff="--- a/src/old_name.py\n"
                            "+++ b/src/new_name.py\n@@ -1 +1 @@\n-old\n+new\n"),))
                    app._render_snapshot(replace(fake, run=replace(
                        fake.run, changes=renamed)))
                    await pilot.pause()
                    selected_title = explorer.query_one("#run-changes-file-heading").render().plain
                    self.assertIn("Rename", selected_title)
                    self.assertIn("From: src/old_name.py", selected_title)
                    self.assertIn("truncated", selected_title)
                    self.assertIn("truncated", explorer.query_one(
                        "#run-changes-diff-text").render().plain)

                    empty = replace(changes, capture_state="unavailable", files=(),
                        message="Capture unavailable")
                    app._render_snapshot(replace(fake, run=replace(
                        fake.run, changes=empty)))
                    await pilot.pause()
                    self.assertFalse(picker.options)
                    self.assertIn("Capture unavailable", explorer.query_one(
                        "#run-changes-diff-text").render().plain)

    async def test_changes_explorer_demo_switches_attempt_and_cumulative(self):
        from tools.demo_changes_explorer import ChangesExplorerDemo
        from loopforge.cli.textual_app.widgets import RunChangesExplorer
        app = ChangesExplorerDemo()
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause(0.4)
            explorer = app.query_one(RunChangesExplorer)
            self.assertTrue(explorer.display)
            self.assertEqual(app._snapshot.run.reading.view, "Changes")
            self.assertFalse(app._snapshot.run.reading.cumulative)
            self.assertIn("Workspace capture", explorer.query_one(
                "#run-changes-summary").render().plain)
            await pilot.click("#run-diff-cumulative")
            await pilot.pause()
            self.assertTrue(app._snapshot.run.reading.cumulative)
            self.assertEqual(app._snapshot.run.changes.source,
                             "deterministic-verification-patch")
            self.assertIn("Cumulative patch", explorer.query_one(
                "#run-changes-summary").render().plain)
            await pilot.click("#run-diff-attempt")
            await pilot.pause()
            self.assertFalse(app._snapshot.run.reading.cumulative)
            self.assertEqual(app._snapshot.run.changes.source,
                             "runner-workspace-snapshots")
            self.assertIn("Workspace capture", explorer.query_one(
                "#run-changes-summary").render().plain)

    async def test_changes_tree_and_single_line_controls(self):
        from tools.demo_changes_explorer import ChangesExplorerDemo
        for width in (60, 80, 120, 160):
            with self.subTest(width=width):
                app = ChangesExplorerDemo()
                async with app.run_test(size=(width, 24)) as pilot:
                    await pilot.pause(0.4)
                    explorer = app.query_one("#run-changes-explorer")
                    picker = app.query_one("#run-changes-file-list")
                    options = picker.options
                    folders = [o for o in options if o.id.startswith("change-dir-")]
                    files = [o for o in options if o.id.startswith("change-file-")]
                    self.assertEqual(len(files), 3)
                    self.assertEqual(len(folders), 5)
                    self.assertTrue(all(not o.disabled for o in folders))
                    self.assertTrue(all(not o.disabled for o in files))
                    attempt = app.query_one("#run-diff-attempt").region
                    cumulative = app.query_one("#run-diff-cumulative").region
                    self.assertEqual(attempt.y, cumulative.y)
                    self.assertEqual(attempt.x + attempt.width, cumulative.x)
                    summary = app.query_one("#run-changes-summary").region
                    self.assertGreater(summary.y, attempt.y + attempt.height)
                    preview = app.query_one("#run-changes-preview").region
                    tree = app.query_one("#run-changes-files").region
                    if width <= 80:
                        self.assertGreaterEqual(preview.y, tree.y + tree.height)
                        self.assertGreaterEqual(
                            app.query_one("#run-changes-diff-scroll").size.height, 5)
                        self.assertFalse(explorer._tree_open)
                        self.assertFalse(picker.display)
                        await pilot.click("#run-changes-tree-toggle")
                        await pilot.pause()
                        self.assertTrue(explorer._tree_open)
                        self.assertTrue(picker.display)
                        self.assertFalse(app.query_one("#run-changes-preview").display)
                    else:
                        self.assertEqual(preview.y, tree.y)

                    # Enter and left/right all operate on directory hierarchy.
                    picker.focus()
                    picker.highlighted = 0  # docs/
                    await pilot.pause()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIn(("docs",), explorer._collapsed_directories)
                    self.assertEqual(len(picker.options), 7)
                    self.assertEqual(explorer._selected_path,
                                     "src/loopforge/cli/run_presenter.py")
                    await pilot.press("right")
                    await pilot.pause()
                    self.assertNotIn(("docs",), explorer._collapsed_directories)
                    self.assertEqual(len(picker.options), 8)
                    await pilot.press("left")
                    await pilot.pause()
                    self.assertIn(("docs",), explorer._collapsed_directories)

                    # Nested src/loopforge can collapse independently.
                    picker.highlighted = next(
                        i for i, option in enumerate(picker.options)
                        if explorer._option_directories.get(option.id) == ("src",))
                    await pilot.pause()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIn(("src",), explorer._collapsed_directories)
                    self.assertFalse(any(
                        path == ("src", "loopforge") for path
                        in explorer._option_directories.values()))
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertNotIn(("src",), explorer._collapsed_directories)

                    # In compact mode choosing a file restores the full diff.
                    if width <= 80:
                        picker.highlighted = next(
                            i for i, option in enumerate(picker.options)
                            if option.id == "change-file-0")
                        await pilot.pause()
                        await pilot.press("enter")
                        await pilot.pause()
                        self.assertFalse(explorer._tree_open)
                        self.assertTrue(app.query_one("#run-changes-preview").display)
                        self.assertIn("return default_config",
                                      app.query_one("#run-changes-diff-text").render().plain)

    async def test_changes_tree_mouse_toggle_survives_refresh_and_returns_to_diff(self):
        from tools.demo_changes_explorer import ChangesExplorerDemo
        app = ChangesExplorerDemo()
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause(0.4)
            explorer = app.query_one("#run-changes-explorer")
            self.assertFalse(explorer._tree_open)
            self.assertTrue(app.query_one("#run-command-bar").display)
            await pilot.click("#run-changes-tree-toggle")
            await pilot.pause()
            picker = app.query_one("#run-changes-file-list")
            await pilot.click("#run-changes-file-list", offset=(3, 0))
            await pilot.pause()
            self.assertIn(("docs",), explorer._collapsed_directories)
            self.assertNotIn("change-file-2",
                             {option.id for option in picker.options})
            app._render_snapshot(app._snapshot)
            await pilot.pause()
            self.assertIn(("docs",), explorer._collapsed_directories)
            self.assertTrue(explorer._tree_open)
            await pilot.click("#run-changes-file-list", offset=(3, 0))
            await pilot.pause()
            self.assertNotIn(("docs",), explorer._collapsed_directories)
            # Select the remaining source file and reclaim diff space.
            picker.highlighted = next(
                i for i, option in enumerate(picker.options)
                if option.id == "change-file-0")
            picker.focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(explorer._tree_open)
            self.assertTrue(app.query_one("#run-changes-preview").display)
            self.assertGreaterEqual(
                app.query_one("#run-changes-diff-scroll").size.height, 5)
            self.assertIn("run_presenter.py",
                          app.query_one("#run-changes-tree-toggle").label.plain)
            self.assertTrue(app.query_one("#run-command-bar").display)
            # Navigating back to Live restores the normal compact context.
            app._change_run_reading(view="Live")
            await pilot.pause()
            self.assertTrue(app.query_one("#run-compact-context").display)

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
        from loopforge.cli.textual_app.widgets import RunDocumentView, RunChangesExplorer
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
                explorer = app.query_one(RunChangesExplorer)
                self.assertEqual(view.display, name != "Changes")
                self.assertEqual(explorer.display, name == "Changes")
                self.assertFalse(app.query_one("#run-activity-feed").display)
                if name == "Context":
                    self.assertIn("mission", view._items)
                    self.assertIn("raw", view._items)
                elif name == "Changes":
                    self.assertEqual(explorer._selected_path, "src/a.py")
                    self.assertIn("1 - a", explorer.query_one(
                        "#run-changes-diff-text").render().plain)
                    self.assertFalse(view.display)
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
