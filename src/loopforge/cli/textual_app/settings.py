"""Global Settings frame and navigation; configuration remains read-only here."""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import DescendantFocus, Resize
from textual.message import Message
from textual.widgets import Button, OptionList, Select, Static
from textual.widgets.option_list import Option


SETTINGS_SECTIONS = (
    ("behavior", "Comportement", "Préférences générales et mode d’exécution de LoopForge."),
    ("harnesses", "Harness et modèles", "Installation des harness et valeurs de modèle par défaut."),
    ("workflow", "Étapes du workflow", "Affectation des harness et des modèles aux étapes agent."),
    ("autonomy", "Autonomie et limites", "Profils d’autonomie, règles par étape et limites des runs."),
    ("storage", "Données et stockage", "Emplacements de la configuration et des données LoopForge."),
    ("diagnostics", "Diagnostics", "Disponibilité locale et informations de diagnostic."),
)


class SettingsDashboard(Container):
    """A persistent rail, a compact native selector, and one scrollable content zone.

    Selection belongs to this widget, not the project/run cursor or StateStore.
    The application supplies factual content without changing user settings.
    """

    BINDINGS = [
        Binding("right", "focus_content", show=False),
        Binding("escape", "back", show=False),
    ]

    class BackRequested(Message):
        """Return to the screen that opened Settings."""

    def __init__(self) -> None:
        super().__init__(id="settings-dashboard")
        self.section_id = SETTINGS_SECTIONS[0][0]
        self._values: dict[str, Text] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-header"):
            yield Static("LoopForge / Settings", id="settings-brand")
            yield Static("Global", id="settings-scope")
            yield Button("Retour", id="settings-back")
        with Horizontal(id="settings-workspace"):
            with Container(id="settings-rail"):
                yield OptionList(
                    *(Option(title, id=key) for key, title, _ in SETTINGS_SECTIONS),
                    id="settings-navigation",
                )
                yield Static("Surcharges définies dans les packs.", id="settings-pack-scope")
            with Container(id="settings-main"):
                yield Select(
                    [(title, key) for key, title, _ in SETTINGS_SECTIONS],
                    value=self.section_id,
                    allow_blank=False,
                    compact=True,
                    id="settings-section-select",
                    tooltip="Choisir une rubrique de Settings",
                )
                with VerticalScroll(id="settings-content", can_focus=True):
                    yield Static("", id="settings-section-title", markup=False)
                    yield Static("", id="settings-description", markup=False)
                    yield Static("", id="settings-values", markup=False)
        yield Static("", id="settings-hotkeys", markup=False)

    def on_mount(self) -> None:
        self.query_one("#settings-rail").border_title = "Rubriques"
        self.query_one("#settings-content").border_title = "Comportement"
        from loopforge.cli.textual_app.run_presenter import ascii_only

        if ascii_only():
            picker = self.query_one("#settings-section-select", Select)
            picker.query_one(".down-arrow", Static).update("v")
            picker.query_one(".up-arrow", Static).update("^")
        self._show_section()

    def update_values(self, values: Mapping[str, Text]) -> None:
        """Refresh only data; retain selection, focus and scroll through snapshots."""

        if self._values == values:
            return
        self._values = dict(values)
        self._show_section()

    def _show_section(self) -> None:
        key, title, description = next(s for s in SETTINGS_SECTIONS if s[0] == self.section_id)
        content = self.query_one("#settings-content", VerticalScroll)
        content.border_title = title
        self.query_one("#settings-section-title", Static).update(title)
        self.query_one("#settings-description", Static).update(description)
        self.query_one("#settings-values", Static).update(self._values.get(key, Text()))
        self._update_focus()

    def _select_section(self, key: str) -> None:
        if key == self.section_id:
            return
        self.section_id = key
        index = next(i for i, item in enumerate(SETTINGS_SECTIONS) if item[0] == key)
        self.query_one("#settings-navigation", OptionList).highlighted = index
        self.query_one("#settings-section-select", Select).value = key
        self._show_section()
        self.query_one("#settings-content", VerticalScroll).scroll_home(animate=False)

    @on(OptionList.OptionHighlighted, "#settings-navigation")
    def _highlight_section(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        if event.option.id is not None:
            self._select_section(event.option.id)

    @on(OptionList.OptionSelected, "#settings-navigation")
    def _enter_section(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is not None:
            self._select_section(event.option.id)
        self.action_focus_content()

    @on(Select.Changed, "#settings-section-select")
    def _compact_section_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is not Select.NULL:
            self._select_section(str(event.value))

    @on(Button.Pressed, "#settings-back")
    def _back_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.BackRequested())

    def action_focus_content(self) -> None:
        self.query_one("#settings-content", VerticalScroll).focus()

    def focus_navigation(self) -> None:
        if self.has_class("settings-compact"):
            self.query_one("#settings-section-select", Select).focus()
        else:
            self.query_one("#settings-navigation", OptionList).focus()

    def action_back(self) -> None:
        focused = self.app.focused
        content = self.query_one("#settings-content", VerticalScroll)
        if focused is content or (focused is not None and content in focused.ancestors):
            self.focus_navigation()
        else:
            self.post_message(self.BackRequested())

    def on_descendant_focus(self, _event: DescendantFocus) -> None:
        self._update_focus()

    def _update_focus(self) -> None:
        navigation = self.query_one("#settings-navigation", OptionList)
        content = self.query_one("#settings-content", VerticalScroll)
        self.query_one("#settings-rail").set_class(navigation.has_focus, "focused")
        content.set_class(content.has_focus_within, "focused")
        in_content = content.has_focus_within
        hint = (
            "↑↓ défiler · Tab zones · Échap rubriques"
            if in_content else "↑↓ rubriques · Entrée contenu · Échap retour"
        )
        if not in_content and self.has_class("settings-compact"):
            hint = "Entrée rubriques · Tab contenu · Échap retour"
        # The capability helper is shared with the rest of the Textual UI.
        from loopforge.cli.textual_app.run_presenter import ascii_only

        if ascii_only():
            hint = hint.replace("↑↓", "Up/Down").replace("·", "|")
        self.query_one("#settings-hotkeys", Static).update(hint)

    def on_resize(self, event: Resize) -> None:
        compact = event.size.width < 100
        if compact == self.has_class("settings-compact"):
            return
        navigation = self.query_one("#settings-navigation", OptionList)
        picker = self.query_one("#settings-section-select", Select)
        owns_navigation = navigation.has_focus or picker.has_focus_within
        # A menu opened at narrow width must not survive invisibly after resize.
        picker.expanded = False
        self.set_class(compact, "settings-compact")
        if owns_navigation:
            self.call_after_refresh(self.focus_navigation)
