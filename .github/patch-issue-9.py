from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


engine_path = Path("src/loopforge/engine/__init__.py")
engine = engine_path.read_text(encoding="utf-8")

streaming_start = engine.index("def run_streaming_process(")
stream_write_marker = '''                else:
                    target.write(chunk)
                    target.flush()
'''
stream_write_replacement = '''                else:
                    binary_target = getattr(target, "buffer", None)
                    if binary_target is not None:
                        binary_target.write(chunk)
                        binary_target.flush()
                    else:
                        target.write(decode_output(chunk))
                        target.flush()
'''
streaming_prefix = engine[:streaming_start]
streaming_body = engine[streaming_start:]
streaming_body = replace_once(
    streaming_body,
    stream_write_marker,
    stream_write_replacement,
    "stream output",
)
streaming_body = replace_once(
    streaming_body,
    "        args=(process.stdout, sys.stdout.buffer, stdout_buffer),\n",
    "        args=(process.stdout, sys.stdout, stdout_buffer),\n",
    "stdout stream target",
)
streaming_body = replace_once(
    streaming_body,
    "        args=(process.stderr, sys.stderr.buffer, stderr_buffer),\n",
    "        args=(process.stderr, sys.stderr, stderr_buffer),\n",
    "stderr stream target",
)
engine = streaming_prefix + streaming_body

function_start = engine.index("def execute_attempt(")
execution_start = engine.index(
    '    if adapter == "local-adapter-fixture":\n',
    function_start,
)
execution_end_marker = (
    "        result = parse_adapter_result_file(result_path) "
    "or parse_adapter_result(stdout)\n"
)
execution_end = engine.index(execution_end_marker, execution_start) + len(
    execution_end_marker
)
replacement_execution = '''    result_path = attempt_dir / "result.json"
    protocol_command = adapter_protocol_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=prompt_path,
        result_output=result_path,
    )
    child, stdout, stderr = execute_adapter_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=prompt_path,
        result_output=result_path,
        timeout_seconds=timeout_seconds,
        operation_callback=operation_callback,
        cancel_event=cancel_event,
    )
    result = parse_adapter_result_file(result_path) or parse_adapter_result(stdout)
'''
engine = engine[:execution_start] + replacement_execution + engine[execution_end:]

result_start = engine.index(
    '    if adapter == "local-adapter-fixture":\n',
    execution_start + len(replacement_execution),
)
result_end_marker = "    elif interrupted:\n"
result_end = engine.index(result_end_marker, result_start) + len(result_end_marker)
engine = engine[:result_start] + "    if interrupted:\n" + engine[result_end:]

engine = replace_once(
    engine,
    '        "command": command,\n        "started_at": started,\n',
    '        "command": command,\n'
    '        "protocol_command": protocol_command,\n'
    '        "started_at": started,\n',
    "attempt protocol evidence",
)
engine_path.write_text(engine, encoding="utf-8")

adapter_path = Path("src/loopforge/adapters/local_implementation_adapter.py")
adapter = adapter_path.read_text(encoding="utf-8")
adapter = replace_once(
    adapter,
    '''    if completed.returncode != 0:
        raise ValueError("Local implementation adapter git command failed")
''',
    '''    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"Local implementation adapter git command failed{suffix}")
''',
    "git failure diagnostic",
)

git_status_start = adapter.index("def git_status_paths(")
command_basename_start = adapter.index("def command_basename(", git_status_start)
status_helpers = '''def git_status_paths(workspace: Path) -> list[str] | None:
    try:
        output = run_git(workspace, "status", "--porcelain=v1", "--untracked-files=all")
    except ValueError as error:
        if "not a git repository" in str(error).lower():
            return None
        raise
    paths: list[str] = []
    for raw_line in output.decode("utf-8", errors="replace").splitlines():
        if not raw_line:
            continue
        path = raw_line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        paths.append(path.replace("\\", "/"))
    return paths


def relevant_git_status_paths(paths: list[str], policy: dict[str, Any]) -> list[str]:
    ignored_prefixes = tuple(policy["ignored_workspace_status_prefixes"])
    return [
        path
        for path in paths
        if not any(
            path == prefix.rstrip("/") or path.startswith(prefix)
            for prefix in ignored_prefixes
        )
    ]


def workspace_file_snapshot(workspace: Path, policy: dict[str, Any]) -> dict[str, tuple[int, int]]:
    ignored_prefixes = tuple(policy["ignored_workspace_status_prefixes"])
    snapshot: dict[str, tuple[int, int]] = {}
    for path in workspace.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if any(
            relative == prefix.rstrip("/") or relative.startswith(prefix)
            for prefix in ignored_prefixes
        ):
            continue
        stat = path.stat()
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def workspace_dirty(workspace: Path, policy: dict[str, Any]) -> bool:
    paths = git_status_paths(workspace)
    return bool(relevant_git_status_paths(paths, policy)) if paths is not None else False


'''
adapter = adapter[:git_status_start] + status_helpers + adapter[command_basename_start:]

adapter = replace_once(
    adapter,
    '''    validate_command_allowed(command, session, policy)
    if policy["require_clean_workspace_at_start"] and workspace_dirty(workspace, policy):
        value = result_value(
''',
    '''    validate_command_allowed(command, session, policy)
    initial_git_paths = git_status_paths(workspace)
    initial_snapshot = (
        workspace_file_snapshot(workspace, policy)
        if initial_git_paths is None
        else None
    )
    if (
        policy["require_clean_workspace_at_start"]
        and initial_git_paths is not None
        and relevant_git_status_paths(initial_git_paths, policy)
    ):
        value = result_value(
''',
    "workspace preflight state",
)
adapter = replace_once(
    adapter,
    '''    output_size = len(completed.stdout or b"") + len(completed.stderr or b"")
    changed = workspace_dirty(workspace, policy)
''',
    '''    output_size = len(completed.stdout or b"") + len(completed.stderr or b"")
    current_git_paths = git_status_paths(workspace)
    if current_git_paths is None:
        changed = initial_snapshot != workspace_file_snapshot(workspace, policy)
    else:
        changed = bool(relevant_git_status_paths(current_git_paths, policy))
''',
    "workspace change state",
)
adapter_path.write_text(adapter, encoding="utf-8")

test_path = Path("tests/test_implementation_result_integrity.py")
tests = test_path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
if marker not in tests:
    raise SystemExit("test insertion marker not found")
if "test_public_continue_fixture_uses_protocol_wrapper" in tests:
    raise SystemExit("regression test already exists")

regression = r'''

    def test_public_continue_fixture_uses_protocol_wrapper(self) -> None:
        import contextlib
        import io
        import os
        import subprocess
        import sys

        from loopforge.cli import main
        from loopforge.engine import apply_initial_task_approval, apply_plan_approval

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            home = root / "home"
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=LoopForge Tests",
                    "-c",
                    "user.email=loopforge@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=project,
                check=True,
                capture_output=True,
            )

            previous = Path.cwd()
            try:
                os.chdir(project)
                with (
                    mock.patch.dict(os.environ, {"LOOPFORGE_HOME": str(home)}),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(main(["init"]), 0)
                    self.assertEqual(
                        main(
                            [
                                "run",
                                "--task",
                                "Exercise the fixture wrapper",
                                "--success-check",
                                "README changed",
                            ]
                        ),
                        0,
                    )

                    config = json.loads(
                        (project / ".loopforge" / "config.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    run_dir = Path(config["run_root"]) / config["current_run_id"]
                    run_path = run_dir / "run.json"
                    run = json.loads(run_path.read_text(encoding="utf-8"))
                    run = apply_initial_task_approval(
                        run,
                        approved=True,
                        source="test",
                    )
                    run["stage_statuses"]["research"] = "complete"
                    run["stage_statuses"]["plan"] = "awaiting_approval"
                    run["current_stage"] = "plan_ready"
                    run["human_gates"]["plan_approval"] = {
                        "required": True,
                        "status": "pending",
                    }
                    run = apply_plan_approval(run, source="test")
                    run_path.write_text(json.dumps(run), encoding="utf-8")

                    fixture_code = (
                        "from pathlib import Path; "
                        "path = Path('README.md'); "
                        "path.write_text(path.read_text(encoding='utf-8') + "
                        "'\\nWrapped.\\n', encoding='utf-8')"
                    )
                    self.assertEqual(
                        main(
                            [
                                "continue",
                                "--adapter",
                                "local-adapter-fixture",
                                "--",
                                sys.executable,
                                "-c",
                                fixture_code,
                            ]
                        ),
                        0,
                    )
            finally:
                os.chdir(previous)

            attempt_path = run_dir / "attempts" / "attempt-001" / "attempt.json"
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            protocol_command = attempt["protocol_command"]
            self.assertIn("loopforge.adapters.local_implementation_adapter", protocol_command)
            self.assertIn("--expected-session", protocol_command)
            self.assertIn("--result-output", protocol_command)
            self.assertEqual(attempt["status"], "completed")
            result = json.loads(
                (run_dir / attempt["result_path"]).read_text(encoding="utf-8")
            )
            validate_implementation_result.validate_result(result)
'''
tests = tests.replace(marker, regression + marker, 1)
test_path.write_text(tests, encoding="utf-8")
