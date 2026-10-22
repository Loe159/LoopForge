"""Contextual, keyboard-first LoopForge command palette.

Presentation is derived from the existing shell command catalog and the
engine's ActionDescriptor guidance. No command dispatch or eligibility rules
are reimplemented here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterable

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from loopforge.cli.actions import ActionDescriptor


_INSPECTION_COMMANDS = frozenset({
    "context", "compact", "diff", "permissions", "plan", "report", "review",
    "status-details", "raw", "goal", "why", "stats", "allowed-tools",
})


@dataclass(frozen=True)
class PaletteEntry:
    """One actionable row, backed by the original command or guided action."""

    category: str
    label: str
    description: str
    command: str = ""
    action: ActionDescriptor | None = None
    shortcut: str = ""

    @property
    def search_text(self) -> str:
        return " ".join((self.label, self.description, self.command,
                         self.action.id if self.action else ""))


def build_palette_entries(
    actions: Iterable[ActionDescriptor],
    commands: dict[str, str],
    *,
    expert_commands: Iterable[tuple[str, str]] = (),
    has_run: bool = False,
    has_project: bool = True,
) -> tuple[PaletteEntry, ...]:
    """Build display-only categories from the canonical action/command data.

    The engine's guided actions own availability and confirmation. The
    interactive shell owns slash-command discovery and dispatch.
    """

    result: list[PaletteEntry] = []
    covered: set[str] = set()
    for action in actions:
        if not action.available:
            continue
        if not has_project and action.id in {"create-run", "init"}:
            continue
        result.append(PaletteEntry(
            category="NEXT ACTION",
            label=action.label,
            description=action.description,
            action=action,
            shortcut="Enter",
        ))
        fallback = action.command_fallback.strip().removeprefix("/").split(" ", 1)[0]
        if fallback:
            covered.add(fallback)

    catalog = dict(commands)
    if has_run:
        from loopforge.cli.interactive import SUPPORTED_COMMANDS

        for slash, _label in expert_commands:
            name = slash.lstrip("/")
            if name in SUPPORTED_COMMANDS:
                catalog.setdefault(name, SUPPORTED_COMMANDS[name])

    if "run" in catalog:
        catalog.pop("new", None)  # Synonym, not a second entry for one action.
    if not has_project:
        for name in ("run", "new", "init", "continue", "do", "verify"):
            catalog.pop(name, None)

    # Presentation order only; command descriptions and eligibility come from
    # contextual_commands()/SUPPORTED_COMMANDS, never this ordering tuple.
    preferred = ("status", "actions", "guide", "next", "run", "new", "runs",
                 "adapter", "config", "help", "commands")
    sorted_names = sorted(
        catalog,
        key=lambda name: (
            0 if name in preferred else 1,
            preferred.index(name) if name in preferred else name,
        ),
    )
    for name in sorted_names:
        if name in covered:
            continue
        category = "INSPECTION" if name in _INSPECTION_COMMANDS else "COMMANDS"
        result.append(PaletteEntry(
            category=category,
            label=_human_label(name, catalog[name]),
            description=catalog[name],
            command=f"/{name}",
            shortcut="Ctrl+N" if name in {"run", "new"} and has_project else "",
        ))

    groups = ("NEXT ACTION", "COMMANDS", "INSPECTION")
    return tuple(entry for group in groups for entry in result
                 if entry.category == group)


def _human_label(command: str, description: str) -> str:
    """Keep the catalog's own English summary, without inventing behavior."""

    preferred_labels = {
        "status": "Show status",
        "actions": "Available actions",
        "guide": "Workflow guidance",
        "next": "Next action",
        "run": "Create new run",
        "new": "Create new run",
        "runs": "List runs",
        "diff": "Show diff",
        "context": "Show context",
        "permissions": "Show permissions",
        "report": "Evidence report",
        "config": "Project configuration",
    }
    return preferred_labels.get(command, description.rstrip(".") or f"/{command}")


def _normalize(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def command_match_score(entry: PaletteEntry, query: str) -> int:
    """Search by command, label, action id, and purpose; allow partial words."""

    q = _normalize(query.strip()).lstrip("/")
    if not q:
        return 1
    label = _normalize(entry.label)
    command = _normalize(entry.command).lstrip("/")
    corpus = _normalize(entry.search_text)
    if q == command or q == label:
        return 100
    if command.startswith(q) or label.startswith(q):
        return 90
    if q in label or q in command:
        return 75
    tokens = re.findall(r"[\w-]+", corpus)
    if all(any(token.startswith(part) for token in tokens) for part in q.split()):
        return 60
    if q in corpus:
        return 40
    return 0


class PaletteRow(Vertical):
    """One entry whose activation is shared by keyboard and mouse."""

    def __init__(self, index: int, entry: PaletteEntry) -> None:
        super().__init__(id=f"lf-palette-row-{index}", classes="lf-palette-row")
        self.entry_index = index
        self.entry = entry

    def compose(self) -> ComposeResult:
        with Horizontal(classes="lf-palette-row-main"):
            marker = "◆" if self.entry.action is not None else "›"
            yield Static(Text(marker), classes="lf-palette-marker")
            yield Static(Text(self.entry.label), classes="lf-palette-label")
            yield Static(Text(self.entry.shortcut or self.entry.command),
                         classes="lf-palette-shortcut")
        yield Static(Text(self.entry.description), classes="lf-palette-description")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        screen = self.screen
        if isinstance(screen, LoopForgeCommandPalette):
            screen.select_and_execute(self.entry_index)


class LoopForgeCommandPalette(ModalScreen[PaletteEntry | None]):
    """Compact modal that leaves the permanent slash-command input untouched."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=False, priority=True),
        Binding("ctrl+k", "close", "Close", show=False, priority=True),
        Binding("down", "next_result", "Next", show=False, priority=True),
        Binding("up", "previous_result", "Previous", show=False, priority=True),
    ]

    def __init__(self, entries: Iterable[PaletteEntry]) -> None:
        super().__init__()
        self.entries = tuple(entries)
        self._matching: list[int] = []
        self._current: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="lf-command-palette"):
            with Horizontal(id="lf-palette-heading"):
                yield Static("COMMAND PALETTE", id="lf-palette-heading-label")
                yield Static("Ctrl+K", id="lf-palette-heading-key")
            yield Input(placeholder="Search commands...", id="lf-palette-search")
            with VerticalScroll(id="lf-palette-results"):
                for category in ("NEXT ACTION", "COMMANDS", "INSPECTION"):
                    with Vertical(id=f"lf-palette-group-{category.lower().replace(' ', '-')}",
                                  classes="lf-palette-group"):
                        yield Static(category, classes="lf-palette-group-title")
                        for index, entry in enumerate(self.entries):
                            if entry.category == category:
                                yield PaletteRow(index, entry)
            yield Static("No matching commands in this context",
                         id="lf-palette-empty")
            with Horizontal(id="lf-palette-footer"):
                yield Static("", id="lf-palette-count")
                yield Static("↑↓ Navigate  Enter Select  Esc Close",
                             id="lf-palette-help")

    def on_mount(self) -> None:
        self.set_class(self.size.width <= 60, "-narrow")
        self._filter("")
        self.query_one("#lf-palette-search", Input).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width <= 60, "-narrow")

    @on(Input.Changed, "#lf-palette-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        self._filter(event.value)

    @on(Input.Submitted, "#lf-palette-search")
    def _on_search_submitted(self, _event: Input.Submitted) -> None:
        self.action_select_result()

    def _filter(self, query: str) -> None:
        matches: list[tuple[int, int]] = []
        for index, entry in enumerate(self.entries):
            score = command_match_score(entry, query)
            if score:
                matches.append((index, score))
        # Navigation follows the visible grid; relevance selects the best match
        # without producing a different keyboard order from the rendered order.
        self._matching = [index for index, _score in matches]
        if self._current not in self._matching:
            best = max(matches, key=lambda pair: (pair[1], -pair[0]), default=None)
            self._current = best[0] if best is not None else None
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        count = len(self._matching)
        self.query_one("#lf-palette-count", Static).update(
            f"{count} command{'s' if count != 1 else ''}"
        )
        self.query_one("#lf-palette-empty", Static).display = count == 0
        visible = set(self._matching)
        for category in ("NEXT ACTION", "COMMANDS", "INSPECTION"):
            container = self.query_one(
                f"#lf-palette-group-{category.lower().replace(' ', '-')}", Vertical
            )
            container.display = any(
                index in visible and entry.category == category
                for index, entry in enumerate(self.entries)
            )
        for index, entry in enumerate(self.entries):
            row = self.query_one(f"#lf-palette-row-{index}", PaletteRow)
            row.display = index in visible
            row.set_class(index == self._current, "selected")
        if self._current is not None:
            self.query_one(f"#lf-palette-row-{self._current}").scroll_visible()

    def action_next_result(self) -> None:
        self._move(1)

    def action_previous_result(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        if not self._matching:
            return
        position = (self._matching.index(self._current)
                    if self._current in self._matching else 0)
        self._current = self._matching[(position + delta) % len(self._matching)]
        self._refresh_rows()

    def action_select_result(self) -> None:
        if self._current is not None:
            self.select_and_execute(self._current)

    def select_and_execute(self, index: int) -> None:
        if index in self._matching:
            self.dismiss(self.entries[index])

    def action_close(self) -> None:
        self.dismiss(None)
