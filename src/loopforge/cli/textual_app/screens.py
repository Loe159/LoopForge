"""Small recoverable screens used by the Textual application shell."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option


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


class AdapterSelectionScreen(ModalScreen[str | None]):
    """Keyboard-first picker for the project's persisted implementation adapter."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        adapters: tuple[str, ...],
        selected_adapter: str,
        diagnostics: dict[str, str],
        *,
        selected_args: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.adapters = adapters
        self.selected_adapter = selected_adapter
        self.diagnostics = diagnostics
        self.selected_args = selected_args

    def compose(self) -> ComposeResult:
        with Container(id="adapter-dialog"):
            yield Static("Choose implementation adapter", classes="dialog-title")
            yield Static(
                "Use Up/Down then Enter to save the default for this project. "
                "Unavailable adapters remain selectable and are diagnosed below.",
                classes="secondary",
            )
            yield OptionList(
                *(
                    Option(
                        _adapter_option_label(adapter, self.selected_adapter, self.diagnostics),
                        id=adapter,
                    )
                    for adapter in self.adapters
                ),
                id="adapter-options",
            )
            args = " ".join(self.selected_args) or "none"
            yield Static(f"Current adapter args: {args}", id="adapter-args", classes="secondary")
            yield Button("Cancel", id="adapter-cancel")

    def on_mount(self) -> None:
        options = self.query_one("#adapter-options", OptionList)
        if self.selected_adapter in self.adapters:
            options.highlighted = self.adapters.index(self.selected_adapter)
        options.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        adapter = event.option.id
        self.dismiss(adapter if isinstance(adapter, str) else None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "adapter-cancel":
            self.dismiss(None)


def _adapter_option_label(adapter: str, selected: str, diagnostics: dict[str, str]) -> str:
    marker = "Current" if adapter == selected else "       "
    return f"{marker}  {adapter} - {diagnostics.get(adapter, 'diagnostic unavailable')}"
