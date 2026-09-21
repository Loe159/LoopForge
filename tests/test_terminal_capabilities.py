"""Tests for the central terminal-capability module (S0.2)."""

from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from loopforge.cli.terminal_capabilities import (
    TerminalCapabilities,
    detect_capabilities,
    detect_width,
    width_class_for,
)


class WidthClassTests(unittest.TestCase):
    """The four responsive breakpoints used by the TUI CSS."""

    def test_breakpoints(self) -> None:
        self.assertEqual(width_class_for(59), "width-60")
        self.assertEqual(width_class_for(60), "width-60")
        self.assertEqual(width_class_for(79), "width-60")
        self.assertEqual(width_class_for(80), "width-80")
        self.assertEqual(width_class_for(119), "width-80")
        self.assertEqual(width_class_for(120), "width-120")
        self.assertEqual(width_class_for(159), "width-120")
        self.assertEqual(width_class_for(160), "width-160")
        self.assertEqual(width_class_for(200), "width-160")


class DetectWidthTests(unittest.TestCase):
    def test_override_takes_precedence(self) -> None:
        self.assertEqual(detect_width(io.StringIO(), override=100), 100)

    def test_columns_env(self) -> None:
        output = io.StringIO()  # not a TTY
        with mock.patch.dict(os.environ, {"COLUMNS": "132"}):
            self.assertEqual(detect_width(output), 132)

    def test_fallback_when_nothing_available(self) -> None:
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"COLUMNS": ""}, clear=False):
            # get_terminal_size will still return something on a real terminal,
            # but we at least confirm the function does not crash.
            width = detect_width(output)
            self.assertGreater(width, 0)


class DetectCapabilitiesTests(unittest.TestCase):
    """Matrix: the three rendering axes (rich/plain, colour, ascii) × modes."""

    def _no_env(self) -> dict:
        """Environment with all colour/ascii vars removed."""
        env = dict(os.environ)
        for key in ("NO_COLOR", "LOOPFORGE_NO_COLOR", "FORCE_COLOR", "TERM", "LOOPFORGE_ASCII", "COLUMNS"):
            env.pop(key, None)
        return env

    # ── colour suppression ──────────────────────────────────────────────

    def test_no_color_env_suppresses_rich(self) -> None:
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            caps = detect_capabilities(io.StringIO(), mode="rich")
            self.assertFalse(caps.use_rich)
            self.assertTrue(caps.no_color)

    def test_loopforge_no_color_env_suppresses_rich(self) -> None:
        with mock.patch.dict(os.environ, {"LOOPFORGE_NO_COLOR": "1"}, clear=False):
            caps = detect_capabilities(io.StringIO(), mode="rich")
            self.assertFalse(caps.use_rich)
            self.assertTrue(caps.no_color)

    def test_term_dumb_suppresses_rich(self) -> None:
        with mock.patch.dict(os.environ, {"TERM": "dumb"}, clear=False):
            caps = detect_capabilities(io.StringIO(), mode="rich")
            self.assertFalse(caps.use_rich)
            self.assertTrue(caps.no_color)

    def test_explicit_no_color_flag_suppresses_rich(self) -> None:
        caps = detect_capabilities(io.StringIO(), mode="rich", no_color=True)
        self.assertFalse(caps.use_rich)
        self.assertTrue(caps.no_color)

    def test_plain_flag_suppresses_rich(self) -> None:
        caps = detect_capabilities(io.StringIO(), mode="rich", plain=True)
        self.assertFalse(caps.use_rich)
        self.assertTrue(caps.no_color)

    # ── Rich enabling ───────────────────────────────────────────────────

    def test_force_color_enables_rich_without_tty(self) -> None:
        env = self._no_env()
        env["FORCE_COLOR"] = "1"
        with mock.patch.dict(os.environ, env, clear=True):
            caps = detect_capabilities(io.StringIO(), mode="auto")
            self.assertTrue(caps.use_rich)
            self.assertFalse(caps.no_color)

    def test_rich_mode_uses_rich_when_available(self) -> None:
        with mock.patch.dict(os.environ, self._no_env(), clear=True):
            caps = detect_capabilities(io.StringIO(), mode="rich", rich_available=True)
        self.assertTrue(caps.use_rich)

    def test_auto_mode_without_tty_or_force_is_plain(self) -> None:
        env = self._no_env()
        with mock.patch.dict(os.environ, env, clear=True):
            caps = detect_capabilities(io.StringIO(), mode="auto")
            self.assertFalse(caps.use_rich)

    # ── ASCII ───────────────────────────────────────────────────────────

    def test_loopforge_ascii_detected(self) -> None:
        with mock.patch.dict(os.environ, {"LOOPFORGE_ASCII": "1"}):
            caps = detect_capabilities(io.StringIO())
            self.assertTrue(caps.ascii_only)

    def test_loopforge_ascii_off_by_default(self) -> None:
        env = self._no_env()
        with mock.patch.dict(os.environ, env, clear=True):
            caps = detect_capabilities(io.StringIO())
            self.assertFalse(caps.ascii_only)

    # ── width integration ───────────────────────────────────────────────

    def test_width_class_in_caps(self) -> None:
        caps = detect_capabilities(io.StringIO(), width_override=60)
        self.assertEqual(caps.width, 60)
        self.assertEqual(caps.width_class, "width-60")

        caps = detect_capabilities(io.StringIO(), width_override=120)
        self.assertEqual(caps.width_class, "width-120")

    # ── capabilities is immutable ───────────────────────────────────────

    def test_capabilities_is_frozen(self) -> None:
        caps = detect_capabilities(io.StringIO())
        with self.assertRaises(Exception):
            caps.use_rich = True  # type: ignore[misc]


class TerminalRendererDelegationTests(unittest.TestCase):
    """Confirm TerminalRenderer delegates to the module (behaviour preserved)."""

    def test_plain_mode_emits_no_ansi(self) -> None:
        from loopforge.cli.ui import TerminalRenderer

        output = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            renderer = TerminalRenderer(output, mode="rich")
            renderer.print("[bold]hello[/]")
        self.assertNotIn("\x1b[", output.getvalue())
        self.assertIn("hello", output.getvalue())

    def test_rich_mode_forces_styles_for_tests(self) -> None:
        from loopforge.cli.ui import TerminalRenderer

        output = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            os.environ.pop("LOOPFORGE_NO_COLOR", None)
            os.environ.pop("TERM", None)
            renderer = TerminalRenderer(output, mode="rich")
            self.assertTrue(renderer.use_rich)


if __name__ == "__main__":
    unittest.main()
