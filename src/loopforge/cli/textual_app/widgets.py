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
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList
from textual.widgets import Collapsible, Input, Static
from textual.widgets.option_list import Option

from loopforge.cli.textual_app.run_presenter import (
    ascii_only,
    family_color,
    run_glyph,
    semantic_color,
    terminal_marker,
    TranscriptEntry,
    agent_body_renderable,
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
    """A native call updated in place; expansion is owned by the reader."""

    def __init__(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        self.detail = Static(entry.body, markup=False)
        self.phase = 0
        super().__init__(self.detail, title="", collapsed=True,
                         collapsed_symbol=run_glyph("▸", ">"),
                         expanded_symbol=run_glyph("▾", "v"), classes="run-tool-entry")
        self.update_entry(entry)

    def update_entry(self, entry: TranscriptEntry) -> None:
        self.entry = entry
        self.detail.update(
            agent_body_renderable(entry.body or "No additional details.", tool_output=True)
        )
        self.set_class(entry.status == "failed", "tool-failed")
        self.refresh_title()

    def refresh_title(self) -> None:
        entry = self.entry
        if entry.status == "running":
            frames = "|/-\\" if ascii_only() else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            marker = frames[self.phase % len(frames)]
        else:
            marker = {"completed": run_glyph("✓", "+"), "failed": run_glyph("×", "x")}.get(entry.status, "?")
        title = Text(marker, style=semantic_color("danger") if entry.status == "failed" else
                     semantic_color("success") if entry.status == "completed" else "#958EA0")
        title.append(f" {entry.title}", style="#958EA0")
        if entry.summary:
            summary = " ".join(entry.summary.split())
            title.append(f"  {summary[:100]}", style="#958EA0")
        if entry.status == "failed":
            title.append("  Failed", style=semantic_color("danger"))
        elif entry.status == "unknown":
            title.append("  No result received", style="#958EA0")
        # Rich Text remains literal: tool names/commands are never markup.
        self.title = title


class RunAgentOutput(Vertical):
    """One incremental narrative, preserving tool widgets and keyboard focus."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transcript = Text()
        self._items: dict[str, Static | RunToolEntry] = {}
        self._entries: tuple[TranscriptEntry, ...] = ()
        self._scope: object = None

    def on_mount(self) -> None:
        self._spinner = self.set_interval(0.12, self._tick, pause=True)

    def _tick(self) -> None:
        for item in self._items.values():
            if isinstance(item, RunToolEntry) and item.entry.status == "running":
                item.phase += 1
                item.refresh_title()

    def update(self, value: Text, *, active: bool = True, scope: object = None) -> None:
        if scope != self._scope:
            for item in self._items.values():
                item.remove()
            self._items.clear()
            self._entries = ()
            self._scope = scope
        self.transcript = value
        entries = transcript_entries(value.plain)
        if not active:
            entries = tuple(replace(entry, status="unknown") if entry.status == "running" else entry
                            for entry in entries)
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
                if entry.kind == "tool":
                    item = RunToolEntry(entry)
                else:
                    text = Text()
                    if entry.kind == "message":
                        text.append("Agent\n", style="bold #E7E0ED")
                        body = agent_body_renderable(entry.body)
                        if isinstance(body, Text):
                            text.append_text(body)
                        else:
                            item = Static(
                                Group(Text("Agent", style="bold #E7E0ED"), body),
                                markup=False,
                                classes=f"run-entry-{entry.kind}",
                            )
                            self._items[entry.key] = item
                            self.mount(item)
                            continue
                    elif entry.kind == "reasoning":
                        text.append("Reasoning\n", style="italic #958EA0")
                        body = agent_body_renderable(entry.body)
                        if isinstance(body, Text):
                            body.stylize("#958EA0")
                            text.append_text(body)
                        else:
                            item = Static(
                                Group(Text("Reasoning", style="italic #958EA0"), body),
                                markup=False,
                                classes=f"run-entry-{entry.kind}",
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
            elif isinstance(item, RunToolEntry):
                item.update_entry(entry)
        if any(entry.status == "running" for entry in entries):
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

    def __init__(self) -> None:
        super().__init__(id="run-activity-feed")
        self._system_prompt: str | None = None
        self._implementation_contract: str | None = None
        self._adapter_title: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="run-attempt-heading")
        yield RunTranscriptPanel(
            "System Prompt",
            panel_id="run-system-prompt-panel",
            body_id="run-system-prompt",
        )
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
    ) -> None:
        ellipsis = "..." if ascii_only() else "…"
        self.query_one("#run-attempt-heading", Static).update(heading)
        prompt = (
            system_prompt
            or f"System prompt will appear when the attempt starts{ellipsis}"
        )
        if prompt != self._system_prompt:
            self.query_one("#run-system-prompt", Static).update(prompt)
            self._system_prompt = prompt
        self.query_one("#run-agent-output", RunAgentOutput).update(agent_output, active=active, scope=scope)
        contract_panel = self.query_one(
            "#run-implementation-panel", RunTranscriptPanel
        )
        contract = implementation_contract.strip()
        if contract != self._implementation_contract:
            self.query_one("#run-implementation-contract", Static).update(contract)
            self._implementation_contract = contract
        contract_panel.display = bool(contract)
        adapter_label = (adapter or "agent").replace("-", " ").title()
        adapter_title = f"Agent Output {'-' if ascii_only() else '•'} {adapter_label}"
        if adapter_title != self._adapter_title:
            self.query_one(
                "#run-agent-output-panel", RunTranscriptPanel
            ).update_title(adapter_title)
            self._adapter_title = adapter_title


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

    def update_action(self, action: Any | None, *, blocked: bool = False) -> None:
        self.display = action is not None
        if action is None:
            return
        title = (
            f"BLOCKED {run_glyph('—', '-')} ACTION REQUIRED"
            if blocked
            else "REQUIRED ACTION"
        )
        self.query_one("#run-action-title", Static).update(title)
        self.query_one("#run-action-description", Static).update(
            str(getattr(action, "description", "Review the current run before continuing."))
        )
        controls = Text()
        controls.append(" Enter ", style="bold #0A0A0A on #D0BCFF")
        controls.append(f"  {getattr(action, 'label', 'Continue')}")
        controls.append("    Ctrl+K ", style="#D0BCFF")
        controls.append("Other actions", style="#CBC3D7")
        self.query_one("#run-action-controls", Static).update(controls)


class RunContextPanel(Container):
    """Square, border-titled panel used within the fixed run sidebar."""

    def __init__(self, title: str, *, panel_id: str) -> None:
        super().__init__(id=panel_id, classes="run-context-panel")
        self.border_title = title


class RunContextSidebar(Vertical):
    """Fixed run facts sourced from the immutable presentation snapshot."""

    def compose(self) -> ComposeResult:
        yield Static("RUN CONTEXT", id="run-context-title")
        with Vertical(id="run-context-details"):
            with RunContextPanel("Metrics", panel_id="run-context-metrics-panel"):
                yield Static("", id="run-context-metrics")
            with RunContextPanel("Steps", panel_id="run-context-steps-panel"):
                yield Static("", id="run-context-steps")
            with RunContextPanel("Configuration", panel_id="run-context-configuration-panel"):
                yield Static("", id="run-context-configuration")
        with Vertical(id="run-view-tabs"):
            yield Static(f"{run_glyph('◉', '*')} Live", id="run-view-activity")
            yield Static(f"{run_glyph('▣', '#')} Changes", classes="run-view-disabled")
            yield Static(f"{run_glyph('▤', '=')} Evidences", classes="run-view-disabled")

    def update_content(
        self,
        *,
        status: str,
        status_color: str,
        progress: str,
        uptime: str,
        tokens: str,
        steps: tuple[Any, ...],
        current_stage: str,
        project: str,
        branch: str,
        pack: str,
        adapter: str,
    ) -> None:
        metrics = Text()
        for index, (label, value, color) in enumerate(
            (
                ("Status", status, status_color),
                ("Progress", progress, "#E7E0ED"),
                ("Uptime", uptime, "#E7E0ED"),
                (
                    "Tokens",
                    tokens,
                    semantic_color("attention") if tokens not in {"—", "-"} else "#958EA0",
                ),
            )
        ):
            if index:
                metrics.append("\n")
            metrics.append(f"{label + ':':<10}", style="#958EA0")
            metrics.append(value, style=color)
        self.query_one("#run-context-metrics", Static).update(metrics)

        stage_text = Text()
        for index, stage in enumerate(steps):
            if index:
                stage_text.append("\n")
            family = str(getattr(stage, "family", "waiting"))
            marker = terminal_marker(getattr(stage, "marker", "○"))
            is_current = str(getattr(stage, "id", "")) == current_stage
            color = family_color(family)
            title = str(getattr(stage, "title", "Unknown step"))
            line = f"{marker} {title}"
            if is_current:
                stage_text.append(line.ljust(34), style="bold #D0BCFF on #34264A")
            else:
                style = "strike #958EA0" if family == "complete" else color
                stage_text.append(line, style=style)
        if not steps:
            stage_text.append("No workflow steps.", style="#958EA0")
        self.query_one("#run-context-steps", Static).update(stage_text)

        configuration = Text()
        for index, (label, value) in enumerate(
            (
                ("Project", project),
                ("Git", branch),
                ("Pack", pack),
                ("Adapter", adapter),
            )
        ):
            if index:
                configuration.append("\n\n")
            configuration.append(label, style="bold #CBC3D7")
            configuration.append(f"\n{value}", style="#958EA0")
        self.query_one("#run-context-configuration", Static).update(configuration)


class RunHotkeyBar(Horizontal):
    """Persistent keyboard guidance for the live run surface."""

    def compose(self) -> ComposeResult:
        movement = "Up/Down" if ascii_only() else "↑↓"
        yield Static(f"{movement} Live   / Command   Ctrl+K Actions", id="run-hotkeys-left")
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
                compact_tabs = Text()
                compact_tabs.append(
                    f" {run_glyph('◉', '*')} Live ",
                    style="bold #0A0A0A on #D0BCFF",
                )
                compact_tabs.append(
                    f"  {run_glyph('▣', '#')} Changes unavailable",
                    style="#958EA0",
                )
                compact_tabs.append(
                    f"  {run_glyph('▤', '=')} Evidences unavailable",
                    style="#958EA0",
                )
                yield Static(compact_tabs, id="run-compact-tabs")
                yield RunActivityFeed()
                yield RunRequiredAction()
                yield RunCommandBar()
            yield RunContextSidebar(id="run-context")
        yield RunHotkeyBar(id="run-hotkeys")
