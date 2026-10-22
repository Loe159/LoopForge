"""The selected single-page task composer; persistence stays in the shared shell."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Button, Static, TextArea

from loopforge.cli.task_intake import TaskContext, TaskDraft, load_task_context
from loopforge.cli.textual_app.screens import ConfirmationScreen
from loopforge.cli.textual_app.run_presenter import ascii_only
from loopforge.engine import task_looks_subjective, validate_task_definition


def _chrome(text: str) -> str:
    return text.replace("·", "-").replace("…", "...") if ascii_only() else text


class CriterionField(Vertical):
    def __init__(self, number: int, *, removable: bool = True) -> None:
        super().__init__(id=f"criterion-{number}", classes="task-criterion")
        self.number, self.removable = number, removable

    def compose(self) -> ComposeResult:
        area = TextArea(id=f"criterion-value-{self.number}", classes="criterion-value",
                        placeholder="Describe one observable result.")
        area.border_title = f"Criterion {self.number}"
        yield area
        if self.removable:
            with Horizontal(classes="criterion-actions"):
                yield Button("Remove", id=f"criterion-remove-{self.number}", classes="criterion-remove")


class TaskComposer(Screen[str | None]):
    """Retains a draft through validation, asynchronous creation and recoverable errors."""

    BINDINGS = [
        Binding("escape", "leave", "Back", priority=True),
        Binding("ctrl+q", "leave", "Back", priority=True),
        Binding("ctrl+enter", "submit", "Create run", priority=True),
    ]
    CSS_PATH = str(Path(__file__).with_name("task_composer.tcss"))

    def __init__(self, project: Path, *, complete: bool = False, run_id: str | None = None) -> None:
        super().__init__()
        self.project = project
        self.complete = complete
        self.expected_run_id = run_id
        self.context: TaskContext | None = None
        self.busy = False
        self.context_changed = False
        self._next_criterion = 1
        self._initial = TaskDraft("")
        self._failure = ""

    @property
    def title_text(self) -> str:
        return "Complete task contract" if self.complete else "New run / Task"

    def compose(self) -> ComposeResult:
        yield Static("LoopForge", id="task-brand")
        yield Static(self.title_text, id="task-title")
        yield Static(Text(f"Project  {self.project.name}" + _chrome(" · ") + str(self.project)), id="task-project")
        yield Static(_chrome("Loading project values…"), id="task-defaults")
        with Horizontal(id="task-workspace"):
            with VerticalScroll(id="task-form-scroll"):
                task = TextArea(id="task-description", placeholder="Describe the change and its scope.",
                                read_only=self.complete)
                task.border_title = _chrome("Task · recorded" if self.complete else "Task · required")
                yield task
                yield Static("SUCCESS CRITERIA", id="task-criteria-title")
                yield Static("What observable result will show that this is done?", id="task-criteria-help")
                with Vertical(id="task-criteria"):
                    yield CriterionField(1, removable=not self.complete)
                if not self.complete:
                    yield Button("Add criterion", id="task-add-criterion")
                with Vertical(id="task-rubric-group"):
                    yield Static("Evaluation rubric required for this task and profile.", id="task-rubric-help")
                    rubric = TextArea(id="task-rubric")
                    rubric.border_title = _chrome("Evaluation rubric · required")
                    yield rubric
            yield Static("", id="task-context-details", markup=False)
        yield Static("", id="task-feedback", markup=False)
        with Vertical(id="task-actions"):
            yield Static(_chrome("Loading project context…"), id="task-status", markup=False)
            with Horizontal(id="task-buttons"):
                yield Button("Save criterion" if self.complete else "Create run", id="task-submit", disabled=True)
                yield Button("Back", id="task-back")
                yield Button("Recheck project", id="task-recheck")
            yield Static(_chrome("Tab Fields · Enter New line · Esc Back · Ctrl+Enter Submit"), id="task-hotkeys")

    def on_mount(self) -> None:
        self._resize(self.size.width, self.size.height)
        self.load_context()

    def on_resize(self, event: Resize) -> None:
        self._resize(event.size.width, event.size.height)

    def _resize(self, width: int, height: int) -> None:
        self.set_class(width < 110, "compact")
        self.set_class(height <= 26, "short")
        if self.is_mounted:
            self._update_validation()

    @work(thread=True, exclusive=True, group="task-context", exit_on_error=False)
    def load_context(self) -> None:
        try:
            context = load_task_context(self.project)
        except Exception as error:
            self.app.call_from_thread(self.context_failed, str(error))
        else:
            self.app.call_from_thread(self.apply_context, context)

    def apply_context(self, context: TaskContext) -> None:
        if not self.is_mounted:
            return
        if self.complete and context.scope.run_id != self.expected_run_id:
            self.context_failed("The current run changed. Return to the run and open Task again.")
            return
        initial = self.context is None
        self.context = context
        self.context_changed = False
        self.query_one("#task-project", Static).update(Text(
            f"Project  {context.project_name}" + _chrome(" · ") + str(context.scope.project_path)))
        self.query_one("#task-defaults", Static).update(Text(
            _chrome(" · ").join((context.pack, context.profile, context.adapter))))
        self.query_one("#task-context-details", Static).update(Text(
            f"PROJECT DEFAULTS\n\nPack     {context.pack}\nProfile  {context.profile}"
            f"\nAdapter  {context.adapter}\n\n\nAFTER {'COMPLETION' if self.complete else 'CREATION'}"
            "\n\nReview the task and criteria.\nApprove the task explicitly."
            "\nResearch is a later action.\n\n\nCriteria describe success.\nThey are not test results."
            + ("" if self.complete else "\n\n\nDraft kept in this session.\nNothing saved yet.")))
        if initial and self.complete:
            self.query_one("#task-description", TextArea).load_text(context.task)
            self._initial = self.draft()
        self._failure = ""
        self._update_validation()
        if initial:
            self.query_one("#criterion-value-1" if self.complete else "#task-description").focus()

    def context_failed(self, message: str) -> None:
        if self.is_mounted:
            self.context_changed = True
            self._failure = message
            self._update_validation()

    def draft(self) -> TaskDraft:
        return TaskDraft(
            self.query_one("#task-description", TextArea).text,
            tuple(area.text for area in self.query(".criterion-value").results(TextArea) if area.text.strip()),
            self.query_one("#task-rubric", TextArea).text,
        )

    @on(TextArea.Changed)
    def _text_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        self._update_validation()

    def _update_validation(self) -> None:
        if not self.is_mounted:
            return
        draft = self.draft()
        context = self.context
        needs_rubric = False
        if context:
            validation = validate_task_definition(
                task=draft.task, success_checks=list(draft.success_checks), profile=context.profile,
                subjective=task_looks_subjective(draft.task), subjective_rubric="",
            )
            needs_rubric = "subjective rubric" in validation["missing"]
        self.query_one("#task-rubric-group").display = needs_rubric and not self.complete
        missing_old_rubric = self.complete and context and "subjective rubric" in context.missing
        valid = bool(context and not self.context_changed and draft.task.strip()
                     and (not self.complete or draft.success_checks)
                     and (not needs_rubric or draft.rubric.strip() or self.complete)
                     and not missing_old_rubric)
        self.query_one("#task-submit", Button).disabled = self.busy or not valid
        self.query_one("#task-submit", Button).label = _chrome(
            ("Saving…" if self.complete else "Creating…") if self.busy else
            ("Save criterion" if self.complete else "Create run"))
        for area in self.query(TextArea):
            area.read_only = self.busy or (self.complete and area.id == "task-description")
        for button in self.query(".criterion-remove, #task-add-criterion").results(Button):
            button.disabled = self.busy
        self.query_one("#task-back", Button).disabled = self.busy
        self.query_one("#task-recheck", Button).display = self.context_changed
        self.query_one("#task-recheck", Button).disabled = self.busy
        if self.busy:
            status = "Saving criterion…" if self.complete else "Creating run…"
        elif not context:
            status = "Load the project context before submitting."
        elif missing_old_rubric:
            status = "This saved task also needs a rubric. Adding a criterion cannot complete it."
        elif self.complete:
            status = "Adds a criterion to this run. Task approval follows."
        elif not draft.task.strip():
            status = "Add a task to create a run."
        elif needs_rubric and not draft.rubric.strip():
            status = "Add an evaluation rubric before creating this task."
        elif not draft.success_checks:
            status = "No criteria yet: complete Task before approval."
        else:
            status = "Creates a run. Review and approval follow in Task."
        if context and context.scope.run_id and not self.complete and not self.busy:
            status += " The new run becomes current; the previous run is kept."
        self.query_one("#task-status", Static).update(Text(_chrome(status)))
        feedback = self.query_one("#task-feedback", Static)
        feedback.update(Text(self._failure))
        feedback.display = bool(self._failure)
        count = len(draft.success_checks)
        unit = "criterion" if count == 1 else "criteria"
        hint = (f"{count} {unit} · Tab fields below · Esc Back" if self.has_class("short") else
                "Tab Fields · Enter New line · Esc Back · Ctrl+Enter Submit")
        self.query_one("#task-hotkeys", Static).update(_chrome(hint))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        identity = event.button.id or ""
        if identity == "task-submit":
            self.action_submit()
        elif identity == "task-back":
            self.action_leave()
        elif identity == "task-recheck" and not self.busy:
            self.load_context()
        elif identity == "task-add-criterion" and not self.busy:
            self._next_criterion += 1
            field = CriterionField(self._next_criterion)
            await self.query_one("#task-criteria").mount(field)
            field.query_one(TextArea).focus()
        elif identity.startswith("criterion-remove-") and not self.busy:
            fields = list(self.query(CriterionField))
            field = getattr(event.button.parent, "parent", None)
            if field not in fields:
                return  # A second queued click may outlive the removed row.
            index = fields.index(field)
            await field.remove()
            remaining = list(self.query(CriterionField))
            if remaining:
                remaining[min(index, len(remaining)-1)].query_one(TextArea).focus()
            else:
                self.query_one("#task-add-criterion").focus()
            self._update_validation()

    def action_submit(self) -> None:
        if self.app.screen is not self or self.query_one("#task-submit", Button).disabled:
            return
        self.busy = True
        self._failure = ""
        self._update_validation()
        self.app.submit_task_draft(self, self.draft())

    def show_failure(self, message: str, *, changed: bool = False) -> None:
        self.busy = False
        self.context_changed = changed
        self._failure = message
        self._update_validation()

    def action_leave(self) -> None:
        if self.busy or self.app.screen is not self:
            return
        if self.draft() == self._initial:
            self.dismiss(None)
            return
        screen = ConfirmationScreen(
            "Leave this unsaved task?",
            ("Your text is kept only in this session.", "Leaving now discards this draft."),
            approve_label="Discard draft", cancel_label="Keep editing", focus_cancel=True,
        )
        screen.add_class("task-discard")
        self.app.push_screen(screen, lambda discard: self.dismiss(None) if discard else None)
