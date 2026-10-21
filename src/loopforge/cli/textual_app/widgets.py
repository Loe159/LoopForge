"""Bounded selectable widgets for the LoopForge Textual TUI (S1.1).

Replaces the ``Static#screen-body`` string-rendering approach with real
selectable widgets.  Each :class:`ScreenList` carries the original item
objects alongside its options so that callers never need to cross-reference
a separate ``_selected_index``.
"""

from __future__ import annotations

from typing import Any, Callable
from dataclasses import replace

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList
from textual.widgets import Button, Collapsible, Input, Static, Select
from textual.message import Message
from textual.events import Resize
from textual.widgets.option_list import Option

from loopforge.cli.textual_app.run_presenter import (
    ascii_only,
    family_color,
    run_glyph,
    semantic_color,
    terminal_marker,
    TranscriptEntry,
    DeclaredFileChange,
    agent_body_renderable,
    agent_message_renderable,
    file_diff_renderable,
    tool_display,
    tool_output_renderable,
    transcript_entries,
)


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


class RunHeader(Horizontal):
    """Persistent run identity and its current supervised state."""

    def compose(self) -> ComposeResult:
        yield Static("", id="run-header-brand")
        yield Static("", id="run-header-identity")
        yield Static("", id="run-header-branch")
        yield Static("", id="run-header-status")

    def update_content(
        self,
        *,
        version: str,
        project: str,
        run_number: int | None,
        title: str,
        branch: str,
        status: str,
        status_color: str,
    ) -> None:
        brand = Text("LoopForge", style="bold #D0BCFF")
        brand.append(f"\nv{version}", style="#CBC3D7")
        self.query_one("#run-header-brand", Static).update(brand)
        separator = " / " if ascii_only() else "  /  "
        identity = Text(project or "Project", style="#CBC3D7")
        identity.append(separator, style="#494454")
        identity.append(
            f"Run #{run_number}" if run_number is not None else "Run",
            style="bold #D0BCFF",
        )
        identity.append(" - " if ascii_only() else "  •  ", style="#958EA0")
        identity.append(title or "Untitled run", style="#E7E0ED")
        self.query_one("#run-header-identity", Static).update(identity)
        branch_label = branch if branch and branch != "no Git branch" else run_glyph("—", "-")
        branch_text = Text(f"git:{branch_label}", style="#CBC3D7")
        self.query_one("#run-header-branch", Static).update(branch_text)
        state = Text(status)
        state.stylize(status_color)
        self.query_one("#run-header-status", Static).update(state)


class RunToolEntry(Collapsible):
    """Hybrid tool row: compact title, scrollable syntax-aware output on demand.

    The source body and call key remain untouched for full detail and identity.
    """

    def __init__(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        self.detail = Static("", markup=False, classes="run-tool-detail")
        self.body_container = Vertical(self.detail, classes="run-tool-content")
        self.phase = 0
        super().__init__(self.body_container, title="", collapsed=True,
                         collapsed_symbol=run_glyph("▸", ">"),
                         expanded_symbol=run_glyph("▾", "v"), classes="run-tool-entry")
        self.update_entry(entry)

    def update_entry(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        view = tool_display(entry) if entry.kind == "tool" else None
        self._summary = view.summary if view else entry.summary
        self._output = view.output if view else entry.body
        if self._output:
            body = tool_output_renderable(self._output) if entry.kind == "tool" else agent_body_renderable(
                self._output, tool_output=True)
        else:
            body = Text("No result received" if entry.status == "unknown"
                        else "Waiting for output" if entry.status == "running"
                        else "No output", style="#958EA0")
        self.detail.update(body)
        self.set_class(entry.status == "failed", "tool-failed")
        self.set_class(entry.status == "running", "tool-running")
        self.set_class(entry.status == "unknown", "tool-unknown")
        self.refresh_title()

    def on_resize(self) -> None:
        self.refresh_title()

    def refresh_title(self) -> None:
        entry = self.entry
        if entry.kind in {"reasoning", "group", "delegation"}:
            self.title = Text(entry.title + (f"  {entry.summary}" if entry.summary else ""))
            return
        if entry.status == "running":
            frames = "|/-\\" if ascii_only() else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            marker = frames[self.phase % len(frames)]
        else:
            marker = {"completed": run_glyph("✓", "+"),
                      "failed": run_glyph("×", "x")}.get(entry.status, "?")
        states = {"completed": "Done", "failed": "Failed", "running": "Running",
                  "unknown": "No result received"}
        state = states.get(entry.status, "Unknown")
        color = (semantic_color("danger") if entry.status == "failed"
                 else semantic_color("success") if entry.status == "completed"
                 else "#D0BCFF" if entry.status == "running" else "#FFB869")
        title = Text(marker, style=color)
        title.append(f" {entry.title}", style="bold #E7E0ED")
        # The status stays visible at narrow widths instead of being truncated
        # behind a very long command.
        command = " ".join(self._summary.split())
        reserved = len(title.plain) + len(state) + 5
        width = self.size.width or 90
        budget = max(0, width - reserved - 3)
        if command and budget >= 6:
            if len(command) > budget:
                command = command[:budget - 1].rstrip() + run_glyph("…", ".")
            title.append("  " + command, style="#CBC3D7")
        title.append("  " + state, style=color)
        self.title = title


class RunReasoningEntry(RunToolEntry):
    """Quiet, read-only disclosure for reasoning actually exposed by the harness.

    Reuses the tool disclosure's stable identity and follow-suspension behavior;
    no private reasoning is reconstructed or attributed to the agent.
    """

    def __init__(self, entry: TranscriptEntry, *, adapter_label: str = "") -> None:
        self.adapter_label = adapter_label
        super().__init__(entry)
        self.add_class("run-reasoning-entry")

    def update_entry(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        self._output = entry.body
        body = agent_body_renderable(entry.body)
        if isinstance(body, Text):
            body.stylize("#CBC3D7")
        self.detail.update(body)
        self.refresh_title()

    def refresh_title(self) -> None:
        title = Text("Reasoning", style="italic #958EA0")
        if self.adapter_label:
            title.append("  ·  " + self.adapter_label, style="#958EA0")
        self.title = title




class RunDelegationEntry(Collapsible):
    """Native delegation disclosure; child activity requires a retained parent ID."""

    def __init__(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        self.phase = 0
        self.detail = Static("", markup=False, classes="run-delegation-detail")
        self._child_list = Vertical(classes="run-delegation-children")
        self._child_items: dict[str, Static | RunToolEntry | RunFileChangeEntry | RunDelegationEntry] = {}
        self.body_container = Vertical(self.detail, self._child_list, classes="run-delegation-content")
        super().__init__(
            self.body_container, title="", collapsed=True,
            collapsed_symbol=run_glyph("▸", ">"),
            expanded_symbol=run_glyph("▾", "v"),
            classes="run-delegation-entry",
        )
        self.update_entry(entry)

    def on_mount(self) -> None:
        self._sync_children()

    def on_resize(self) -> None:
        self.refresh_title()

    def refresh_title(self) -> None:
        linked = bool(self.entry.children)
        label = ("Sub-agent" if linked else "Delegation") + " · " + self.entry.title
        state = {
            "running": "Running", "completed": "Completed",
            "failed": "Failed", "unknown": "Unknown",
        }.get(self.entry.status, "Unknown")
        frames = "|/-" if ascii_only() else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        marker = {
            "running": frames[self.phase % len(frames)],
            "completed": run_glyph("✓", "+"),
            "failed": run_glyph("×", "x"), "unknown": "?",
        }.get(self.entry.status, "?")
        width = self.size.width or 90
        warning = "  ! Child error" if any(self._child_failed(child)
                                            for child in self.entry.children) else ""
        reserved = len(state) + len(warning) + 6
        limit = max(8, width - reserved)
        if len(label) > limit:
            label = label[:max(1, limit - 1)].rstrip() + run_glyph("…", ".")
        title = Text(label, style="bold #E7E0ED")
        color = (semantic_color("danger") if self.entry.status == "failed"
                 else semantic_color("success") if self.entry.status == "completed"
                 else "#D0BCFF" if self.entry.status == "running" else "#958EA0")
        title.append(f"  {marker} {state}", style=color)
        if warning:
            title.append(warning, style="#FFB4AB")
        self.title = title

    @staticmethod
    def _child_failed(entry: TranscriptEntry) -> bool:
        return (entry.status == "failed" or entry.kind == "error" or
                any(RunDelegationEntry._child_failed(child) for child in entry.children))

    def update_entry(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        # Display the native mission only when the adapter explicitly exposes it.
        self.detail.display = bool(entry.body or entry.mission)
        if entry.body or entry.mission:
            parts = []
            if entry.mission:
                parts.extend((Text("Mission", style="#958EA0"),
                              agent_body_renderable(entry.mission, tool_output=True)))
            if entry.body and entry.body != entry.mission:
                parts.extend((Text("Delegation details", style="#958EA0"),
                              agent_body_renderable(entry.body, tool_output=True)))
            self.detail.update(Group(*parts))
        self.set_class(entry.status == "failed", "delegation-failed")
        self.refresh_title()
        if self.is_mounted:
            self._sync_children()

    def _sync_children(self) -> None:
        entries = self.entry.children
        keys = {entry.key for entry in entries}
        for key in tuple(self._child_items):
            if key not in keys:
                self._child_items.pop(key).remove()
        previous = None
        for entry in entries:
            widget = self._child_items.get(entry.key)
            if widget is None:
                if entry.kind == "delegation":
                    widget = RunDelegationEntry(entry)
                elif entry.kind == "reasoning":
                    widget = RunReasoningEntry(entry)
                elif entry.kind == "file_change":
                    widget = RunFileChangeEntry(entry)
                elif entry.kind in {"tool", "group"}:
                    widget = RunToolEntry(entry)
                elif entry.kind == "message":
                    widget = Static(Group(
                        Text("Agent", style="bold #D0BCFF"),
                        agent_message_renderable(entry.body),
                    ), markup=False, classes="run-delegation-message")
                else:
                    line = Text(entry.title, style=(
                        semantic_color("danger") if entry.kind == "error" else "#CBC3D7"))
                    if entry.body:
                        line.append("\n" + entry.body, style="#CBC3D7")
                    widget = Static(line, markup=False, classes="run-delegation-event")
                self._child_items[entry.key] = widget
                self._child_list.mount(widget)
            elif isinstance(widget, RunDelegationEntry):
                widget.update_entry(entry)
            elif isinstance(widget, RunReasoningEntry):
                widget.update_entry(entry)
            elif isinstance(widget, RunToolEntry):
                widget.update_entry(entry)
            elif isinstance(widget, RunFileChangeEntry):
                if widget.entry != entry:
                    widget.update_entry(entry)
            elif entry.kind == "message":
                widget.update(Group(
                    Text("Agent", style="bold #D0BCFF"),
                    agent_message_renderable(entry.body),
                ))
            else:
                line = Text(entry.title, style=(
                    semantic_color("danger") if entry.kind == "error" else "#CBC3D7"))
                if entry.body:
                    line.append("\n" + entry.body, style="#CBC3D7")
                widget.update(line)
            if previous is None:
                if self._child_list.children and self._child_list.children[0] is not widget:
                    self._child_list.move_child(widget, before=0)
            else:
                self._child_list.move_child(widget, after=previous)
            previous = widget


def _file_change_row(file: DeclaredFileChange) -> Collapsible:
    """Each native-declared path expands its captured session diff inline."""
    action = {"modified": "Edit", "added": "Add", "deleted": "Delete",
              "renamed": "Rename"}.get(file.action, "File")
    title = Text(f"{action}  {file.path}", style="bold #E7E0ED")
    if file.additions is not None:
        title.append(f"  +{file.additions}", style="#A8E6B0")
    if file.deletions is not None:
        title.append(f"  -{file.deletions}", style="#FFB4AB")
    return Collapsible(
        VerticalScroll(
            Static(file_diff_renderable(file), markup=False, classes="run-file-diff-text"),
            classes="run-file-diff-scroll",
        ),
        title=title, collapsed=True,
        collapsed_symbol=run_glyph("▸", ">"),
        expanded_symbol=run_glyph("▾", "v"),
        classes="run-file-change-row",
    )


class RunFileChangeEntry(Collapsible):
    """One native event, with an independent disclosure for each declared file.

    Counts and inline diffs are from the selected execution's captured
    workspace snapshot, never proof of an individual harness edit.
    """

    def __init__(self, entry: TranscriptEntry, *, source_label: str = "") -> None:
        self.entry = entry
        self.source_label = source_label
        initial_rows = (
            tuple(_file_change_row(file) for file in entry.file_changes)
            if entry.file_changes else
            (Static(Text("File paths unavailable in this native event.", style="#958EA0"),
                    markup=False, classes="run-file-change-empty"),)
        )
        self._rows = Vertical(*initial_rows, classes="run-file-change-rows")
        self._origin = Static("", markup=False, classes="run-file-change-origin")
        self._content = Vertical(self._rows, self._origin, classes="run-file-change-content")
        super().__init__(
            self._content, title="", collapsed=True,
            collapsed_symbol=run_glyph("▸", ">"),
            expanded_symbol=run_glyph("▾", "v"),
            classes="run-file-change-entry",
        )
        self.update_entry(entry)

    def update_entry(self, entry: TranscriptEntry) -> None:
        # Keep per-file disclosures when a retained capture becomes available.
        expanded = {}
        if self._rows.is_mounted:
            for file, child in zip(self.entry.file_changes, self._rows.query(".run-file-change-row")):
                if isinstance(child, Collapsible):
                    expanded[file.path] = not child.collapsed
        self.entry = entry
        files = entry.file_changes
        word = "file" if len(files) == 1 else "files"
        label = (f"Edited {len(files)} {word}" if files and all(
            f.action == "modified" for f in files
        ) else f"Files changed · {len(files)} {word}" if files else "Files changed")
        title = Text(label, style="bold #E7E0ED")
        if self.source_label:
            title.append("  " + self.source_label, style="#958EA0")
        self.title = title
        has_capture = any(file.diff or file.additions is not None
                          or file.deletions is not None for file in files)
        origin = "Declared by agent"
        if has_capture:
            origin += " · snapshot diff (entire session)"
        self._origin.update(Text(origin, style="#958EA0"))
        if self._rows.is_mounted:
            self._rows.remove_children()
            if files:
                children = tuple(_file_change_row(file) for file in files)
                for child, file in zip(children, files):
                    child.collapsed = not expanded.get(file.path, False)
                self._rows.mount(*children)
            else:
                self._rows.mount(Static(Text(
                    "File paths unavailable in this native event.", style="#958EA0"),
                    markup=False, classes="run-file-change-empty"))


class RunAgentOutput(Vertical):
    """One incremental narrative, preserving tool widgets and keyboard focus."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transcript = Text()
        self._items: dict[str, Static | RunToolEntry | RunFileChangeEntry | RunDelegationEntry] = {}
        self._entries: tuple[TranscriptEntry, ...] = ()
        self._scope: object = None

    def on_mount(self) -> None:
        self._spinner = self.set_interval(0.12, self._tick, pause=True)

    def _tick(self) -> None:
        for item in (*self.query(RunToolEntry), *self.query(RunDelegationEntry)):
            if item.entry.status == "running":
                item.phase += 1
                item.refresh_title()

    def update(self, value: Text, *, active: bool = True, scope: object = None,
               entries: tuple[TranscriptEntry, ...] | None = None,
               adapter_label: str = "") -> None:
        if scope != self._scope:
            for item in self._items.values():
                item.remove()
            self._items.clear()
            self._entries = ()
            self._scope = scope
        self.transcript = value
        entries = entries if entries is not None else transcript_entries(value.plain)
        if not active:
            entries = tuple(replace(entry, status="unknown") if entry.status == "running" else entry
                            for entry in entries)
        # An empty native reasoning event does not expose any content to read.
        entries = tuple(entry for entry in entries
                        if entry.kind != "reasoning" or entry.body.strip())
        if entries == self._entries:
            return
        self._entries = entries
        keys = {entry.key for entry in entries}
        for key in tuple(self._items):
            if key not in keys:
                self._items.pop(key).remove()
        for entry in entries:
            item = self._items.get(entry.key)
            if item is None:
                if entry.kind == "file_change":
                    item = RunFileChangeEntry(entry, source_label=adapter_label)
                elif entry.kind == "reasoning":
                    item = RunReasoningEntry(entry, adapter_label=adapter_label)
                elif entry.kind == "delegation":
                    item = RunDelegationEntry(entry)
                elif entry.kind in {"tool", "group"}:
                    item = RunToolEntry(entry)
                else:
                    text = Text()
                    if entry.kind == "message":
                        item = Static(
                            Group(
                                Text("Agent", style="bold #D0BCFF"),
                                agent_message_renderable(entry.body),
                            ),
                            markup=False,
                            classes="run-entry-message",
                        )
                        self._items[entry.key] = item
                        self.mount(item)
                        continue
                    else:
                        text.append(entry.title, style="#958EA0")
                        if entry.body:
                            text.append("\n" + entry.body, style="#CBC3D7")
                    item = Static(text, markup=False, classes=f"run-entry-{entry.kind}")
                self._items[entry.key] = item
                self.mount(item)
            elif isinstance(item, RunDelegationEntry):
                item.update_entry(entry)
            elif isinstance(item, RunToolEntry):
                item.update_entry(entry)
            elif isinstance(item, RunFileChangeEntry):
                if item.entry != entry:
                    item.update_entry(entry)
            elif isinstance(item, Static):
                if entry.kind == "message":
                    item.update(Group(
                        Text("Agent", style="bold #D0BCFF"),
                        agent_message_renderable(entry.body),
                    ))
                else:
                    body = agent_body_renderable(entry.body)
                    if isinstance(body, Text):
                        content = Text(entry.title + "\n", style="bold #E7E0ED")
                        content.append_text(body)
                        item.update(content)
                    else:
                        item.update(Group(Text(entry.title), body))
        if any(entry.status == "running" or any(child.status == "running"
                   for child in entry.children) for entry in entries):
            self._spinner.resume()
        else:
            self._spinner.pause()
        self._order_entries()

    def _order_entries(self) -> None:
        # Reopening/final artifact refreshes can insert older entries before
        # already-mounted live rows. Move them without replacing focused tools.
        # mount() registers children synchronously; only their Mount events are
        # asynchronous. Order now, before painting, rather than in a callback
        # after a refresh that may be deferred or superseded by another update.
        previous = None
        for entry in self._entries:
            item = self._items.get(entry.key)
            if item is None or item.parent is not self:
                continue
            if previous is None:
                if self.children and self.children[0] is not item:
                    self.move_child(item, before=0)
            else:
                self.move_child(item, after=previous)
            previous = item


class RunTranscriptPanel(Container):
    """One labeled transcript surface inside the scrolling run narrative."""

    def __init__(self, title: str, *, panel_id: str, body_id: str) -> None:
        super().__init__(id=panel_id, classes="run-transcript-panel")
        self.border_title = title
        self._body_id = body_id

    def compose(self) -> ComposeResult:
        if self._body_id == "run-agent-output":
            yield RunAgentOutput(id=self._body_id)
        else:
            yield Static("", id=self._body_id, markup=False)

    def update_title(self, title: str) -> None:
        self.border_title = title


class RunActivityFeed(VerticalScroll):
    """Scrollable run narrative matching the prompt/output/contract prototype."""

    can_focus = False

    class ReadingMoved(Message):
        pass

    def on_mouse_scroll_up(self) -> None:
        self.post_message(self.ReadingMoved())

    def __init__(self) -> None:
        super().__init__(id="run-activity-feed")
        self._system_prompt: str | None = None
        self._implementation_contract: str | None = None
        self._adapter_title: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="run-attempt-heading")
        yield RunTranscriptPanel(
            "Agent Output",
            panel_id="run-agent-output-panel",
            body_id="run-agent-output",
        )
        yield RunTranscriptPanel(
            "Implementation Contract",
            panel_id="run-implementation-panel",
            body_id="run-implementation-contract",
        )
        with Vertical(id="run-execution-result"):
            yield Static("", id="run-result-text", markup=False)
            with Horizontal(classes="run-result-links"):
                yield Button("View changes", id="run-result-changes", classes="run-link")
                yield Button("View evidences", id="run-result-evidences", classes="run-link")

    def update_content(
        self,
        *,
        heading: Text,
        system_prompt: str,
        agent_output: Text,
        implementation_contract: str,
        adapter: str,
        active: bool = True,
        scope: object = None,
        entries: tuple[TranscriptEntry, ...] | None = None,
    ) -> None:
        ellipsis = "..." if ascii_only() else "…"
        self.query_one("#run-attempt-heading", Static).update(heading)
        self.query_one("#run-agent-output", RunAgentOutput).update(
            agent_output, active=active, scope=scope, entries=entries,
            adapter_label=(adapter or "agent").replace("-", " ").title(),
        )
        contract_panel = self.query_one(
            "#run-implementation-panel", RunTranscriptPanel
        )
        contract = implementation_contract.strip()
        if contract != self._implementation_contract:
            self.query_one("#run-implementation-contract", Static).update(contract)
            self._implementation_contract = contract
        contract_panel.display = False  # Contract evidence belongs to Evidences.
        adapter_label = (adapter or "agent").replace("-", " ").title()
        adapter_title = f"Agent Output {'-' if ascii_only() else '•'} {adapter_label}"
        if adapter_title != self._adapter_title:
            self.query_one(
                "#run-agent-output-panel", RunTranscriptPanel
            ).update_title(adapter_title)
            self._adapter_title = adapter_title


class RunDetailEntry(Collapsible):
    """Inspectable context, diff or evidence; content is always literal."""

    def __init__(self, key: str, title: str, body: str, *, expanded: bool = False) -> None:
        self.key = key
        self.body = body
        self.detail = Static(Text(body), markup=False)
        super().__init__(self.detail, title=Text(title), collapsed=not expanded,
                         collapsed_symbol=run_glyph("▸", ">"), expanded_symbol=run_glyph("▾", "v"),
                         classes="run-document-entry")


class RunDocumentView(VerticalScroll):
    """Lazily loaded sections whose stable identities preserve disclosures."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._scope: object = None
        self._items: dict[str, RunDetailEntry] = {}

    def update_sections(self, scope: object, sections: tuple[tuple[str, str, str, bool], ...]) -> None:
        if scope != self._scope:
            self.remove_children()
            self._items.clear()
            self._scope = scope
        keys = {s[0] for s in sections}
        for key in tuple(self._items):
            if key not in keys:
                self._items.pop(key).remove()
        for key, title, body, expanded in sections:
            item = self._items.get(key)
            if item is None:
                item = RunDetailEntry(key, title, body, expanded=expanded)
                self._items[key] = item
                self.mount(item)
            elif item.body != body or item.title != Text(title):
                item.body = body
                item.title = Text(title)
                item.detail.update(Text(body))


class RunChangesExplorer(Vertical):
    """Read-only explorer of the selected run's retained changes.

    Never reads workspace files: the code preview is the captured, bounded diff.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._selection_scope: object = None
        self._signature: object = None
        self._files: tuple[Any, ...] = ()
        self._selected_path = ""
        self._option_file_indices: dict[str, int] = {}
        self._option_directories: dict[str, tuple[str, ...]] = {}
        self._collapsed_directories: set[tuple[str, ...]] = set()
        self._tree_open = False  # Compact screens start with full diff visibility.
        self._preview_signature: object = None

    def on_resize(self, event: Resize) -> None:
        # 14 usable body rows (16 including the summary) can accommodate both
        # a scrollable file tree and a meaningful syntax-highlighted diff.
        # Measure the actual explorer height, not only the terminal's width.
        self.set_class(event.size.height >= 16, "stacked-tree-diff")

    def compose(self) -> ComposeResult:
        yield Static("", id="run-changes-summary", markup=False)
        with Horizontal(id="run-changes-body"):
            with Vertical(id="run-changes-files"):
                yield Button("Files", id="run-changes-tree-toggle", classes="run-link")
                yield OptionList(id="run-changes-file-list")
            with Vertical(id="run-changes-preview"):
                yield Static("", id="run-changes-file-heading", markup=False)
                with VerticalScroll(id="run-changes-diff-scroll"):
                    yield Static("", id="run-changes-diff-text", markup=False)

    @staticmethod
    def _action(status: str) -> str:
        return {"modified": "Edit", "added": "Add", "deleted": "Delete",
                "renamed": "Rename"}.get(status, "Change")

    @staticmethod
    def _counts(file: Any) -> Text:
        value = Text()
        if file.additions is not None:
            value.append(f"+{file.additions}", style="#A8E6B0")
        if file.deletions is not None:
            if value:
                value.append("  ")
            value.append(f"-{file.deletions}", style="#FFB4AB")
        return value

    def update_changes(self, scope: object, evidence: Any, *,
                       cumulative: bool = False, session_label: str = "") -> None:
        if evidence is None:
            from loopforge.cli.run_changes import RunChangesSnapshot
            evidence = RunChangesSnapshot()
        files = tuple(evidence.files)
        signature = (scope, evidence.scope, evidence.source, evidence.capture_state,
                     evidence.message, evidence.stale, evidence.base_commit, files)
        if signature == self._signature:
            return

        same_scope = scope == self._selection_scope
        old_path = self._selected_path if same_scope else ""
        if not same_scope:
            self._collapsed_directories.clear()
            self._tree_open = False
        self._selection_scope = scope
        self._signature = signature
        self._files = files
        paths = [file.path for file in files]
        selected_index = paths.index(old_path) if old_path in paths else 0

        heading = Text(f"{len(files)} files", style="bold #E7E0ED")
        if files and all(file.additions is not None and file.deletions is not None
                         for file in files):
            heading.append(f"  +{sum(f.additions for f in files)}", style="#A8E6B0")
            heading.append(f"  -{sum(f.deletions for f in files)}", style="#FFB4AB")
        heading.append(" · " + ("Cumulative patch" if cumulative else "Workspace capture"),
                       style="#958EA0")
        heading.append(" · " + evidence.capture_state, style="#958EA0")
        if evidence.stale:
            heading.append(" · STALE", style="#FFB869")
        if evidence.message and (not files or evidence.stale or evidence.capture_state != "complete"):
            heading.append("\n" + evidence.message[:140], style="#958EA0")
        if evidence.base_commit:
            heading.append("\nBase: " + str(evidence.base_commit)[:16], style="#958EA0")
        self.query_one("#run-changes-summary", Static).update(heading)

        # Retained captures may refresh while the cursor is on a directory.
        # Preserve that node rather than jumping back to the last previewed file.
        focused_folder = None
        if same_scope and self._option_directories:
            picker = self.query_one("#run-changes-file-list", OptionList)
            position = picker.highlighted
            if position is not None and position < len(picker.options):
                focused_folder = self._option_directories.get(picker.options[position].id)
        self._render_tree(selected_index=selected_index, focus_folder=focused_folder)
        if files:
            self._select_file(selected_index)
        else:
            self._selected_path = ""
            self._preview_signature = None
            self.query_one("#run-changes-file-heading", Static).update(
                Text("No retained file changes", style="#CBC3D7"))
            self.query_one("#run-changes-diff-text", Static).update(
                Text(evidence.message or "No reliable snapshot for this selection.",
                     style="#958EA0"))
            self._update_tree_visibility()

    def _render_tree(self, *, selected_index: int | None = None,
                     focus_folder: tuple[str, ...] | None = None) -> None:
        picker = self.query_one("#run-changes-file-list", OptionList)
        picker.clear_options()
        self._option_file_indices.clear()
        self._option_directories.clear()
        root: dict[str, Any] = {"directories": {}, "files": []}
        for index, file in enumerate(self._files):
            parts = [part for part in file.path.replace("\\", "/").split("/") if part]
            if not parts:
                parts = [file.path]
            node = root
            for part in parts[:-1]:
                node = node["directories"].setdefault(
                    part, {"directories": {}, "files": []})
            node["files"].append((parts[-1], index))

        # Directory identity is its full relative path, not an option index:
        # collapsing a node does not make a neighboring file appear selected.
        desired_id = ""

        def populate(node: dict[str, Any], ancestors: tuple[str, ...]) -> None:
            nonlocal desired_id
            depth = len(ancestors)
            for folder, children in sorted(node["directories"].items()):
                folder_path = (*ancestors, folder)
                closed = folder_path in self._collapsed_directories
                option_id = f"change-dir-{len(self._option_directories)}"
                mark = run_glyph("▸ ", "> ") if closed else run_glyph("▾ ", "v ")
                label = Text("  " * depth + mark + folder + "/",
                             style="#D0BCFF" if closed else "#CBC3D7",
                             no_wrap=True, overflow="ellipsis")
                picker.add_option(Option(label, id=option_id))
                self._option_directories[option_id] = folder_path
                if folder_path == focus_folder:
                    desired_id = option_id
                if not closed:
                    populate(children, folder_path)
            for name, index in node["files"]:
                file = self._files[index]
                label = Text("  " * depth + run_glyph("• ", "* ") + name,
                             style="#E7E0ED", no_wrap=True, overflow="ellipsis")
                label.append("  ")
                label.append_text(self._counts(file))
                option_id = f"change-file-{index}"
                picker.add_option(Option(label, id=option_id))
                self._option_file_indices[option_id] = index
                if index == selected_index and not desired_id and focus_folder is None:
                    desired_id = option_id

        populate(root, ())
        if desired_id:
            for idx, option in enumerate(picker.options):
                if option.id == desired_id:
                    picker.highlighted = idx
                    break
        self._update_tree_visibility()

    def _update_tree_visibility(self) -> None:
        container = self.query_one("#run-changes-files")
        container.set_class(self._tree_open, "tree-open")
        self.set_class(self._tree_open, "compact-tree-open")
        toggle = self.query_one("#run-changes-tree-toggle", Button)
        marker = run_glyph("▾", "v") if self._tree_open else run_glyph("▸", ">")
        current = self._selected_path.rsplit("/", 1)[-1]
        toggle.label = f"{marker} Files ({len(self._files)})" + (
            f" · {current}" if current and not self._tree_open else ""
        )

    def _toggle_folder(self, path: tuple[str, ...], *, open_only: bool = False,
                       close_only: bool = False) -> None:
        collapsed = path in self._collapsed_directories
        if (collapsed and not close_only) or (not collapsed and open_only):
            self._collapsed_directories.discard(path)
        elif not collapsed and not open_only:
            self._collapsed_directories.add(path)
        else:
            return
        self._render_tree(focus_folder=path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-changes-tree-toggle":
            self._tree_open = not self._tree_open
            self._update_tree_visibility()
            if self._tree_open:
                self.query_one("#run-changes-file-list", OptionList).focus()
            event.stop()

    def _highlight_directory(self, path: tuple[str, ...]) -> None:
        """Move the keyboard cursor to a visible ancestor without changing preview."""
        picker = self.query_one("#run-changes-file-list", OptionList)
        for index, option in enumerate(picker.options):
            if self._option_directories.get(option.id) == path:
                picker.highlighted = index
                return

    def on_key(self, event: Any) -> None:
        picker = self.query_one("#run-changes-file-list", OptionList)
        if not picker.has_focus or event.key not in {"left", "right"}:
            return
        position = picker.highlighted
        if position is None or position >= len(picker.options):
            return
        option = picker.options[position]
        path = self._option_directories.get(option.id)
        if path is not None:
            if event.key == "right":
                if path in self._collapsed_directories:
                    self._toggle_folder(path, open_only=True)
                elif position + 1 < len(picker.options):
                    # Right on an already-expanded folder enters its first child.
                    next_option = picker.options[position + 1]
                    next_path = self._option_directories.get(next_option.id)
                    next_file_index = self._option_file_indices.get(next_option.id)
                    if ((next_path is not None and next_path[:len(path)] == path)
                            or (next_file_index is not None and
                                self._files[next_file_index].path.replace("\\", "/").split("/")[:len(path)]
                                == list(path))):
                        picker.highlighted = position + 1
            elif path not in self._collapsed_directories:
                self._toggle_folder(path, close_only=True)
            elif len(path) > 1:
                self._highlight_directory(path[:-1])
        else:
            file_index = self._option_file_indices.get(option.id)
            if file_index is not None:
                if event.key == "left":
                    parts = self._files[file_index].path.replace("\\", "/").split("/")
                    if len(parts) > 1:
                        self._highlight_directory(tuple(parts[:-1]))
                elif self.query_one("#run-changes-tree-toggle", Button).display:
                    # On compact terminals right opens the selected preview.
                    # On wide terminals the preview is already visible, so
                    # keep keyboard focus in the tree for continued navigation.
                    self._tree_open = False
                    self._update_tree_visibility()
                    self.query_one("#run-changes-tree-toggle", Button).focus()
        event.stop()

    def _select_file(self, index: int) -> None:
        if not isinstance(index, int) or not 0 <= index < len(self._files):
            return
        file = self._files[index]
        old_path = self._selected_path
        self._selected_path = file.path
        title = Text(f"{self._action(file.status)} · {file.path}", style="bold #E7E0ED")
        count = self._counts(file)
        if count:
            title.append("  ")
            title.append_text(count)
        if file.previous_path:
            title.append("\nFrom: " + file.previous_path, style="#958EA0")
        if file.binary:
            title.append(" · binary", style="#FFB869")
        if file.truncated:
            title.append(" · truncated", style="#FFB869")
        self.query_one("#run-changes-file-heading", Static).update(title)
        from loopforge.cli.textual_app.run_presenter import DeclaredFileChange
        signature = (file.path, file.diff, file.binary, file.truncated)
        if signature != self._preview_signature:
            self.query_one("#run-changes-diff-text", Static).update(
                file_diff_renderable(DeclaredFileChange(
                    file.path, file.status, file.additions, file.deletions,
                    file.diff, file.truncated, file.binary)))
            self._preview_signature = signature
        if file.path != old_path:
            self.query_one("#run-changes-diff-scroll", VerticalScroll).scroll_home(
                animate=False)
        self._update_tree_visibility()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "run-changes-file-list":
            if event.option:
                index = self._option_file_indices.get(event.option.id)
                if index is not None:
                    self._select_file(index)
            event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "run-changes-file-list":
            if event.option:
                directory = self._option_directories.get(event.option.id)
                if directory is not None:
                    self._toggle_folder(directory)
                else:
                    index = self._option_file_indices.get(event.option.id)
                    if index is not None:
                        self._select_file(index)
                        # The single-pane toggle exists only below 52 columns.
                        toggle = self.query_one("#run-changes-tree-toggle", Button)
                        if toggle.display:
                            self._tree_open = False
                            self._update_tree_visibility()
                            toggle.focus()
            event.stop()


class RunCommandBar(Container):
    """Command entry shown when the run is not waiting on a human gate."""

    COMMAND_HINT = "/run   /status   /actions   /config"

    def __init__(self) -> None:
        super().__init__(id="run-command-bar", classes="run-panel")
        self.border_title = "Command Input"

    def compose(self) -> ComposeResult:
        yield HomeCommandInput(
            placeholder=f"{run_glyph('›', '>')} Type / for commands",
            id="run-command-input",
        )
        yield Static(self.COMMAND_HINT, id="run-command-hint")

    def update_hint(self, value: str) -> None:
        self.query_one("#run-command-hint", Static).update(
            value or self.COMMAND_HINT
        )


class RunRequiredAction(Container):
    """A compact, keyboard-first dock for the authoritative next action."""

    def __init__(self) -> None:
        super().__init__(id="run-required-action", classes="run-panel")

    def compose(self) -> ComposeResult:
        yield Static("", id="run-action-title")
        yield Static("", id="run-action-description")
        yield Static("", id="run-action-controls")

    def update_action(self, action: Any | None, *, blocked: bool = False,
                      reason: str = "") -> None:
        self.display = action is not None or blocked
        if not self.display:
            return
        title = (
            f"BLOCKED {run_glyph('—', '-')} ACTION REQUIRED"
            if blocked
            else "Approval required"
        )
        self.query_one("#run-action-title", Static).update(title)
        self.query_one("#run-action-description", Static).update(
            Text(str(getattr(action, "description", reason or "Inspect the retained evidence.")))
        )
        controls = Text()
        if action is not None:
            controls.append(" Ctrl+Enter ", style="bold #0A0A0A on #D0BCFF")
            controls.append(f"  {action.label}")
        controls.append("    Ctrl+K ", style="#D0BCFF")
        controls.append("Other actions", style="#CBC3D7")
        self.query_one("#run-action-controls", Static).update(controls)


class RunContextPanel(Container):
    """Square, border-titled panel used within the fixed run sidebar."""

    def __init__(self, title: str, *, panel_id: str) -> None:
        super().__init__(id=panel_id, classes="run-context-panel")
        self.border_title = title


class RunWorkflowList(OptionList):
    """Stage-only navigation with read-only nested agent TODO lines."""
    BINDINGS = [*OptionList.BINDINGS,
                Binding("right", "cursor_right", show=False),
                Binding("left", "cursor_left", show=False)]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plan_stage = ""
        self.expanded = True
        self.toggle_plan: Callable[[], None] | None = None

    def action_cursor_right(self) -> None:
        if self.plan_stage and not self.expanded and self.toggle_plan:
            self.toggle_plan()

    def action_cursor_left(self) -> None:
        if self.plan_stage and self.expanded and self.toggle_plan:
            self.toggle_plan()

    async def _on_click(self, event: Any) -> None:
        index = event.style.meta.get("option")
        if index is not None and 0 <= index < len(self.options):
            option = self.options[index]
            if option.id == self.plan_stage and self.highlighted == index and self.toggle_plan:
                self.toggle_plan()
                event.stop()
                return
        await super()._on_click(event)


class RunContextSidebar(Vertical):
    """Supervision scrolls independently; four-view navigation stays pinned."""

    def compose(self) -> ComposeResult:
        yield Static("RUN CONTEXT", id="run-context-title")
        with VerticalScroll(id="run-context-details"):
            with RunContextPanel("Current activity", panel_id="run-context-configuration-panel"):
                yield Static("", id="run-context-configuration", markup=False)
                yield Button("", id="run-problems", classes="run-link")
            with RunContextPanel("Workflow", panel_id="run-context-steps-panel"):
                yield RunWorkflowList(id="run-context-steps")
            with RunContextPanel("Metrics", panel_id="run-context-metrics-panel"):
                yield Static("", id="run-context-metrics", markup=False)
        with Vertical(id="run-view-tabs"):
            for view in ("Live", "Context", "Changes", "Evidences"):
                yield Button(view, id="run-view-" + view.lower(), classes="run-link")

    def _toggle_plan(self) -> None:
        self._plan_expanded = not getattr(self, "_plan_expanded", True)
        self._workflow_signature = None
        if getattr(self, "_last_content", None) is not None:
            self.update_content(**self._last_content)

    def update_content(self, *, status: str, status_color: str, progress: str,
                       uptime: str, tokens: str, steps: tuple[Any, ...],
                       current_stage: str, project: str, branch: str, pack: str,
                       adapter: str, selected_stage: str = "", view: str = "Live",
                       metrics: tuple[tuple[str, str], ...] = (), problems: tuple[str, ...] = (),
                       todo: str = "", agent_plan: Any = None,
                       plan_stage: str = "", plan_scope: str = "") -> None:
        from loopforge.cli.agent_plan import AgentPlan
        agent_plan = agent_plan if isinstance(agent_plan, AgentPlan) else AgentPlan()
        if plan_scope != getattr(self, "_plan_scope", None):
            self._plan_scope = plan_scope
            self._plan_expanded = True
        self._last_content = dict(status=status, status_color=status_color, progress=progress,
            uptime=uptime, tokens=tokens, steps=steps, current_stage=current_stage,
            project=project, branch=branch, pack=pack, adapter=adapter,
            selected_stage=selected_stage, view=view, metrics=metrics, problems=problems,
            todo=todo, agent_plan=agent_plan, plan_stage=plan_stage, plan_scope=plan_scope)
        activity = Text(status, style=status_color)
        activity.append(f"\n{current_stage}\nAdapter: {adapter}\n{project}")
        if todo:
            activity.append("\n" + todo)
        self.query_one("#run-context-configuration", Static).update(activity)
        problem_button = self.query_one("#run-problems", Button)
        problem_button.display = bool(problems)
        problem_button.label = Text(f"{len(problems)} problems · Inspect" if problems else "")
        problem_button.tooltip = "\n".join(problems)
        workflow = self.query_one("#run-context-steps", RunWorkflowList)
        valid_stage = plan_stage if agent_plan.items and any(stage.id == plan_stage for stage in steps) else ""
        workflow.plan_stage = valid_stage
        workflow.expanded = getattr(self, "_plan_expanded", True)
        workflow.toggle_plan = self._toggle_plan
        signature = (tuple((stage.id, stage.title, stage.family, str(stage.marker)) for stage in steps),
                     current_stage, selected_stage, valid_stage, agent_plan, workflow.expanded)
        if signature != getattr(self, "_workflow_signature", None):
            self._workflow_signature = signature
            chosen = (workflow.options[workflow.highlighted].id
                      if workflow.highlighted is not None and workflow.highlighted < len(workflow.options) else None)
            workflow.clear_options()
            for stage in steps:
                marker = terminal_marker(stage.marker)
                selected = "> " if stage.id == selected_stage else "  "
                active = " (active)" if stage.id == current_stage else ""
                line = Text(f"{selected}{marker} {stage.title}{active}", style=family_color(stage.family))
                if stage.id == valid_stage:
                    line.append(f"  {agent_plan.completed}/{agent_plan.count} ", style="#958EA0")
                    line.append(run_glyph("▾", "v") if workflow.expanded else run_glyph("▸", ">"), style="#D0BCFF")
                    if workflow.expanded:
                        for task in agent_plan.items:
                            symbol, shade = {
                                "completed": (run_glyph("✓", "+"), "#A8E6B0"),
                                "in_progress": (run_glyph("◉", "*"), "#D0BCFF"),
                                "pending": (run_glyph("○", "o"), "#958EA0"),
                                "failed": (run_glyph("×", "x"), "#FFB4AB"),
                                "unknown": ("?", "#958EA0"),
                            }[task.status]
                            line.append("\n      ")
                            line.append(symbol, style=shade)
                            line.append(" " + task.text, style="#CBC3D7")
                workflow.add_option(Option(line, id=stage.id))
            if chosen is not None:
                try:
                    workflow.highlighted = workflow.get_option_index(chosen)
                except Exception:
                    pass
        values = [("Status", status)]
        if progress not in {"—", "-", ""}:
            values.append(("Progress", progress))
        if uptime not in {"—", "-", ""}:
            values.append(("Uptime", uptime))
        values.extend(metrics)
        if tokens not in {"—", "-", ""}:
            values.append(("Tokens", tokens))
        text = Text()
        for label, value in values:
            if text:
                text.append("\n")
            text.append(label + ": ", style="#958EA0")
            text.append(value)
        self.query_one("#run-context-metrics", Static).update(text)
        self.query_one("#run-context-metrics-panel").display = bool(values)
        for name in ("Live", "Context", "Changes", "Evidences"):
            self.query_one("#run-view-" + name.lower(), Button).set_class(name == view, "selected")


class RunHotkeyBar(Horizontal):
    """Persistent keyboard guidance for the live run surface."""

    def compose(self) -> ComposeResult:
        movement = "Up/Down" if ascii_only() else "↑↓"
        yield Static(f"Tab Navigate  F4 Detail  F6 Views  / Command  End Follow", id="run-hotkeys-left")
        yield Static("Esc Runs   ^q Quit", id="run-hotkeys-right")


class RunDashboard(Vertical):
    """The dedicated live view for one supervised run."""

    def __init__(self) -> None:
        super().__init__(id="run-dashboard")

    def compose(self) -> ComposeResult:
        yield RunHeader(id="run-header")
        with Horizontal(id="run-shell"):
            with Vertical(id="run-main"):
                yield Static("", id="run-compact-context")
                yield Button("Supervision · F6", id="run-compact-tabs", classes="run-link")
                with Horizontal(id="run-selection"):
                    yield Static("", id="run-selection-stage", markup=False)
                    yield Select([], allow_blank=True, prompt="No attempt yet", id="run-session-select")
                with Horizontal(id="run-reading-controls"):
                    for mode in ("Focused", "All", "Raw"):
                        yield Button(mode, id="run-mode-" + mode.lower(), classes="run-link")
                    yield Button("Follow live", id="run-follow", classes="run-link")
                with Horizontal(id="run-changes-controls"):
                    yield Button("Attempt", id="run-diff-attempt", classes="run-link")
                    yield Button("Run cumulative", id="run-diff-cumulative", classes="run-link")
                yield RunActivityFeed()
                yield RunDocumentView(id="run-document-view")
                yield RunChangesExplorer(id="run-changes-explorer")
                yield RunRequiredAction()
                yield RunCommandBar()
            yield RunContextSidebar(id="run-context")
        yield RunHotkeyBar(id="run-hotkeys")
