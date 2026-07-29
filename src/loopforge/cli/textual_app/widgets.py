"""Bounded selectable widgets for the LoopForge Textual TUI (S1.1).

Replaces the ``Static#screen-body`` string-rendering approach with real
selectable widgets.  Each :class:`ScreenList` carries the original item
objects alongside its options so that callers never need to cross-reference
a separate ``_selected_index``.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.widgets import OptionList
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

    def populate(self, items: list[Any], formatter: Callable[[Any], str]) -> None:
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
