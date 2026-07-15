"""Small recoverable screens used by the Textual application shell."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Static


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
