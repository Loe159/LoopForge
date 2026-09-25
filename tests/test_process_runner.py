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
from unittest import mock

from loopforge.engine.process_runner import ProcessRunner, ProcessReceipt
from loopforge.engine import process_runner


_IS_WINDOWS = os.name == "nt"
_IS_POSIX = os.name == "posix"


class WindowsCancellationApiTests(unittest.TestCase):
    def test_writer_pins_handle_before_cancellation(self) -> None:
        release = threading.Event()
        ready = threading.Event()
        opened: list[int] = []
        kernel32 = mock.Mock()
        kernel32.OpenThread.return_value = 123

        def worker_body() -> None:
            opened.append(process_runner._open_windows_writer_handle(kernel32))
            ready.set()
            release.wait()

        worker = threading.Thread(target=worker_body)
        worker.start()
        try:
            self.assertTrue(ready.wait(1))
            process_runner._cancel_windows_writer(opened[0], kernel32)
            kernel32.OpenThread.assert_called_once_with(0x0001, False, worker.native_id)
            kernel32.CancelSynchronousIo.assert_called_once_with(123)
            kernel32.CloseHandle.assert_not_called()
            kernel32.CloseHandle(opened[0])
            kernel32.CloseHandle.assert_called_once_with(123)
        finally:
            release.set()
            worker.join()


class NormalCompletionTests(unittest.TestCase):
    def test_simple_echo_returns_correct_receipt(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", "print('hello')"],
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
            [str(Path(sys.executable).resolve()), "-c", "while True: print('x' * 1000)"],
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
    def test_simulated_windows_handle_setup_race_never_writes_after_timeout(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        release = threading.Event()
        kernel32 = mock.Mock()

        def slow_open(api: object) -> int:
            release.wait(5)
            return 123

        try:
            with (
                mock.patch(
                    "loopforge.engine.process_runner.os.set_blocking",
                    side_effect=OSError("unsupported"),
                    create=True,
                ),
                mock.patch.object(process_runner, "_windows_cancel_api", return_value=kernel32),
                mock.patch.object(process_runner, "_open_windows_writer_handle", side_effect=slow_open),
                mock.patch("loopforge.engine.process_runner.os.write") as write,
            ):
                receipt = runner.run(
                    [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                    cwd=Path.cwd(),
                    stdin_data="x" * (2 * 1024 * 1024),
                )
            self.assertTrue(receipt.timed_out)
            self.assertTrue(receipt.stdin_cleanup_failed)
            self.assertLess(receipt.finished_at - receipt.started_at, 0.8)
            write.assert_not_called()
            kernel32.CancelSynchronousIo.assert_not_called()
        finally:
            release.set()
            for thread in threading.enumerate():
                if thread.name.startswith("loopforge-stdin-"):
                    thread.join(timeout=1)
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_simulated_windows_failed_cancel_reports_active_writer_promptly(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        release = threading.Event()
        kernel32 = mock.Mock()
        kernel32.OpenThread.return_value = 123

        def blocked_write(fd: int, data: bytes) -> int:
            release.wait(5)
            return len(data)

        try:
            with (
                mock.patch(
                    "loopforge.engine.process_runner.os.set_blocking",
                    side_effect=OSError("unsupported"),
                    create=True,
                ),
                mock.patch.object(process_runner, "_windows_cancel_api", return_value=kernel32),
                mock.patch("loopforge.engine.process_runner.os.write", side_effect=blocked_write),
            ):
                receipt = runner.run(
                    [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                    cwd=Path.cwd(),
                    stdin_data="x" * (2 * 1024 * 1024),
                )
            self.assertTrue(receipt.timed_out)
            self.assertTrue(receipt.stdin_cleanup_failed)
            self.assertFalse(receipt.completed)
            self.assertEqual(receipt.issue, "stdin_cleanup_failure")
            self.assertLess(receipt.finished_at - receipt.started_at, 0.8)
            self.assertTrue(
                any(
                    thread.name == f"loopforge-stdin-{receipt.pid}"
                    for thread in threading.enumerate()
                )
            )
            kernel32.CloseHandle.assert_not_called()
        finally:
            release.set()
            for thread in threading.enumerate():
                if thread.name.startswith("loopforge-stdin-"):
                    thread.join(timeout=1)
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_simulated_windows_cancel_interrupts_blocked_write(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        released = threading.Event()
        handle_opened = threading.Event()
        kernel32 = mock.Mock()
        kernel32.OpenThread.side_effect = lambda *_: (handle_opened.set(), 123)[1]
        kernel32.CancelSynchronousIo.side_effect = lambda *_: released.set()

        def blocked_write(fd: int, data: bytes) -> int:
            self.assertTrue(handle_opened.is_set())
            released.wait(1.5)
            return len(data)

        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=OSError("unsupported"),
                create=True,
            ),
            mock.patch.object(process_runner, "_windows_cancel_api", return_value=kernel32),
            mock.patch("loopforge.engine.process_runner.os.write", side_effect=blocked_write),
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
            )
        self.assertTrue(receipt.timed_out)
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)
        self.assertFalse(
            any(thread.name == f"loopforge-stdin-{receipt.pid}" for thread in threading.enumerate())
        )
        kernel32.CancelSynchronousIo.assert_called()
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_simulated_windows_cancellable_writer_times_out(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        kernel32 = mock.Mock()
        kernel32.OpenThread.return_value = 123
        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=OSError("unsupported"),
                create=True,
            ),
            mock.patch.object(process_runner, "_windows_cancel_api", return_value=kernel32),
            mock.patch.object(process_runner, "_cancel_windows_writer") as cancel_writer,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
            )
        self.assertTrue(receipt.timed_out)
        self.assertEqual(receipt.issue, "timeout")
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)
        self.assertFalse(
            any(thread.name == f"loopforge-stdin-{receipt.pid}" for thread in threading.enumerate())
        )
        cancel_writer.assert_called()
        kernel32.CloseHandle.assert_called_once_with(123)

    @unittest.skipUnless(_IS_WINDOWS, "Windows synchronous pipe cancellation")
    def test_windows_cancellable_writer_times_out_and_cleans_up(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        with mock.patch(
            "loopforge.engine.process_runner.os.set_blocking",
            side_effect=OSError("unsupported"),
            create=True,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
            )
        self.assertTrue(receipt.timed_out)
        self.assertFalse(
            any(thread.name == f"loopforge-stdin-{receipt.pid}" for thread in threading.enumerate())
        )

    def test_unavailable_nonblocking_stdin_refuses_before_slow_staging(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)

        def slow_staging(*args: object, **kwargs: object) -> mock.MagicMock:
            file = mock.MagicMock()
            file.write.side_effect = lambda data: time.sleep(0.4)
            return file

        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=OSError("unsupported"),
                create=True,
            ),
            mock.patch("loopforge.engine.process_runner.subprocess.Popen") as launch,
            mock.patch("tempfile.TemporaryFile", side_effect=slow_staging) as staging,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
            )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "launch_failure")
        self.assertIn("nonblocking stdin unavailable", receipt.stderr)
        self.assertIsNone(receipt.pid)
        self.assertLess(receipt.finished_at - receipt.started_at, 0.3)
        launch.assert_not_called()
        staging.assert_not_called()

    def test_missing_nonblocking_api_refuses_before_launch(self) -> None:
        runner = ProcessRunner(timeout=0.15)
        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=AttributeError("set_blocking"),
                create=True,
            ),
            mock.patch("loopforge.engine.process_runner.subprocess.Popen") as launch,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "print('should not run')"],
                cwd=Path.cwd(),
                stdin_data="hello",
            )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "launch_failure")
        launch.assert_not_called()

    @unittest.skipUnless(_IS_POSIX, "process group test requires POSIX fork")
    def test_unavailable_nonblocking_stdin_never_launches_descendant(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        script = "import os, time; os.fork(); os._exit(0)"
        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=OSError("unsupported"),
                create=True,
            ),
            mock.patch("loopforge.engine.process_runner.subprocess.Popen") as launch,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", script],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
            )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "launch_failure")
        self.assertIsNone(receipt.pid)
        launch.assert_not_called()

    @unittest.skipUnless(_IS_POSIX, "inherited pipe test requires POSIX fork")
    def test_exited_parent_with_descendant_holding_stdin_cleans_up_writer(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        open_fds = Path("/proc/self/fd")
        before_fds = len(list(open_fds.iterdir())) if open_fds.exists() else None
        script = (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    os.close(1)\n"
            "    os.close(2)\n"
            "    time.sleep(1.5)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", script],
            cwd=Path.cwd(),
            stdin_data="x" * (2 * 1024 * 1024),
        )
        self.assertTrue(receipt.timed_out)
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.issue, "timeout")
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)
        self.assertFalse(
            any(
                thread.name == f"loopforge-stdin-{receipt.pid}"
                for thread in threading.enumerate()
            )
        )
        if before_fds is not None:
            self.assertEqual(len(list(open_fds.iterdir())), before_fds)

    def test_timeout_applies_while_child_does_not_read_stdin(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=0.15)
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
            cwd=Path.cwd(),
            stdin_data="x" * (2 * 1024 * 1024),
        )
        self.assertTrue(receipt.timed_out)
        self.assertEqual(receipt.issue, "timeout")
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)

    def test_timeout_kills_process(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=1.0)
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(60)"],
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
            "import os, time\n"
            "os.fork()\n"
            "time.sleep(60)\n"
        )
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", script],
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
            [str(Path(sys.executable).resolve()), "-c", script],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertTrue(receipt.timed_out)


class CancellationTests(unittest.TestCase):
    def test_cancel_while_child_does_not_read_stdin(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=5)
        cancel_event = threading.Event()
        timer = threading.Timer(0.15, cancel_event.set)
        timer.start()
        try:
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(1.0)"],
                cwd=Path.cwd(),
                stdin_data="x" * (2 * 1024 * 1024),
                cancel_event=cancel_event,
            )
        finally:
            timer.cancel()
        self.assertTrue(receipt.kill_requested)
        self.assertEqual(receipt.issue, "cancellation")
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)

    def test_cancel_event_stops_process(self) -> None:
        runner = ProcessRunner(output_limit_bytes=100000, timeout=30)
        cancel_event = threading.Event()
        receipt_container: list[ProcessReceipt] = []

        def run_in_thread() -> None:
            r = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(30)"],
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
    def test_simulated_windows_cancellable_writer_delivers_small_input(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=5)
        kernel32 = mock.Mock()
        kernel32.OpenThread.return_value = 123
        with (
            mock.patch(
                "loopforge.engine.process_runner.os.set_blocking",
                side_effect=OSError("unsupported"),
                create=True,
            ),
            mock.patch.object(process_runner, "_windows_cancel_api", return_value=kernel32),
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import sys; print(sys.stdin.read())"],
                cwd=Path.cwd(),
                stdin_data="hello",
            )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.stdout.strip(), "hello")
        kernel32.CloseHandle.assert_called_once_with(123)

    @unittest.skipUnless(_IS_WINDOWS, "Windows synchronous pipe cancellation")
    def test_windows_cancellable_writer_delivers_small_input(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=5)
        with mock.patch(
            "loopforge.engine.process_runner.os.set_blocking",
            side_effect=OSError("unsupported"),
            create=True,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import sys; print(sys.stdin.read())"],
                cwd=Path.cwd(),
                stdin_data="hello",
            )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.stdout.strip(), "hello")

    def test_unavailable_nonblocking_stdin_does_not_affect_devnull(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=5)
        with mock.patch(
            "loopforge.engine.process_runner.os.set_blocking",
            side_effect=OSError("unsupported"),
            create=True,
        ):
            receipt = runner.run(
                [str(Path(sys.executable).resolve()), "-c", "import sys; print(len(sys.stdin.read()))"],
                cwd=Path.cwd(),
            )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.stdout.strip(), "0")

    def test_stdin_data_reaches_child_and_closes_at_eof(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=5)
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", "import sys; print(len(sys.stdin.read()))"],
            cwd=Path.cwd(),
            stdin_data="é" * 100000,
        )
        self.assertTrue(receipt.completed)
        self.assertEqual(receipt.stdout.strip(), "100000")

    def test_stdin_closed_by_default_gives_eof(self) -> None:
        runner = ProcessRunner(output_limit_bytes=10000, timeout=10)
        receipt = runner.run(
            [str(Path(sys.executable).resolve()), "-c", "import sys; data = sys.stdin.read(); print('got:', repr(data))"],
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
    def test_output_limit_applies_while_stdin_writer_is_blocked(self) -> None:
        runner = ProcessRunner(output_limit_bytes=5000, timeout=5)
        receipt = runner.run(
            [
                str(Path(sys.executable).resolve()),
                "-c",
                "import sys, time; sys.stdout.write('x' * 10000); "
                "sys.stdout.flush(); time.sleep(1.0)",
            ],
            cwd=Path.cwd(),
            stdin_data="x" * (2 * 1024 * 1024),
        )
        self.assertTrue(receipt.output_limit_exceeded)
        self.assertEqual(receipt.issue, "output_limit")
        self.assertLess(receipt.finished_at - receipt.started_at, 0.8)

    def test_output_near_limit_preserved_excess_truncated(self) -> None:
        limit = 5000
        runner = ProcessRunner(output_limit_bytes=limit, timeout=10)
        receipt = runner.run(
            [
                str(Path(sys.executable).resolve()),
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
            [str(Path(sys.executable).resolve()), "-c", "import sys; sys.stderr.write('err'); sys.stdout.write('out')"],
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
                [str(Path(sys.executable).resolve()), "-c", "print('spooled')"],
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
            [str(Path(sys.executable).resolve()), "-c", "import sys; sys.exit(1)"],
            cwd=Path.cwd(),
        )
        self.assertFalse(receipt.completed)
        self.assertEqual(receipt.returncode, 1)
        self.assertFalse(receipt.timed_out)
        self.assertEqual(receipt.issue, "")


if __name__ == "__main__":
    unittest.main()
