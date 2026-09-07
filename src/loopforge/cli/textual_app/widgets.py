"""Bounded selectable widgets for the LoopForge Textual TUI (S1.1).

Replaces the ``Static#screen-body`` string-rendering approach with real
selectable widgets.  Each :class:`ScreenList` carries the original item
objects alongside its options so that callers never need to cross-reference
a separate ``_selected_index``.
"""

from __future__ import annotations

from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import OptionList
from textual.widgets import Input, Static
from textual.widgets.option_list import Option


class ScreenList(OptionList):
    """A bounded, cursor-driven list that preserves item identity.

    Use :meth:`populate` to replace the options from a list of domain
    objects (project rows, run rows, evidence items).  The widget tracks
    the highlighted index via Textual's built-in ``highlighted`` property;
    :meth:`selected_item` returns the domain object at the cursor without
    any external index bookkeeping.

    The list is not keyboard-focusable: cursor movement is driven by the
    app's action handlers (:meth:`move_cursor`), so the app-level bindings
    for up/down/enter remain the sole owners of those keys.
    """

    can_focus = False

    def __init__(self, id: str = "screen-list") -> None:
        super().__init__(id=id)
        self._items: list[Any] = []

    # ── population ──────────────────────────────────────────────────────

    def populate(self, items: list[Any], formatter: Callable[[Any], Any]) -> None:
        """Replace all options, preserving the cursor when possible."""

        previous = self.highlighted or 0
        self._items = list(items)
        self.clear_options()
        for item in self._items:
            self.add_option(Option(formatter(item)))
        if self._items:
            self.highlighted = min(previous, len(self._items) - 1)

    # ── selection ───────────────────────────────────────────────────────

    @property
    def selected_item(self) -> Any | None:
        """Return the domain object at the cursor, or ``None``."""

        index = self.highlighted
        if index is not None and 0 <= index < len(self._items):
            return self._items[index]
        return None

    def move_cursor(self, delta: int) -> None:
        """Advance the cursor by *delta* (wraps at boundaries)."""

        count = len(self._items)
        if count == 0:
            return
        current = self.highlighted or 0
        self.highlighted = (current + delta) % count

    def reset_cursor(self) -> None:
        """Move the cursor back to the first item."""

        self.highlighted = 0 if self._items else None

    @property
    def item_count(self) -> int:
        return len(self._items)


class HomeHeader(Horizontal):
    """Persistent LoopForge identity and global attention summary."""

    def compose(self) -> ComposeResult:
        with Vertical(id="home-brand"):
            yield Static("LoopForge", id="home-product-name")
            yield Static("", id="home-version")
        yield Static("", id="home-summary")

    def update_content(self, *, version: str, project_count: int, attention_count: int) -> None:
        self.query_one("#home-version", Static).update(f"v{version}")
        summary = Text(f"{project_count} projects · ")
        start = len(summary)
        summary.append(f"{attention_count} need attention")
        summary.stylize("#FFB869", start)
        self.query_one("#home-summary", Static).update(summary)


class HomeMetrics(Container):
    """Four factual metrics whose content follows the selected project row."""

    _FIELD_IDS = ("primary", "secondary", "tertiary", "quaternary")

    def __init__(self) -> None:
        super().__init__(id="home-metrics", classes="home-panel")
        self.border_title = "METRICS"

    def compose(self) -> ComposeResult:
        for field_id in self._FIELD_IDS:
            with Vertical(classes="home-metric"):
                yield Static("", id=f"home-metric-{field_id}-label", classes="home-metric-label")
                yield Static("", id=f"home-metric-{field_id}-value", classes="home-metric-value")

    def update_values(self, values: tuple[tuple[str, str], ...]) -> None:
        for field_id, (label, value) in zip(self._FIELD_IDS, values, strict=True):
            self.query_one(f"#home-metric-{field_id}-label", Static).update(label)
            self.query_one(f"#home-metric-{field_id}-value", Static).update(value)


class HomeListPanel(Container):
    """Bordered dashboard list with an explicit active-panel treatment."""

    def __init__(self, title: str, *, panel_id: str, list_id: str) -> None:
        super().__init__(id=panel_id, classes="home-panel home-list-panel")
        self.border_title = title
        self.list_id = list_id

    def compose(self) -> ComposeResult:
        yield ScreenList(id=self.list_id)

    def set_active(self, active: bool) -> None:
        self.set_class(active, "focused")


class HomeCommandInput(Input):
    """Command field that stays out of Textual's automatic focus chain."""

    can_focus = False

    def set_command_active(self, active: bool) -> None:
        self.can_focus = active
        if not active and self.has_focus:
            self.blur()


class HomeCommandBar(Container):
    """Persistent command-only input using the existing slash dispatcher."""

    def __init__(self) -> None:
        super().__init__(id="home-command-bar", classes="home-panel")
        self.border_title = "Command Input"

    def compose(self) -> ComposeResult:
        yield HomeCommandInput(placeholder="› Type / for commands", id="home-command-input")
        yield Static("/run   /status   /pack   /config", id="home-command-hint")

    def update_hint(self, value: str) -> None:
        self.query_one("#home-command-hint", Static).update(
            value or "/run   /status   /pack   /config"
        )


class HomeHotkeyBar(Horizontal):
    """Contextual keyboard guidance matching the selected dashboard state."""

    def compose(self) -> ComposeResult:
        yield Static("", id="home-hotkeys-left")
        yield Static("", id="home-hotkeys-center")
        yield Static("^q Quit", id="home-hotkeys-right")

    def update_state(self, *, project_selected: bool, focus: str) -> None:
        left = "^n New Run" if project_selected else ""
        center = (
            "Enter Focus runs   → Runs"
            if focus == "projects"
            else "Enter Open run   ← Projects"
        )
        self.query_one("#home-hotkeys-left", Static).update(left)
        self.query_one("#home-hotkeys-center", Static).update(center)


class HomeDashboard(Vertical):
    """The assembled main screen; all other Textual screens remain untouched."""

    def __init__(self) -> None:
        super().__init__(id="home-dashboard")

    def compose(self) -> ComposeResult:
        yield HomeHeader(id="home-header")
        yield HomeMetrics()
        with Horizontal(id="home-columns"):
            yield HomeListPanel(
                "Projects",
                panel_id="home-project-panel",
                list_id="home-project-list",
            )
            yield HomeListPanel(
                "Active runs",
                panel_id="home-run-panel",
                list_id="home-run-list",
            )
        yield HomeCommandBar()
        yield HomeHotkeyBar(id="home-hotkeys")
