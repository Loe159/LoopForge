"""Tests for loopforge.engine.process_runner."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from loopforge.engine.process_runner import ProcessRunner, ProcessReceipt


_IS_WINDOWS = os.name == "nt"
_IS_POSIX = os.name == "posix"


class NormalCompletionTests(unittest.TestCase):
    def test_simple_echo_returns_correct_receipt(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
        receipt = runner.run(
            [sys.executable, "-c", "print('hello')"],
            cwd=Path.cwd(),
        )
        self.assertTrue(receipt.completed)
        self.assertFalse(receipt.timed_out)
        self.assertFalse(receipt.output_limit_exceeded)
        self.assertFalse(receipt.kill_requested)
        self.assertEqual(receipt.returncode, 0)
        self.assertIn("hello", receipt.stdout)
        self.assertEqual(receipt.stderr, "")
        self.assertFalse(receipt.output_truncated)
        self.assertGreater(receipt.started_at, 0)
        self.assertGreater(receipt.finished_at, receipt.started_at)
        self.assertIsNotNone(receipt.pid)
        self.assertEqual(receipt.issue, "")


class StdoutBoundedTests(unittest.TestCase):
    def test_infinite_stdout_bounded_to_limit(self) -> None:
        runner = ProcessRunner(output_limit_bytes=50000, timeout=10)
        receipt = runner.run(
            [sys.executable, "-c", "while True: print('x' * 1000)"],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.output_limit_exceeded)
        self.assertFalse(receipt.timed_out)
        self.assertTrue(receipt.kill_requested)
        self.assertTrue(receipt.output_truncated)
        self.assertEqual(receipt.issue, "output_limit")
        self.assertLessEqual(len(receipt.stdout), 50000)


class TimeoutTests(unittest.TestCase):
    def test_timeout_kills_process(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=1.0)
        receipt = runner.run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.timed_out)
        self.assertFalse(receipt.output_limit_exceeded)
        self.assertTrue(receipt.kill_requested)
        self.assertEqual(receipt.issue, "timeout")
        self.assertLess(receipt.finished_at - receipt.started_at, 15)

    @unittest.skipUnless(_IS_POSIX, "process group termination is POSIX-only")
    def test_timeout_kills_process_tree_posix(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=2.0)
        script = (
            "import os, sys, time; "
            "pid = os.fork(); "
            "if pid == 0: time.sleep(60); "
            "else: time.sleep(60)"
        )
        receipt = runner.run(
            [sys.executable, "-c", script],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.timed_out)

    @unittest.skipUnless(_IS_WINDOWS, "taskkill tree termination is Windows-only")
    def test_timeout_kills_process_tree_windows(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=2.0)
        script = (
            "import subprocess, time; "
            "p = subprocess.Popen(['python', '-c', 'time.sleep(60)']); "
            "time.sleep(60)"
        )
        receipt = runner.run(
            [sys.executable, "-c", script],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.timed_out)


class CancellationTests(unittest.TestCase):
    def test_cancel_event_stops_process(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=30)
        cancel_event = threading.Event()
        receipt_container: list[ProcessReceipt] = []

        def run_in_thread() -> None:
            r = runner.run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=Path.cwd(),
                cancel_event=cancel_event,
            )
            receipt_container.append(r)

        t = threading.Thread(target=run_in_thread)
        t.start()
        time.sleep(1.0)
        cancel_event.set()
        t.join(timeout=15)

        self.assertEqual(len(receipt_container), 1)
        receipt = receipt_container[0]
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.kill_requested)
        self.assertEqual(receipt.issue, "cancellation")


class StdinClosedTests(unittest.TestCase):
    def test_stdin_closed_by_default_gives_eof(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
        receipt = runner.run(
            [sys.executable, "-c", "import sys; data = sys.stdin.read(); print('got:', repr(data))"],
            cwd=Path.cwd(),
        )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.returncode, 0)
        self.assertIn("got: ''", receipt.stdout)


class LaunchFailureTests(unittest.TestCase):
    def test_nonexistent_executable_gives_proper_receipt(self) -> None:
        runner = ProcessRunner()
        receipt = runner.run(
            ["/nonexistent/path/to/executable_xyzzy"],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "launch_failure")
        self.assertEqual(receipt.returncode, None)
        self.assertIsNone(receipt.pid)


class LargeOutputRingBufferTests(unittest.TestCase):
    def test_output_near_limit_preserved_excess_truncated(self) -> None:
        limit = 5000
        runner = ProcessRunner(output_limit_bytes=limit, timeout=10)
        receipt = runner.run(
            [
                sys.executable,
                "-c",
                "import sys; "
                "sys.stdout.write('A' * 4000); "
                "sys.stdout.flush(); "
                "sys.stdout.write('B' * 4000); "
                "sys.stdout.flush()",
            ],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.output_limit_exceeded)
        self.assertTrue(receipt.output_truncated)
        self.assertLessEqual(len(receipt.stdout), limit)


class ProcessReceiptFieldsTests(unittest.TestCase):
    def test_normal_completion_all_fields_populated(self) -> None:
        runner = ProcessRunner()
        receipt = runner.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('err'); sys.stdout.write('out')"],
            cwd=Path.cwd(),
        )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.returncode, 0)
        self.assertIn("out", receipt.stdout)
        self.assertIn("err", receipt.stderr)
        self.assertFalse(receipt.timed_out)
        self.assertFalse(receipt.output_limit_exceeded)
        self.assertFalse(receipt.kill_requested)
        self.assertFalse(receipt.output_truncated)
        self.assertGreater(receipt.finished_at, receipt.started_at)
        self.assertIsNotNone(receipt.pid)
        self.assertTrue(receipt.children_terminated)
        self.assertEqual(receipt.issue, "")


class SpoolDirTests(unittest.TestCase):
    def test_spool_dir_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spool = Path(tmpdir) / "spool"
            runner = ProcessRunner(spool_dir=spool)
            receipt = runner.run(
                [sys.executable, "-c", "print('spooled')"],
                cwd=Path.cwd(),
            )
            self.assertTrue(receipt.completed)
            self.assertIsNotNone(receipt.spool_path)
            self.assertTrue(receipt.spool_path.exists())


class InvalidCommandTests(unittest.TestCase):
    def test_empty_command_fails_cleanly(self) -> None:
        runner = ProcessRunner()
        receipt = runner.run([], cwd=Path.cwd())
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "launch_failure")

    def test_nonzero_return_not_completed(self) -> None:
        runner = ProcessRunner()
        receipt = runner.run(
            [sys.executable, "-c", "import sys; sys.exit(1)"],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.returncode, 1)
        self.assertFalse(receipt.timed_out)
        self.assertEqual(receipt.issue, "")


if __name__ == "__main__":
    unittest.main()