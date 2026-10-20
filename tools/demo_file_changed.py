"""Preview declared native file changes in the real LoopForge TUI.

    PYTHONPATH=src .venv/bin/python tools/demo_file_changed.py
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.app import _snapshot_run_identity
from loopforge.cli.run_changes import RunChangesSnapshot, RunFileChange

if __package__:
    from .demo_tool_call import demonstration_snapshot
else:
    from demo_tool_call import demonstration_snapshot


class FileChangedDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                         load_on_mount=False)

    def _suspend_run_follow(self):
        self._run_follow_tail = False

    def _change_run_reading(self, **changes):
        # This preview is entirely in memory. Using StateStore.select_reading()
        # would reload an unrelated, empty workspace and lose the demo run.
        if self._screen != "run":
            return
        changes.setdefault("following", False)
        changes.setdefault("scroll_y", 0.0)
        self._run_follow_tail = False
        reading = replace(self._snapshot.run.reading, **changes)
        self._render_snapshot(replace(
            self._snapshot, run=replace(self._snapshot.run, reading=reading),
        ))

    def on_mount(self):
        super().on_mount()
        self._screen = "run"
        base = demonstration_snapshot(self, final=True)
        declared = (
            {"kind": "message", "title": "Agent",
             "body": "I've updated the implementation and associated tests.", "order": 0},
            {"kind": "file_change", "title": "File change", "native_id": "codex-edit-1",
             "status": "completed", "order": 1, "files": [
                 {"path": "src/loopforge/cli/run_presenter.py", "action": "modified"},
                 {"path": "tests/test_run_transcript_ui.py", "action": "added"},
                 {"path": "docs/old_notes.md", "action": "deleted"},
             ]},
            {"kind": "tool", "title": "Shell", "call_id": "unit-tests", "status": "completed",
             "body": "  $ python -m unittest\n  Output\n    OK", "order": 2},
        )
        changes = RunChangesSnapshot(capture_state="complete",
            source="runner-workspace-snapshots", files=(
                RunFileChange("src/loopforge/cli/run_presenter.py", "modified", additions=24, deletions=8),
                RunFileChange("tests/test_run_transcript_ui.py", "added", additions=86, deletions=0),
                RunFileChange("docs/old_notes.md", "deleted", additions=0, deletions=42),
            ))
        snap = replace(base, run=replace(base.run,
            agent=replace(base.run.agent, structured_events=declared,
                          event_count=len(declared)), changes=changes))
        self._operation_run_identity = _snapshot_run_identity(snap)
        self._render_snapshot(snap)


if __name__ == "__main__":
    FileChangedDemo().run()
