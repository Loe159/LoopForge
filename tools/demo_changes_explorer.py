"""Preview the Changes explorer using synthetic evidence (no workspace writes).

    PYTHONPATH=src .venv/bin/python tools/demo_changes_explorer.py

Left pane: choose a file with arrows or mouse.
Top toggle: Attempt / Run cumulative.
"""
from __future__ import annotations

from dataclasses import replace

if __package__:
    from .demo_file_changed import FileChangedDemo
else:
    from demo_file_changed import FileChangedDemo


class ChangesExplorerDemo(FileChangedDemo):
    def on_mount(self) -> None:
        super().on_mount()
        self._attempt_changes = replace(
            self._snapshot.run.changes,
            message="Synthetic workspace snapshots for the UI preview.",
        )
        self._cumulative_changes = replace(
            self._attempt_changes,
            scope="run cumulative",
            source="deterministic-verification-patch",
            message="Synthetic retained cumulative patch for the UI preview.",
        )
        # Initial StateStore publications can replay the default Live reading
        # just after on_mount; switch after the startup queue is drained.
        self.set_timer(0.2, lambda: self._change_run_reading(view="Changes"))

    def _change_run_reading(self, **changes):
        if hasattr(self, "_attempt_changes"):
            cumulative = changes.get("cumulative", self._snapshot.run.reading.cumulative)
            proof = self._cumulative_changes if cumulative else self._attempt_changes
            self._snapshot = replace(
                self._snapshot, run=replace(self._snapshot.run, changes=proof))
        super()._change_run_reading(**changes)


if __name__ == "__main__":
    ChangesExplorerDemo().run()
