"""Read-only native fixture for the selected New Run / Task composition.

PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py --state filled
The fixture never creates a run or executes an approval.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.models import RunSnapshot
from loopforge.cli.presentation import ProjectSummary, RunSummary, ShellSnapshot, StageView
from loopforge.cli.task_intake import TaskContext
from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.screens import RunDetailScreen
from loopforge.cli.textual_app.task_composer import CriterionField, TaskComposer
from loopforge.engine import ActionScope


class ComposerPreview(TaskComposer):
    def __init__(self, state: str) -> None:
        self.preview_state = state
        super().__init__(Path.cwd(), complete=state == "complete", run_id="task-demo" if state == "complete" else None)

    def load_context(self) -> None:
        self.call_after_refresh(self._populate)

    async def _populate(self) -> None:
        self.apply_context(TaskContext(
            ActionScope("synthetic-project", Path.cwd(), "task-demo" if self.complete else None,
                        0, config_revision=0),
            "AUTH DEMO", "autonomous" if self.preview_state == "rubric" else "supervised",
            "generic-code", "codex", task="Reject expired tokens in the API." if self.complete else "",
        ))
        if self.preview_state != "empty":
            self.query_one("#task-description").load_text(
                "Improve the readability of settings." if self.preview_state == "rubric" else
                "Reject expired tokens in the API.\nKeep valid tokens working and cover expiry boundaries.")
            self.query_one("#criterion-value-1").load_text("Expired tokens return HTTP 401.")
        if self.preview_state == "rubric":
            self.query_one("#task-rubric").load_text("Compare hierarchy, keyboard focus and error recovery.")
        if not self.complete and self.preview_state != "empty":
            self._next_criterion = 2
            await self.query_one("#task-criteria").mount(CriterionField(2))
            self.query_one("#criterion-value-2").load_text("Valid tokens still return HTTP 200.")
        if self.preview_state == "error":
            self.show_failure("Could not write project metadata. Check local access, then retry.")
        if self.preview_state == "saving":
            self.busy = True
        self._update_validation()
        if self.preview_state == "rubric":
            self.query_one("#task-rubric").focus()
        if self.preview_state == "discard":
            self.call_after_refresh(self.action_leave)


class TaskCompositionDemo(LoopForgeApp):
    def __init__(self, state="filled"):
        self.preview_state = state
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"), load_on_mount=False)

    def on_mount(self):
        super().on_mount()
        if self.preview_state == "task":
            action = ActionDescriptor("approve-task", "Review and approve task", "Review the recorded task.",
                                      "low", True, True, "/do approve-task", "approve-task")
            project = ProjectSummary("AUTH DEMO", Path.cwd(), True, "supervised", "generic-code")
            run = RunSummary("task-demo", "task-demo", "Reject expired tokens in the API.",
                             "task_draft", "needs_human", "task", "human", False, action)
            stages = tuple(StageView(key, title, "human" if key=="task" else "engine",
                                     "draft" if key=="task" else "pending",
                                     "needs_human" if key=="task" else "waiting",
                                     "◆" if key=="task" else "○", title, None)
                           for key,title in (("task","Task"),("research","Research"),("plan","Planning"),
                                             ("implementation","Implementation"),("verification","Verification"),("review","Review")))
            shell = ShellSnapshot(project, run, stages, (action,), (), "ready", "needs_human")
            self._screen = "run"
            self._render_snapshot(replace(self.snapshot, selected_run_id="task-demo",
                project=replace(self.snapshot.project, shell=shell, branch="fix/auth"),
                run=RunSnapshot("ready", shell=shell,
                                success_checks=("Expired tokens return HTTP 401.", "Valid tokens still return HTTP 200."))))
        else:
            self.push_screen(ComposerPreview(self.preview_state))

    def submit_task_draft(self, screen, draft):
        screen.busy = False
        screen._update_validation()
        self.push_screen(RunDetailScreen("Read-only demonstration", "Synthetic preview. No run or engine approval is created."))

    def request_action(self, action):
        self.push_screen(RunDetailScreen("Read-only demonstration", action.label + "\nNo engine approval is recorded."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=("empty", "filled", "rubric", "complete", "error", "saving", "discard", "task"), default="filled")
    TaskCompositionDemo(parser.parse_args().state).run()
