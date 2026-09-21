from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from loopforge.adapters.commands import (
    InteractiveAdapterUnavailable,
    interactive_implementation_command,
    interactive_stage_command,
)
from loopforge.engine.terminal import (
    TerminalLaunchRequest,
    TerminalSessionResult,
    WindowsTerminalLauncher,
    _normalize_windows_terminal_command,
    default_terminal_launcher,
)
from loopforge.engine import execute_attempt
from loopforge.cli.parser import CliParserBuilder


class InteractiveAdapterCommandTests(unittest.TestCase):
    def test_codex_interactive_command_removes_headless_flags(self) -> None:
        command = interactive_implementation_command(
            adapter="codex",
            adapter_args=["exec", "--json", "--color", "never", "-m", "gpt-5"],
            workspace_dir=Path("C:/worktree"),
            prompt="Implement the approved plan.",
        )

        self.assertEqual(command[0], "codex")
        self.assertNotIn("exec", command)
        self.assertNotIn("--json", command)
        self.assertNotIn("--color", command)
        self.assertEqual(command[-1], "Implement the approved plan.")
        self.assertIn("--cd", command)
        self.assertIn(str(Path("C:/worktree")), command)

    def test_codex_interactive_command_forces_run_worktree_and_sandbox(self) -> None:
        command = interactive_implementation_command(
            adapter="codex",
            adapter_args=[
                "--cd=C:/control-checkout",
                "-C",
                "C:/other-checkout",
                "--sandbox",
                "danger-full-access",
                "--add-dir",
                "C:/outside",
                "--yolo",
                "--skip-git-repo-check",
                "--output-last-message",
                "C:/result.txt",
            ],
            workspace_dir=Path("C:/worktree"),
            prompt="Implement the approved plan.",
        )

        self.assertEqual(command.count("--cd"), 1)
        self.assertEqual(command[command.index("--cd") + 1], str(Path("C:/worktree")))
        self.assertEqual(command.count("-s"), 1)
        self.assertEqual(command[command.index("-s") + 1], "workspace-write")
        self.assertNotIn("C:/control-checkout", command)
        self.assertNotIn("C:/other-checkout", command)
        self.assertNotIn("C:/outside", command)
        self.assertNotIn("--yolo", command)
        self.assertNotIn("--skip-git-repo-check", command)
        self.assertNotIn("C:/result.txt", command)

    def test_claude_interactive_command_removes_print_mode(self) -> None:
        command = interactive_implementation_command(
            adapter="claude-code",
            adapter_args=[
                "-p",
                "--fallback-model",
                "haiku",
                "--max-budget-usd",
                "1.00",
                "--json-schema",
                "{}",
                "--allow-dangerously-skip-permissions",
                "--dangerously-skip-permissions",
                "--permission-mode",
                "bypassPermissions",
                "--add-dir",
                "C:/outside-one",
                "C:/outside-two",
                "--model",
                "sonnet",
            ],
            workspace_dir=Path("C:/worktree"),
            prompt="Implement the approved plan.",
        )

        self.assertEqual(
            command,
            ["claude", "--model", "sonnet", "Implement the approved plan."],
        )

    def test_kilo_interactive_command_uses_documented_interactive_mode(self) -> None:
        command = interactive_implementation_command(
            adapter="kilo-code",
            adapter_args=[
                "run",
                "--dangerously-skip-permissions",
                "--attach",
                "http://localhost:4096",
                "--file",
                "C:/outside-one.txt",
                "C:/outside-two.txt",
                "--model",
                "openai/gpt-5",
                "--format",
                "json",
                "--thinking",
            ],
            workspace_dir=Path("C:/worktree"),
            prompt="Implement the approved plan.",
        )

        self.assertEqual(command[:3], ["kilo", "run", "--interactive"])
        self.assertIn("--dir", command)
        self.assertIn("--agent", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertNotIn("--attach", command)
        self.assertNotIn("http://localhost:4096", command)
        self.assertNotIn("--file", command)
        self.assertNotIn("C:/outside-one.txt", command)
        self.assertNotIn("C:/outside-two.txt", command)
        self.assertNotIn("--format", command)
        self.assertNotIn("--thinking", command)
        self.assertEqual(command[-1], "Implement the approved plan.")

    def test_opencode_interactive_command_removes_headless_prompt(self) -> None:
        command = interactive_implementation_command(
            adapter="opencode",
            adapter_args=[
                "run",
                "--auto",
                "--prompt",
                "old prompt",
                "--dir",
                "C:/outside",
                "--format",
                "json",
                "--password",
                "secret",
                "--username",
                "runner",
                "--variant",
                "high",
                "--model",
                "fast",
            ],
            workspace_dir=Path("C:/worktree"),
            prompt="Implement the approved plan.",
        )

        self.assertEqual(
            command,
            [
                "opencode",
                "--model",
                "fast",
                "--prompt",
                "Implement the approved plan.",
            ],
        )

    def test_unsupported_interactive_adapter_requests_headless_fallback(self) -> None:
        with self.assertRaises(InteractiveAdapterUnavailable):
            interactive_implementation_command(
                adapter="aider",
                adapter_args=[],
                workspace_dir=Path("C:/worktree"),
                prompt="Implement the approved plan.",
            )

    def test_readonly_stage_uses_same_interactive_harness_contract(self) -> None:
        command = interactive_stage_command(
            adapter="codex",
            adapter_args=["exec", "--json", "--color", "never"],
            workspace_dir=Path("C:/worktree"),
            prompt="Write research to .loopforge/runtime-stages/research-candidate.md.",
        )

        self.assertEqual(command[0], "codex")
        self.assertNotIn("exec", command)
        self.assertNotIn("--json", command)
        self.assertIn("workspace-write", command)
        self.assertEqual(
            command[-1],
            "Write research to .loopforge/runtime-stages/research-candidate.md.",
        )

    def test_continue_parser_exposes_terminal_headless_choice(self) -> None:
        args = CliParserBuilder().build().parse_args(
            ["continue", "--adapter", "codex", "--execution-mode", "headless"]
        )

        self.assertEqual(args.execution_mode, "headless")

    def test_run_creation_rejects_stage_execution_flags(self) -> None:
        from loopforge.cli.errors import CliUsageError

        with self.assertRaises(CliUsageError):
            CliParserBuilder().build().parse_args(["run", "--execution-mode", "headless"])


class TerminalLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = mock.Mock()
        import shutil
        original_which = shutil.which
        def find_executable(name, *args, **kwargs):
            if name in {"powershell.exe", "powershell"}:
                return str(Path(sys.executable).resolve())
            return original_which(name, *args, **kwargs)
        powershell = mock.patch("loopforge.engine.terminal.shutil.which", side_effect=find_executable)
        powershell.start()
        self.addCleanup(powershell.stop)
        patcher = mock.patch(
            "loopforge.engine.terminal._WindowsJob.create", return_value=self.job
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self) -> tuple[str, ...]:
        return (str(Path(sys.executable).resolve()), "prompt")

    def test_default_launcher_selects_windows_terminal_launcher(self) -> None:
        launcher = default_terminal_launcher(platform="win32")

        self.assertIsInstance(launcher, WindowsTerminalLauncher)

    def test_windows_launcher_opens_new_console_and_waits(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            request = TerminalLaunchRequest(
                command=self.command(),
                cwd=root,
                title="LoopForge attempt-001",
                timeout_seconds=30,
                artifacts_dir=root / "artifacts",
                cancel_event=threading.Event(),
            )
            process = mock.Mock()
            process.poll.return_value = 0
            process.returncode = 0
            with mock.patch(
                "loopforge.engine.terminal.subprocess.Popen", return_value=process
            ) as popen:
                result = WindowsTerminalLauncher().launch(request)

        self.assertTrue(result.launched)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(popen.call_args.kwargs["creationflags"] & 0x00000010)
        self.assertEqual(popen.call_args.kwargs["cwd"], root)

    def test_windows_launcher_mirrors_bridge_output_when_callback_is_present(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            chunks: list[tuple[str, bytes]] = []
            connection = mock.Mock()
            connection.recv_bytes.side_effect = [b"Reasoning\r\n", EOFError]
            listener = mock.Mock()
            listener.accept.return_value = connection
            process = mock.Mock()
            process.poll.return_value = 0
            process.returncode = 0
            with (
                mock.patch(
                    "loopforge.engine.terminal.Listener", return_value=listener
                ),
                mock.patch(
                    "loopforge.engine.terminal.subprocess.Popen", return_value=process
                ) as popen,
            ):
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        cancel_event=threading.Event(),
                        output_chunk_callback=lambda stream, chunk: chunks.append(
                            (stream, chunk)
                        ),
                    )
                )

        launcher_command = popen.call_args.args[0]
        self.assertEqual(Path(launcher_command[1]).name, "terminal_bridge.py")
        self.assertEqual(chunks, [("stdout", b"Reasoning\r\n")])
        self.assertEqual(result.output, b"Reasoning\r\n")

    def test_windows_command_wraps_kilo_cmd_for_conpty(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            kilo = root / "kilo.cmd"
            comspec = root / "cmd.exe"
            kilo.touch()
            comspec.touch()

            command = _normalize_windows_terminal_command(
                [str(kilo), "run", "--interactive", "prompt"],
                {"COMSPEC": str(comspec), "PATH": str(root)},
            )

        self.assertEqual(command[:4], [str(comspec.resolve()), "/d", "/s", "/c"])
        self.assertEqual(command[4], str(kilo))

    def test_windows_launcher_passes_only_the_requested_environment(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            process = mock.Mock()
            process.poll.return_value = 0
            process.returncode = 0
            with mock.patch(
                "loopforge.engine.terminal.subprocess.Popen", return_value=process
            ) as popen:
                WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        environment={"PATH": "safe-path", "SYSTEMROOT": "C:/Windows"},
                    )
                )

        self.assertEqual(
            popen.call_args.kwargs["env"],
            {"PATH": "safe-path", "SYSTEMROOT": "C:/Windows"},
        )

    def test_non_windows_launcher_reports_extensible_unavailability(self) -> None:
        launcher = default_terminal_launcher(platform="linux")
        with TemporaryDirectory() as temp:
            root = Path(temp)
            result = launcher.launch(
                TerminalLaunchRequest(
                    command=self.command(),
                    cwd=root,
                    title="LoopForge attempt-001",
                    timeout_seconds=30,
                    artifacts_dir=root / "artifacts",
                )
            )

        self.assertFalse(result.launched)
        self.assertIn("not implemented", result.error.lower())

    def test_windows_launcher_cancellation_terminates_the_terminal_process_tree(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cancelled = mock.Mock()
            cancelled.is_set.side_effect = [False, False, True]
            process = mock.Mock()
            process.pid = 4321
            process.poll.side_effect = [None, 1]
            process.returncode = 1
            with (
                mock.patch(
                    "loopforge.engine.terminal.subprocess.Popen", return_value=process
                ),
                mock.patch("loopforge.engine.terminal.subprocess.run") as run,
            ):
                self.job.terminate.side_effect = OSError("job termination failed")
                run.return_value.returncode = 0
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        cancel_event=cancelled,
                    )
                )

        self.assertTrue(result.interrupted)
        run.assert_called_once_with(
            ["taskkill.exe", "/PID", "4321", "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=10,
        )

    def test_preflight_cancellation_does_not_create_a_terminal_process(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cancelled = threading.Event()
            cancelled.set()
            with mock.patch("loopforge.engine.terminal.subprocess.Popen") as popen:
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        cancel_event=cancelled,
                    )
                )

        self.assertFalse(result.launched)
        self.assertTrue(result.interrupted)
        popen.assert_not_called()

    def test_cancellation_before_handshake_never_releases_the_harness(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cancelled = mock.Mock()
            cancelled.is_set.side_effect = [False, True]
            process = mock.Mock()
            process.poll.return_value = None
            process.returncode = 1
            with mock.patch(
                "loopforge.engine.terminal.subprocess.Popen", return_value=process
            ):
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        cancel_event=cancelled,
                    )
                )
            start_path = root / "artifacts" / "terminal-session.start"
            self.assertFalse(start_path.exists())

        self.assertFalse(result.launched)
        self.assertTrue(result.interrupted)
        self.job.terminate.assert_called_once_with()

    def test_windows_launcher_timeout_terminates_the_terminal_process_tree(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            process = mock.Mock()
            process.pid = 4321
            process.poll.side_effect = [None, 1]
            process.returncode = 1
            with (
                mock.patch(
                    "loopforge.engine.terminal.subprocess.Popen", return_value=process
                ),
                mock.patch("loopforge.engine.terminal.subprocess.run") as run,
                mock.patch(
                    "loopforge.engine.terminal.time.monotonic", side_effect=[0.0, 2.0]
                ),
            ):
                self.job.terminate.side_effect = OSError("job termination failed")
                run.return_value.returncode = 0
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=1,
                        artifacts_dir=root / "artifacts",
                    )
                )

        self.assertTrue(result.timed_out)
        run.assert_called_once()

    def test_windows_job_object_terminates_descendants_without_taskkill(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cancelled = mock.Mock()
            cancelled.is_set.side_effect = [False, False, True]
            process = mock.Mock()
            process.pid = 4321
            process.poll.side_effect = [None, 1]
            process.returncode = 1
            job = mock.Mock()
            with (
                mock.patch(
                    "loopforge.engine.terminal.subprocess.Popen", return_value=process
                ),
                mock.patch(
                    "loopforge.engine.terminal._WindowsJob.create", return_value=job
                ),
                mock.patch("loopforge.engine.terminal.subprocess.run") as run,
            ):
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                        cancel_event=cancelled,
                    )
                )

        self.assertTrue(result.interrupted)
        job.assign.assert_called_once_with(process)
        job.terminate.assert_called_once_with()
        job.close.assert_called_once_with()
        run.assert_not_called()

    def test_failed_taskkill_is_retried_before_wrapper_termination(self) -> None:
        process = mock.Mock()
        process.pid = 4321
        process.poll.return_value = None
        result = mock.Mock(returncode=1, stderr=b"access denied")

        with mock.patch("loopforge.engine.terminal.subprocess.run", return_value=result) as run:
            error = WindowsTerminalLauncher._terminate_process_tree(process)

        self.assertEqual(run.call_count, 2)
        process.terminate.assert_called_once_with()
        self.assertEqual(error, "access denied")

    def test_terminated_wrapper_is_killed_if_bounded_wait_expires(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="wrapper", timeout=5),
            None,
        ]

        WindowsTerminalLauncher._wait_for_terminated_process(process, self.job)

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.job.close.assert_called_once_with()

    def test_job_assignment_failure_never_releases_the_wrapper(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            process = mock.Mock()
            process.poll.return_value = None
            process.returncode = 1
            self.job.assign.side_effect = OSError("assignment denied")
            with mock.patch(
                "loopforge.engine.terminal.subprocess.Popen", return_value=process
            ):
                result = WindowsTerminalLauncher().launch(
                    TerminalLaunchRequest(
                        command=self.command(),
                        cwd=root,
                        title="LoopForge attempt-001",
                        timeout_seconds=30,
                        artifacts_dir=root / "artifacts",
                    )
                )

            start_path = root / "artifacts" / "terminal-session.start"
            self.assertFalse(start_path.exists())

        self.assertFalse(result.launched)
        self.assertIn("supervision", result.error)
        process.terminate.assert_called_once_with()

    def test_keyboard_interrupt_terminates_the_terminal_process_tree(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            process = mock.Mock()
            process.pid = 4321
            process.poll.side_effect = [None, None]
            process.returncode = 1
            with (
                mock.patch(
                    "loopforge.engine.terminal.subprocess.Popen", return_value=process
                ),
                mock.patch("loopforge.engine.terminal.subprocess.run") as run,
                mock.patch("loopforge.engine.terminal.time.sleep", side_effect=KeyboardInterrupt),
            ):
                self.job.terminate.side_effect = OSError("job termination failed")
                run.return_value.returncode = 0
                with self.assertRaises(KeyboardInterrupt):
                    WindowsTerminalLauncher().launch(
                        TerminalLaunchRequest(
                            command=self.command(),
                            cwd=root,
                            title="LoopForge attempt-001",
                            timeout_seconds=30,
                            artifacts_dir=root / "artifacts",
                        )
                    )

        run.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)


class TerminalAttemptIntegrationTests(unittest.TestCase):
    def run_data(self, workspace: Path) -> dict[str, object]:
        return {
            "run_id": "run-terminal-test",
            "task_id": "task-terminal-test",
            "task": "Implement the approved plan.",
            "project_root": str(workspace),
            "base_commit": "0" * 40,
            "profile": "supervised",
            "workspace": {"mode": "git-worktree", "path": str(workspace)},
            "limits": {"max_attempts": 3, "timeout_seconds": 30},
            "success_checks": ["terminal change exists"],
            "pack_contract": {},
        }

    def contract_data(self) -> dict[str, object]:
        return {
            "success_checks": ["terminal change exists"],
            "allowed_tools": ["Write bounded changes."],
            "limits": {"max_attempts": 3, "timeout_seconds": 30},
        }

    def test_execute_attempt_supervises_terminal_then_detects_changes(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "terminal-change.txt").write_text("changed\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                    launcher_command=("test-terminal",),
                )

            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["execution_mode"], "terminal")
        self.assertEqual(attempt["terminal_launcher"], "test-terminal")
        self.assertTrue(attempt["workspace_changed"])

    def test_terminal_attempt_observes_hooks_and_retains_the_raw_console(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            events: list[dict[str, object]] = []
            console_output = b"Thinking about the implementation.\r\nTool call: edit file\r\n"

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                self.assertIsNotNone(request.output_chunk_callback)
                request.output_chunk_callback("stdout", console_output)
                from loopforge.adapters.observation_hook import record_hook
                record_hook({"cwd": str(request.cwd), "session_id": "test-session",
                             "hook_event_name": "Stop",
                             "last_assistant_message": "Thinking about the implementation."},
                            Path(request.environment["LOOPFORGE_OBSERVATION_DIR"]), request.cwd)
                (request.cwd / "terminal-change.txt").write_text(
                    "changed\n", encoding="utf-8"
                )
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                    output=console_output,
                )

            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=mock.Mock(launch=mock.Mock(side_effect=launch)),
                operation_callback=events.append,
            )

            persisted = (run_dir / str(attempt["stdout_path"])).read_bytes()

        self.assertEqual(persisted, console_output)
        self.assertTrue(
            any(
                event.get("kind") == "adapter_output"
                and "Thinking about the implementation." in str(event.get("message"))
                for event in events
            )
        )

    def test_control_c_exit_with_changes_completes_the_attempt(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "completed-before-exit.txt").touch()
                return TerminalSessionResult(
                    launched=True,
                    returncode=0xC000013A,
                    launcher="test-terminal",
                )

            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["returncode"], 0xC000013A)
        self.assertTrue(attempt["workspace_changed"])

    def test_successful_retry_accepts_changes_from_failed_attempt(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (workspace / "carried-change.txt").touch()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            run = self.run_data(workspace)
            run["status"] = "adapter_blocked"
            run["attempts"] = [
                {
                    "id": "attempt-001",
                    "status": "failed",
                    "workspace_changed": True,
                    "workspace_changes": ["A carried-change.txt"],
                }
            ]
            launcher = mock.Mock()
            launcher.launch.return_value = TerminalSessionResult(
                launched=True,
                returncode=0,
                launcher="test-terminal",
            )

            with (
                mock.patch(
                    "loopforge.engine.git_status_entries",
                    side_effect=[
                        ["?? carried-change.txt"],
                        ["?? carried-change.txt"],
                    ],
                ),
                mock.patch(
                    "loopforge.engine.git_status_paths",
                    side_effect=[
                        {"carried-change.txt"},
                        {"carried-change.txt"},
                    ],
                ),
            ):
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=run,
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

        self.assertEqual(attempt["id"], "attempt-002")
        self.assertEqual(attempt["status"], "completed")
        self.assertTrue(attempt["workspace_changed"])
        self.assertIn("?? carried-change.txt", attempt["workspace_changes"])

    def test_execute_attempt_filters_parent_secrets_from_terminal_environment(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                self.assertIsNotNone(request.environment)
                self.assertNotIn("LOOPFORGE_TEST_SECRET", request.environment)
                (request.cwd / "terminal-change.txt").write_text("changed\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            launcher.launch.side_effect = launch
            with mock.patch.dict(
                os.environ, {"LOOPFORGE_TEST_SECRET": "sentinel-value"}, clear=False
            ):
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

        self.assertEqual(attempt["status"], "completed")

    def test_terminal_attempt_stages_full_prompt_and_sends_short_reference(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            run = self.run_data(workspace)
            run["task"] = "x" * 40_000
            observed_prompt = ""
            staged_prompt = ""
            staged_path: Path | None = None

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                nonlocal observed_prompt, staged_prompt, staged_path
                observed_prompt = request.command[-1]
                self.assertLess(len(observed_prompt), 1_000)
                self.assertIn(".loopforge/runtime-prompts/", observed_prompt)
                prompt_reference = observed_prompt.split(" in ", 1)[1].split(
                    ". Treat", 1
                )[0]
                staged_path = request.cwd / prompt_reference
                staged_prompt = staged_path.read_text(encoding="utf-8")
                self.assertGreater(len(staged_prompt), 32_000)
                self.assertIn("## Embedded Run Inputs", staged_prompt)
                (request.cwd / "terminal-change.txt").write_text("changed\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=run,
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=mock.Mock(launch=mock.Mock(side_effect=launch)),
            )

            self.assertEqual(attempt["status"], "completed")
            self.assertEqual(attempt["result_origin"], "loopforge")
            self.assertGreater(len(staged_prompt), 32_000)
            self.assertIsNotNone(staged_path)
            self.assertFalse(staged_path.exists())

    def test_terminal_attempt_rejects_linked_prompt_directory(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            with mock.patch(
                "loopforge.engine.execution._path_is_reparse_point",
                side_effect=lambda path: path.name == ".loopforge",
            ):
                with self.assertRaisesRegex(ValueError, "staging directory is unsafe"):
                    execute_attempt(
                        project_dir=workspace,
                        run_dir=run_dir,
                        run=self.run_data(workspace),
                        contract=self.contract_data(),
                        adapter="codex",
                        adapter_args=[],
                        implementation_mode="terminal",
                        terminal_launcher=launcher,
                    )

            launcher.launch.assert_not_called()

    def test_terminal_noop_does_not_reuse_preexisting_git_changes(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            (workspace / "preexisting.txt").write_text("dirty\n", encoding="utf-8")
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.launch.return_value = TerminalSessionResult(
                launched=True,
                returncode=0,
                launcher="test-terminal",
            )

            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "blocked")
        self.assertFalse(attempt["workspace_changed"])
        self.assertEqual(attempt["workspace_changes"], [])

    def test_terminal_ignored_artifacts_do_not_count_as_implementation_changes(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            (workspace / ".gitignore").write_text(".pytest_cache/\n", encoding="utf-8")
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                cache = request.cwd / ".pytest_cache"
                cache.mkdir()
                (cache / "state").write_text("generated\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            launcher = mock.Mock()
            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "blocked")
        self.assertFalse(attempt["workspace_changed"])
        self.assertEqual(attempt["workspace_changes"], [])

    def test_terminal_commit_counts_as_an_implementation_change(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "config", "user.email", "loopforge@example.invalid"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "LoopForge Test"],
                cwd=workspace,
                check=True,
            )
            (workspace / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "base"], cwd=workspace, check=True
            )
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "committed.txt").write_text("changed\n", encoding="utf-8")
                subprocess.run(["git", "add", "committed.txt"], cwd=request.cwd, check=True)
                subprocess.run(
                    ["git", "commit", "-q", "-m", "implementation"],
                    cwd=request.cwd,
                    check=True,
                )
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            launcher = mock.Mock()
            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertTrue(attempt["workspace_changed"])
        self.assertIn("A\tcommitted.txt", attempt["workspace_changes"])

    def test_terminal_detects_unicode_git_paths(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "café.py").write_text("changed = True\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            launcher = mock.Mock()
            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertIn("A café.py", attempt["workspace_changes"])

    def test_terminal_detects_changes_below_a_gitlink_status_path(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            nested = workspace / "vendor" / "module"
            nested.mkdir(parents=True)
            run_dir.mkdir()
            (nested / "code.py").write_text("before = True\n", encoding="utf-8")
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "vendor" / "module" / "code.py").write_text(
                    "after = True\n", encoding="utf-8"
                )
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            launcher.launch.side_effect = launch
            with (
                mock.patch(
                    "loopforge.engine.git_status_entries",
                    side_effect=[[" M vendor/module"], [" M vendor/module"]],
                ),
                mock.patch(
                    "loopforge.engine.git_status_paths",
                    side_effect=[{"vendor/module"}, {"vendor/module"}],
                ),
                mock.patch(
                    "loopforge.engine.nested_git_fingerprints",
                    side_effect=[
                        {"vendor/module": ("a" * 40, (("code.py", (1, 1)),))},
                        {"vendor/module": ("a" * 40, (("code.py", (2, 2)),))},
                    ],
                ),
            ):
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

        self.assertEqual(attempt["status"], "completed")
        self.assertIn("M vendor/module/code.py", attempt["workspace_changes"])

    def test_terminal_ignores_non_git_churn_below_a_dirty_gitlink(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            nested = workspace / "vendor" / "module"
            nested.mkdir(parents=True)
            run_dir.mkdir()
            (nested / "code.py").write_text("dirty = True\n", encoding="utf-8")
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                cache = request.cwd / "vendor" / "module" / ".cache"
                cache.mkdir()
                (cache / "state").write_text("generated\n", encoding="utf-8")
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="test-terminal",
                )

            fingerprint = {"vendor/module": ("a" * 40, (("code.py", (1, 1)),))}
            launcher.launch.side_effect = launch
            with (
                mock.patch(
                    "loopforge.engine.git_status_entries",
                    side_effect=[[" M vendor/module"], [" M vendor/module"]],
                ),
                mock.patch(
                    "loopforge.engine.git_status_paths",
                    side_effect=[{"vendor/module"}, {"vendor/module"}],
                ),
                mock.patch(
                    "loopforge.engine.nested_git_fingerprints",
                    side_effect=[fingerprint, fingerprint],
                ),
            ):
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

        self.assertEqual(attempt["status"], "blocked")
        self.assertEqual(attempt["workspace_changes"], [])

    def test_terminal_cancellation_produces_valid_failed_result(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.launch.return_value = TerminalSessionResult(
                launched=True,
                returncode=1,
                interrupted=True,
                launcher="test-terminal",
            )

            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "failed")
        self.assertTrue(attempt["interrupted"])
        self.assertIsNone(attempt["contract_validation_error"])

    def test_auto_mode_falls_back_to_headless_for_unsupported_adapter(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")

            def execute_headless(**kwargs: object) -> tuple[dict[str, object], bytes, bytes]:
                result_output = Path(str(kwargs["result_output"]))
                session_path = Path(str(kwargs["expected_session_path"]))
                session = json.loads(session_path.read_text(encoding="utf-8"))
                (workspace / "headless-change.txt").write_text("changed\n", encoding="utf-8")
                result_output.write_text(
                    json.dumps(
                        {
                            **session,
                            "result_version": 1,
                            "purpose": "implementation_session_result",
                            "mode": "untrusted-runner-output",
                            "status": "completed",
                            "summary": "Headless fallback completed.",
                            "workspace_changed": True,
                            "patch_generated": False,
                            "deterministic_checks_run": False,
                            "publication_requested": False,
                            "network_requested": False,
                            "next_action": "deterministic_patch_generation",
                        }
                    ),
                    encoding="utf-8",
                )
                return ({"completed": True, "returncode": 0}, b"", b"")

            with mock.patch(
                "loopforge.engine.execute_adapter_command", side_effect=execute_headless
            ) as execute:
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="aider",
                    adapter_args=[],
                    implementation_mode="auto",
                )

        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["execution_mode"], "headless")
        self.assertIn("does not define", attempt["terminal_fallback_reason"])

    def test_forced_terminal_rejects_unsupported_adapter_before_attempt_creation(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")

            with self.assertRaises(InteractiveAdapterUnavailable):
                execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="aider",
                    adapter_args=[],
                    implementation_mode="terminal",
                )

            self.assertFalse((run_dir / "attempts").exists())

    def test_forced_terminal_launcher_failure_does_not_fall_back(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.name = "unavailable-test-terminal"
            launcher.launch.return_value = TerminalSessionResult(
                launched=False,
                returncode=None,
                launcher="unavailable-test-terminal",
                error="No desktop terminal is available.",
            )

            with mock.patch("loopforge.engine.execute_adapter_command") as execute:
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

            stderr = (run_dir / str(attempt["stderr_path"])).read_text(encoding="utf-8")

        self.assertEqual(attempt["execution_mode"], "terminal")
        self.assertEqual(attempt["status"], "failed")
        self.assertIn("No desktop terminal is available.", stderr)
        execute.assert_not_called()

    def test_auto_mode_falls_back_when_platform_launcher_cannot_start(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.name = "unavailable-test-terminal"
            launcher.launch.return_value = TerminalSessionResult(
                launched=False,
                returncode=None,
                launcher="unavailable-test-terminal",
                error="No desktop terminal is available.",
            )

            def execute_headless(**kwargs: object) -> tuple[dict[str, object], bytes, bytes]:
                session = json.loads(
                    Path(str(kwargs["expected_session_path"])).read_text(encoding="utf-8")
                )
                (workspace / "fallback-change.txt").write_text("changed\n", encoding="utf-8")
                Path(str(kwargs["result_output"])).write_text(
                    json.dumps(
                        {
                            **session,
                            "result_version": 1,
                            "purpose": "implementation_session_result",
                            "mode": "untrusted-runner-output",
                            "status": "completed",
                            "summary": "Headless fallback completed.",
                            "workspace_changed": True,
                            "patch_generated": False,
                            "deterministic_checks_run": False,
                            "publication_requested": False,
                            "network_requested": False,
                            "next_action": "deterministic_patch_generation",
                        }
                    ),
                    encoding="utf-8",
                )
                return ({"completed": True, "returncode": 0}, b"", b"")

            with mock.patch(
                "loopforge.engine.execute_adapter_command", side_effect=execute_headless
            ) as execute:
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="auto",
                    terminal_launcher=launcher,
                )

        self.assertEqual(attempt["execution_mode"], "headless")
        self.assertEqual(attempt["terminal_launcher"], "unavailable-test-terminal")
        self.assertEqual(attempt["terminal_fallback_reason"], "No desktop terminal is available.")
        launcher.launch.assert_called_once()
        execute.assert_called_once()

    def test_auto_mode_does_not_fallback_after_terminal_cancellation(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            cancelled = threading.Event()
            cancelled.set()
            launcher = mock.Mock()
            launcher.name = "cancelled-test-terminal"
            launcher.launch.return_value = TerminalSessionResult(
                launched=False,
                returncode=None,
                interrupted=True,
                launcher="cancelled-test-terminal",
            )

            with mock.patch("loopforge.engine.execute_adapter_command") as execute:
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="auto",
                    terminal_launcher=launcher,
                    cancel_event=cancelled,
                )

        self.assertEqual(attempt["execution_mode"], "terminal")
        self.assertEqual(attempt["status"], "failed")
        self.assertTrue(attempt["interrupted"])
        execute.assert_not_called()

    def test_late_cancel_signal_does_not_discard_successful_terminal_result(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            cancelled = threading.Event()
            launcher = mock.Mock()
            launcher.name = "late-cancel-test-terminal"

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "terminal-change.txt").write_text(
                    "changed\n", encoding="utf-8"
                )
                cancelled.set()
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="late-cancel-test-terminal",
                )

            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="auto",
                terminal_launcher=launcher,
                cancel_event=cancelled,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertFalse(attempt["interrupted"])

    def test_git_initialized_and_committed_during_session_counts_as_change(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.name = "git-init-test-terminal"

            def launch(request: TerminalLaunchRequest) -> TerminalSessionResult:
                (request.cwd / "committed.txt").write_text("changed\n", encoding="utf-8")
                subprocess.run(["git", "init"], cwd=request.cwd, check=True, capture_output=True)
                subprocess.run(
                    ["git", "add", "committed.txt"],
                    cwd=request.cwd,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=LoopForge Test",
                        "-c",
                        "user.email=loopforge@example.invalid",
                        "commit",
                        "-m",
                        "test",
                    ],
                    cwd=request.cwd,
                    check=True,
                    capture_output=True,
                )
                return TerminalSessionResult(
                    launched=True,
                    returncode=0,
                    launcher="git-init-test-terminal",
                )

            launcher.launch.side_effect = launch
            attempt = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(attempt["status"], "completed")
        self.assertIn("A committed.txt", attempt["workspace_changes"])

    def test_keyboard_interrupt_is_persisted_and_retry_uses_next_attempt(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.name = "interrupt-test-terminal"
            launcher.launch.side_effect = KeyboardInterrupt

            first = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

            retry_run = self.run_data(workspace)
            retry_run["attempts"] = [first]
            launcher.launch.side_effect = None
            launcher.launch.return_value = TerminalSessionResult(
                launched=True,
                returncode=0,
                launcher="interrupt-test-terminal",
            )
            second = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=retry_run,
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(first["status"], "failed")
        self.assertTrue(first["interrupted"])
        self.assertEqual(second["id"], "attempt-002")

    def test_setup_failure_preserves_diagnostics_without_blocking_retry(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            launcher = mock.Mock()
            launcher.name = "setup-failure-test-terminal"
            launcher.launch.side_effect = RuntimeError("launcher setup failed")

            with self.assertRaisesRegex(RuntimeError, "launcher setup failed"):
                execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="codex",
                    adapter_args=[],
                    implementation_mode="terminal",
                    terminal_launcher=launcher,
                )

            launcher.launch.side_effect = None
            launcher.launch.return_value = TerminalSessionResult(
                launched=True,
                returncode=0,
                launcher="setup-failure-test-terminal",
            )
            second = execute_attempt(
                project_dir=workspace,
                run_dir=run_dir,
                run=self.run_data(workspace),
                contract=self.contract_data(),
                adapter="codex",
                adapter_args=[],
                implementation_mode="terminal",
                terminal_launcher=launcher,
            )

        self.assertEqual(second["id"], "attempt-002")

    def test_cancelled_unsupported_adapter_does_not_start_headless_fallback(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            run_dir = root / "run"
            workspace.mkdir()
            run_dir.mkdir()
            (run_dir / "progress.md").write_text("# Progress\n\n", encoding="utf-8")
            cancelled = threading.Event()
            cancelled.set()

            with mock.patch("loopforge.engine.execute_adapter_command") as execute:
                attempt = execute_attempt(
                    project_dir=workspace,
                    run_dir=run_dir,
                    run=self.run_data(workspace),
                    contract=self.contract_data(),
                    adapter="aider",
                    adapter_args=[],
                    implementation_mode="auto",
                    cancel_event=cancelled,
                )

        self.assertEqual(attempt["status"], "failed")
        self.assertTrue(attempt["interrupted"])
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
