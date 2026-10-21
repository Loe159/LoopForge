"""Preview declared native file changes in the real LoopForge TUI.

    PYTHONPATH=src .venv/bin/python tools/demo_file_changed.py
"""
from __future__ import annotations

from dataclasses import replace
from difflib import unified_diff
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
        def snapshot_diff(path: str, before: str, after: str, action: str) -> RunFileChange:
            # difflib unified_diff defaults to 3 real context lines.
            patch = "".join(unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile="a/" + path, tofile="b/" + path,
            ))
            return RunFileChange(
                path, action,
                additions=sum(line.startswith("+") and not line.startswith("+++")
                              for line in patch.splitlines()),
                deletions=sum(line.startswith("-") and not line.startswith("---")
                              for line in patch.splitlines()),
                diff=patch,
            )

        changes = RunChangesSnapshot(capture_state="complete",
            source="runner-workspace-snapshots", files=(
                snapshot_diff("src/loopforge/cli/run_presenter.py",
                    "def load_config(path):\n    path = Path(path)\n    if not path.exists():\n"
                    "        return None\n    content = path.read_text()\n"
                    "    config = parse_config(content)\n    return config\n",
                    "def load_config(path):\n    path = Path(path)\n    if not path.exists():\n"
                    "        return default_config()\n    content = path.read_text()\n"
                    "    config = parse_config(content)\n    return config\n", "modified"),
                snapshot_diff("tests/test_run_transcript_ui.py", "",
                    "def test_config():\n    expected = True\n"
                    "    actual = load_config('test')\n    assert actual == expected\n", "added"),
                snapshot_diff("docs/old_notes.md",
                    "# Old notes\nUnused entry\nDeprecated flag\n", "", "deleted"),
            ))
        snap = replace(base, run=replace(base.run,
            agent=replace(base.run.agent, structured_events=declared,
                          event_count=len(declared)), changes=changes))
        self._operation_run_identity = _snapshot_run_identity(snap)
        self._render_snapshot(snap)


if __name__ == "__main__":
    FileChangedDemo().run()
