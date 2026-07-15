"""Small recoverable screens used by the Textual application shell."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class RecoverableErrorScreen(ModalScreen[None]):
    """An error boundary that lets the operator return to the last snapshot."""

    BINDINGS = [Binding("escape", "dismiss_error", "Back")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Container(id="error-dialog"):
            yield Static("Something went wrong", classes="error-title")
            yield Static(self.message or "Unknown interactive error.", id="error-message")
            yield Button("Return to LoopForge", variant="primary", id="dismiss-error")

    def action_dismiss_error(self) -> None:
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dismiss-error":
            self.dismiss()


class ConfirmationScreen(ModalScreen[bool]):
    """Keyboard-safe approval dialog with the recorded decision evidence."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, lines: tuple[str, ...], *, approve_label: str = "Approve") -> None:
        super().__init__()
        self.title_text = title
        self.lines = lines
        self.approve_label = approve_label

    def compose(self) -> ComposeResult:
        with Container(id="confirmation-dialog"):
            yield Static(self.title_text, classes="dialog-title")
            yield Static("\n".join(self.lines), id="confirmation-evidence")
            yield Button(self.approve_label, variant="primary", id="confirm-approve")
            yield Button("Cancel", id="confirm-cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-approve")


class TextEntryScreen(ModalScreen[str | None]):
    """Small focus-trapped text entry dialog used for filters and new runs."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, prompt: str, *, value: str = "", submit_label: str = "Apply") -> None:
        super().__init__()
        self.title_text = title
        self.prompt = prompt
        self.value = value
        self.submit_label = submit_label

    def compose(self) -> ComposeResult:
        with Container(id="entry-dialog"):
            yield Static(self.title_text, classes="dialog-title")
            yield Static(self.prompt, classes="secondary")
            yield Input(value=self.value, id="entry-value")
            yield Button(self.submit_label, variant="primary", id="entry-submit")
            yield Button("Cancel", id="entry-cancel")

    def on_mount(self) -> None:
        self.query_one("#entry-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "entry-submit":
            self.dismiss(self.query_one("#entry-value", Input).value)
        else:
            self.dismiss(None)
