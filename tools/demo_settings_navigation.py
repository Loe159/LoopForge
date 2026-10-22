"""Read-only Settings frame demo using the real widgets and synthetic diagnostics.

Run from the repository root:
    PYTHONPATH=src .venv/bin/python tools/demo_settings_navigation.py

Optional real Textual SVG captures (written only to the supplied directory):
    PYTHONPATH=src .venv/bin/python tools/demo_settings_navigation.py --capture /tmp/settings-review
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.settings import SettingsDashboard
from loopforge.engine import SUPPORTED_ADAPTERS


class SettingsNavigationDemo(LoopForgeApp):
    def __init__(self) -> None:
        super().__init__(
            SimpleNamespace(project_dir=Path.cwd(), theme="dark"), load_on_mount=False,
        )
        self._adapter_diagnostic_cache = {
            key: "non vérifié (données de démonstration)" for key in SUPPORTED_ADAPTERS
        }

    def on_mount(self) -> None:
        super().on_mount()
        self.action_show_settings()
        self.query_one("#settings-brand").update("LoopForge / Settings [démo]")


async def capture(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    app = SettingsNavigationDemo()
    async with app.run_test(size=(120, 30)) as pilot:
        for width in (48, 52, 60, 80, 100, 120, 160):
            await pilot.resize_terminal(width, 24)
            await pilot.pause()
            app.save_screenshot(f"settings-{width}x24.svg", path=str(directory))
        frame = app.query_one(SettingsDashboard)
        frame._select_section("autonomy")
        frame.action_focus_content()
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        app.save_screenshot("settings-autonomy-120x30.svg", path=str(directory))
        await pilot.resize_terminal(60, 24)
        frame.focus_navigation()
        await pilot.press("enter")
        await pilot.pause()
        app.save_screenshot("settings-menu-60x24.svg", path=str(directory))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    if args.capture:
        asyncio.run(capture(args.capture))
    else:
        SettingsNavigationDemo().run()
