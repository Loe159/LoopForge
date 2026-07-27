"""Tests for rendering isolation: no I/O during TUI render.

Covers Subtask 5 of Epic 3: no subprocess.run, open(), or filesystem
access should occur during the TUI render path.
"""

from __future__ import annotations

import importlib.util
import unittest
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class RenderingIsolationTests(unittest.TestCase):
    """Verify no I/O occurs during snapshot construction and flush."""

    def test_uisnapshot_is_frozen(self) -> None:
        from loopforge.cli.models import (
            EvidenceSnapshot,
            HomeSnapshot,
            OperationSnapshot,
            ProjectSnapshot,
            RunSnapshot,
            SettingsSnapshot,
            UiSnapshot,
        )

        self.assertTrue(is_dataclass(UiSnapshot))
        snapshot = UiSnapshot(
            revision=1,
            reasons=(),
            selected_project=None,
            selected_run_id=None,
            home=HomeSnapshot("ready"),
            project=ProjectSnapshot("ready"),
            run=RunSnapshot("empty"),
            evidence=EvidenceSnapshot("empty"),
            settings=SettingsSnapshot(),
            operation=OperationSnapshot(),
        )
        with self.assertRaises(FrozenInstanceError):
            snapshot.revision = 999

    def test_state_store_flush_does_not_do_io(self) -> None:
        """StateStore.flush should only read in-memory fields."""

        from loopforge.cli.state_store import StateStore

        store = StateStore(
            Path("/tmp"),
            status_loader=lambda path: None,
            runs_loader=lambda status: None,
            projects_loader=lambda: None,
            global_runs_loader=lambda: None,
            branch_loader=lambda path: "",
        )
        with mock.patch("subprocess.run") as mock_run, mock.patch(
            "builtins.open", create=True
        ) as mock_open:
            store.flush()
            mock_run.assert_not_called()
            mock_open.assert_not_called()

    def test_worker_loads_before_publish(self) -> None:
        """Workers must capture identity before publishing."""

        from loopforge.cli.state_store import LoadIdentity, StateStore

        store = StateStore(
            Path("/tmp"),
            status_loader=lambda path: None,
            runs_loader=lambda status: None,
            projects_loader=lambda: None,
            global_runs_loader=lambda: None,
            branch_loader=lambda path: "",
        )
        identity = store.begin_load()
        self.assertIsNotNone(identity)
        self.assertTrue(store.accepts(identity))


@unittest.skipUnless(
    importlib.util.find_spec("textual") is not None,
    "Textual is an installed runtime dependency",
)
class AdapterDiagnosticsCacheTests(unittest.TestCase):
    """The render path must reuse cached adapter diagnostics, never re-probing PATH."""

    def test_adapter_diagnostics_probes_path_once_then_caches(self) -> None:
        from loopforge.cli.textual_app import LoopForgeApp

        shell = SimpleNamespace(project_dir=Path.cwd(), theme="default")
        app = LoopForgeApp(shell, load_on_mount=False)

        with mock.patch(
            "loopforge.cli.textual_app.app.shutil.which", return_value="/usr/local/bin/agent"
        ) as mock_which:
            first = app._adapter_diagnostics()
            calls_after_first = mock_which.call_count
            self.assertGreater(calls_after_first, 0)

            second = app._adapter_diagnostics()
            third = app._adapter_diagnostics()

            # The cache must prevent any additional PATH probes on the render path.
            self.assertEqual(mock_which.call_count, calls_after_first)
            self.assertEqual(first, second)
            self.assertEqual(second, third)


if __name__ == "__main__":
    unittest.main()
