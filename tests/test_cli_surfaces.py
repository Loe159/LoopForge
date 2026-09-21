"""Regressions for the two supported surfaces: Textual and explicit CLI commands."""

import ast
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.interactive import DispatchResult, InteractiveShell, run_interactive
from loopforge.engine import update_user_preferences, user_preferences, user_preferences_path


class CliSurfaceTests(unittest.TestCase):
    def test_cli_contains_no_prompt_input_loop(self):
        root = Path(__file__).resolve().parents[1] / "src" / "loopforge" / "cli"
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "input", str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("prompt_toolkit"), str(path))

    def test_guided_action_needs_explicit_confirmation_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(project / "home")}):
                session = InteractiveShell(project, output=io.StringIO(), error=io.StringIO())
                action = ActionDescriptor(
                    id="run-research", label="Research", description="Read only",
                    risk="read-only-agent", requires_confirmation=True, available=True,
                    command_fallback="research", executor_key="run-readonly-stage",
                )
                with (
                    mock.patch.object(session, "guidance_action", return_value=action),
                    mock.patch.object(session, "execute_guided_action", return_value=DispatchResult(0)) as execute,
                    mock.patch("builtins.input", side_effect=AssertionError("unexpected prompt")),
                ):
                    self.assertEqual(session.dispatch("/do run-research").exit_code, 1)
                    execute.assert_not_called()
                    self.assertEqual(session.dispatch("/do run-research --confirm --execution-mode headless").exit_code, 0)
                    self.assertEqual(execute.call_args.kwargs["implementation_mode"], "headless")
                with mock.patch.object(session, "guidance_action", return_value=None):
                    self.assertEqual(session.dispatch("/do run-research --confirm").exit_code, 1)

    def test_missing_textual_never_falls_back_to_a_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            errors = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(project / "home")}),
                mock.patch("loopforge.cli.interactive.tui_dependency_state", return_value={"rich": True, "textual": False}),
                mock.patch("builtins.input", side_effect=AssertionError("unexpected prompt")),
            ):
                self.assertEqual(run_interactive(project, output=io.StringIO(), error=errors), 1)
            self.assertIn("textual", errors.getvalue())
            self.assertIn("shell --command", errors.getvalue())

    def test_retired_preferences_are_ignored_without_losing_theme(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            preference_file = user_preferences_path(home=home)
            preference_file.parent.mkdir(parents=True)
            preference_file.write_text(
                '{"theme": "dark", "keymap": "vim", "statusline": "off"}', encoding="utf-8",
            )
            self.assertEqual(user_preferences(home=home), {"theme": "dark"})
            with self.assertRaises(ValueError):
                update_user_preferences({"keymap": "vim"}, home=home)
