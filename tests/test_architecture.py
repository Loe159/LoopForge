"""Architecture guard tests: no circular dependencies, no CLI imports from engine submodules.

Covers Subtask 6 of Epic 3: dependencies must be acyclic, engine must not
import from CLI, and no code outside engine should access engine private symbols.
"""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


class EngineImportDirectionTests(unittest.TestCase):
    """Engine modules must never import from CLI."""

    ENGINE_MODULES = [
        "loopforge.engine",
        "loopforge.engine.installation",
        "loopforge.engine.project_service",
        "loopforge.engine.workflow",
        "loopforge.engine.memory",
        "loopforge.engine.artifacts",
        "loopforge.engine.run_service",
        "loopforge.engine.execution",
        "loopforge.engine.stages",
        "loopforge.engine.verification",
        "loopforge.engine.status_service",
        "loopforge.engine.workspace",
        "loopforge.engine.rendering",
        "loopforge.engine.adapter_runtime",
    ]

    def test_no_engine_module_imports_cli(self):
        """No engine module should import from loopforge.cli."""
        for module_name in self.ENGINE_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                source_file = Path(module.__file__)
                tree = ast.parse(source_file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertFalse(
                                alias.name.startswith("loopforge.cli"),
                                f"{module_name} imports {alias.name} from CLI"
                            )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("loopforge.cli"):
                            self.fail(f"{module_name} imports from {node.module} (CLI)")


class NoPrivateAccessTests(unittest.TestCase):
    """No code outside engine should access engine private (_prefixed) symbols."""

    def _engine_source_files(self):
        engine_dir = SRC_ROOT / "loopforge" / "engine"
        return list(engine_dir.glob("*.py"))

    def test_cli_does_not_import_engine_private_symbols(self):
        """CLI code must not import _private symbols from loopforge.engine."""
        cli_dir = SRC_ROOT / "loopforge" / "cli"
        cli_files = list(cli_dir.glob("*.py")) + list((cli_dir / "textual_app").glob("*.py"))
        violations = []
        for py_file in cli_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module == "loopforge.engine" or (node.module and node.module.startswith("loopforge.engine.")):
                        for alias in node.names:
                            if alias.name.startswith("_"):
                                violations.append(f"{py_file.name}: from {node.module} import {alias.name}")
        self.assertFalse(violations, f"private symbol imports found:\n" + "\n".join(violations))


class EngineSubmoduleIndependenceTests(unittest.TestCase):
    """Engine submodules should not create circular imports at module load time."""

    def test_all_engine_modules_importable(self):
        """Every engine submodule must be importable without circular import errors."""
        for module_name in [
            "loopforge.engine",
            "loopforge.engine.installation",
            "loopforge.engine.project_service",
            "loopforge.engine.workflow",
            "loopforge.engine.memory",
            "loopforge.engine.artifacts",
            "loopforge.engine.run_service",
            "loopforge.engine.execution",
            "loopforge.engine.stages",
            "loopforge.engine.verification",
            "loopforge.engine.status_service",
            "loopforge.engine.workspace",
            "loopforge.engine.rendering",
            "loopforge.engine.adapter_runtime",
            "loopforge.engine.models",
            "loopforge.engine.models.scope",
            "loopforge.engine.models.pack",
            "loopforge.engine.models.project",
            "loopforge.engine.models.run",
            "loopforge.engine.models.lifecycle",
            "loopforge.engine.models.verification",
            "loopforge.engine.models.commands",
            "loopforge.engine.models.artifacts",
        ]:
            with self.subTest(module=module_name):
                mod = importlib.import_module(module_name)
                self.assertIsNotNone(mod)


class CommandsPackageTests(unittest.TestCase):
    """The commands package should be importable and self-contained."""

    def test_commands_importable(self):
        import loopforge.commands
        self.assertTrue(hasattr(loopforge.commands, 'execute_command'))

    def test_commands_do_not_import_cli(self):
        """Commands must not import from CLI."""
        commands_dir = SRC_ROOT / "loopforge" / "commands"
        for py_file in commands_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.startswith("loopforge.cli"),
                            f"{py_file.name} imports {alias.name} from CLI"
                        )


if __name__ == "__main__":
    unittest.main()
