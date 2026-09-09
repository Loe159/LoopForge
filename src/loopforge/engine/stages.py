"""Read-only workflow stages and draft publication domain for LoopForge runs.

Owns the read-only stage entry point (``execute_readonly_stage``), the next
available read-only stage selector (``next_readonly_stage``), the read-only
artifact validator (``validate_readonly_stage_artifact``), and the deterministic
draft publication preparer (``prepare_draft_publication``).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; lifecycle primitives and the workflow
result types are safe top-level imports from sibling submodules.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from loopforge.adapters.commands import (
    InteractiveAdapterUnavailable,
    interactive_stage_command,
    redacted_interactive_command,
    require_interactive_adapter,
)
from loopforge.engine.lifecycle import (
    RunStage,
    StageStatus,
)
from loopforge.engine.terminal import (
    TerminalLauncher,
    TerminalSessionResult,
    launch_terminal_session,
)
from loopforge.engine.workflow import StageResult
from loopforge.engine.path_resolvers import resolve_confined
from loopforge.engine.execution import OperationCallback


MAX_STAGE_ARTIFACT_BYTES = 1_000_000


def next_readonly_stage(run: dict[str, Any]) -> str | None:
    from loopforge.engine import normalize_run_workflow_state

    normalized = normalize_run_workflow_state(run)
    approval = normalized.get("approval", {})
    approved = bool(approval.get("approved")) if isinstance(approval, dict) else False
    if not approved:
        return None
    statuses = normalized.get("stage_statuses", {})
    if not isinstance(statuses, dict):
        return None
    if statuses.get("task") != "approved":
        return None
    if statuses.get("research") != "complete":
        return "research"
    if statuses.get("plan") not in {"awaiting_approval", "approved", "complete"}:
        return "plan"
    verification = normalized.get("verification", {})
    verification_passed = (
        statuses.get("verification") == "complete"
        and isinstance(verification, dict)
        and verification.get("status") == "passed"
    )
    if verification_passed and statuses.get("review") not in {"complete", "approved"}:
        return "review"
    return None


def validate_readonly_stage_artifact(stage: str, markdown: str) -> list[str]:
    from loopforge.engine import (
        READONLY_STAGE_SUCCESS,
        REQUIRED_READONLY_STAGE_SECTIONS,
        markdown_sections,
        parse_frontmatter,
        section_text,
    )

    blockers: list[str] = []
    lines = markdown.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---" or "---" not in [
        line.strip() for line in lines[1:]
    ]:
        blockers.append(f"{stage}.md must start with YAML frontmatter.")
        return blockers
    frontmatter = parse_frontmatter(markdown)
    if frontmatter.get("artifact") != stage:
        blockers.append(f"{stage}.md frontmatter must include artifact: {stage}.")
    if not frontmatter.get("artifact_version"):
        blockers.append(f"{stage}.md frontmatter must include artifact_version.")
    if not frontmatter.get("issue"):
        blockers.append(f"{stage}.md frontmatter must include issue.")
    if not frontmatter.get("base_commit"):
        blockers.append(f"{stage}.md frontmatter must include base_commit.")
    expected_status = READONLY_STAGE_SUCCESS[stage][0]
    if frontmatter.get("status") != expected_status:
        blockers.append(f"{stage}.md frontmatter must include status: {expected_status}.")
    sections = markdown_sections(markdown)
    missing_sections = [
        section
        for section in REQUIRED_READONLY_STAGE_SECTIONS[stage]
        if not section_text(sections, section)
    ]
    if missing_sections:
        blockers.append(
            f"{stage}.md is missing required sections: {', '.join(missing_sections)}."
        )
    return blockers


def prepare_draft_publication(project_dir: Path) -> StageResult:
    from loopforge.engine import (
        apply_draft_publication_prepared,
        current_git_branch,
        current_status,
        draft_publication_body,
        normalize_run_workflow_state,
        persist_run_json,
        relative_to_run,
        utc_now,
        write_json_atomic,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage="publication",
            ok=False,
            message="Initialize LoopForge before preparing draft publication.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage="publication",
            ok=False,
            message="No current run is ready for draft publication.",
            blockers=status.blockers or [status.next_step],
        )

    run = normalize_run_workflow_state(status.run)
    statuses = run.get("stage_statuses", {})
    gates = run.get("human_gates", {})
    eligibility = run.get("publish_eligibility", {})
    verification = run.get("verification", {})
    if not isinstance(statuses, dict):
        statuses = {}
    if not isinstance(gates, dict):
        gates = {}
    if not isinstance(eligibility, dict):
        eligibility = {}
    if not isinstance(verification, dict):
        verification = {}
    review_gate = gates.get("review_approval")
    if not isinstance(review_gate, dict):
        review_gate = {}
    patch = verification.get("patch")
    if not isinstance(patch, dict):
        patch = {}

    blockers: list[str] = []
    if statuses.get("verification") != "complete" or verification.get("status") != "passed":
        blockers.append("draft publication requires passed deterministic verification.")
    if statuses.get("review") not in {"approved", "complete"} or review_gate.get("status") != "approved":
        blockers.append("draft publication requires explicit review approval.")
    if not bool(eligibility.get("eligible")) or eligibility.get("mode") != "draft":
        blockers.append("draft publication requires draft publish eligibility.")
    patch_path_value = patch.get("path")
    patch_path = status.run_dir / str(patch_path_value) if patch_path_value else None
    if not bool(patch.get("generated")) or patch.get("status") != "generated":
        blockers.append("draft publication requires a generated verification patch.")
    if patch_path is None or not patch_path.is_file():
        blockers.append("draft publication requires a retained verification patch.")
    if not isinstance(patch.get("sha256"), str) or not str(patch.get("sha256")).strip():
        blockers.append("draft publication requires a verification patch sha256.")
    base_commit = run.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        blockers.append("draft publication requires base_commit in run.json.")
    if blockers:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            stage="publication",
            ok=False,
            message="LoopForge draft publication is blocked.",
            blockers=blockers,
        )

    publication_dir = status.run_dir / "artifacts" / "publication"
    publication_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = publication_dir / "draft-pr.json"
    relative_artifact_path = relative_to_run(status.run_dir, artifact_path)
    run_id = str(run.get("run_id") or "run")
    title = str(run.get("task") or "LoopForge run").strip() or "LoopForge run"
    payload = {
        "artifact_version": 1,
        "artifact": "draft_pr",
        "kind": "draft_pr_publication",
        "draft": True,
        "no_network": True,
        "network": {
            "performed": False,
            "reason": "LoopForge prepared a deterministic local draft artifact only.",
        },
        "publisher": "local-draft-artifact",
        "run_id": run_id,
        "task": run.get("task"),
        "title": f"LoopForge: {title}",
        "body": draft_publication_body(run, verification),
        "branch": f"loopforge/{run_id}",
        "base": current_git_branch(status.project_dir),
        "head_branch": f"loopforge/{run_id}",
        "base_branch": current_git_branch(status.project_dir),
        "base_commit": base_commit,
        "patch": {
            "path": patch.get("path"),
            "sha256": patch.get("sha256"),
            "size_bytes": patch.get("size_bytes", 0),
        },
        "verification": {
            "status": verification.get("status"),
            "patch": {
                "path": patch.get("path"),
                "sha256": patch.get("sha256"),
                "size_bytes": patch.get("size_bytes", 0),
            },
        },
        "source": {
            "run_id": run.get("run_id"),
            "task": run.get("task"),
            "review_status": review_gate.get("status"),
            "verification_status": verification.get("status"),
        },
    }
    write_json_atomic(artifact_path, payload)
    updated = apply_draft_publication_prepared(
        run,
        artifact_path=relative_artifact_path,
    )
    updated.setdefault("artifacts", {})["draft_publication"] = str(artifact_path)
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, status.run_json_path or (status.run_dir / "run.json"), updated)
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage="publication",
        ok=True,
        message="LoopForge draft PR artifact prepared without network publication.",
        blockers=[],
        artifact_path=artifact_path,
    )


def execute_readonly_stage(
    project_dir: Path,
    *,
    stage: str,
    adapter: str,
    adapter_args: list[str] | None = None,
    execution_mode: str = "auto",
    terminal_launcher: TerminalLauncher | None = None,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> StageResult:
    from loopforge.engine import (
        AGENT_EXECUTION_MODES,
        READONLY_STAGE_SUCCESS,
        attempt_timeout,
        codex_workspace_preflight_blockers,
        command_for_readonly_stage,
        current_status,
        emit_adapter_output,
        emit_operation_event,
        execute_fixture_command,
        execute_readonly_adapter_command,
        git_status_entries,
        initial_workflow_state,
        normalize_run_workflow_state,
        persist_run_json,
        readonly_stage_prerequisite_blockers,
        readonly_worktree_changes,
        render_stage_prompt,
        retain_rejected_readonly_artifact,
        run_workspace_path,
        update_run_for_stage_blocker,
        utc_now,
        workspace_snapshot,
        write_bytes,
        write_json_atomic,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            stage=stage,
            ok=False,
            message="Initialize LoopForge before running a read-only stage.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            stage=stage,
            ok=False,
            message="No current run is ready for a read-only stage.",
            blockers=status.blockers or [status.next_step],
        )
    run = normalize_run_workflow_state(status.run)
    run_json_path = status.run_json_path or (status.run_dir / "run.json")
    if execution_mode not in AGENT_EXECUTION_MODES:
        blockers = [
            "read-only stage execution_mode must be auto, terminal, or headless."
        ]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    blockers = readonly_stage_prerequisite_blockers(run, stage)
    if blockers:
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    available_stage = next_readonly_stage(run)
    if available_stage != stage:
        blockers = [f"{stage} is not the next available read-only stage."]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    workspace_dir = run_workspace_path(run, status.project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        blockers = [f"run workspace is not available: {workspace_dir}"]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )

    blockers = codex_workspace_preflight_blockers(adapter, workspace_dir)
    if blockers:
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked by the Codex preflight.",
            blockers=blockers,
        )

    selected_execution_mode = execution_mode
    terminal_fallback_reason = ""
    if execution_mode != "headless":
        try:
            require_interactive_adapter(adapter)
            selected_execution_mode = "terminal"
        except InteractiveAdapterUnavailable as error:
            if execution_mode == "terminal":
                blockers = [f"interactive {stage} adapter is unavailable: {error}"]
                updated = update_run_for_stage_blocker(
                    project_dir=status.project_dir,
                    run_json_path=run_json_path,
                    run=run,
                    stage=stage,
                    blockers=blockers,
                )
                return StageResult(
                    project_dir=status.project_dir,
                    run_dir=status.run_dir,
                    run=updated,
                    stage=stage,
                    ok=False,
                    message=f"LoopForge {stage} stage is blocked.",
                    blockers=blockers,
                )
            selected_execution_mode = "headless"
            terminal_fallback_reason = str(error)

    stage_dir = status.run_dir / "artifacts" / "stages" / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    last_message_path = stage_dir / "last-message.md"
    last_message_path.unlink(missing_ok=True)
    emit_operation_event(
        operation_callback,
        "stage_started",
        f"Starting read-only {stage} stage with {adapter}.",
        artifact=str(stage_dir),
    )
    runtime_stage_dir = workspace_dir / ".loopforge" / "runtime-stages"
    runtime_prompt_path = runtime_stage_dir / f"{stage}-prompt.md"
    candidate_path = runtime_stage_dir / f"{stage}-candidate.md"
    prompt = render_stage_prompt(
        stage=stage,
        run=run,
        run_dir=status.run_dir,
        workspace_dir=workspace_dir,
        adapter=adapter,
        artifact_output_path=(
            candidate_path if selected_execution_mode == "terminal" else None
        ),
    )
    (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    runtime_prompt_path.unlink(missing_ok=True)
    candidate_path.unlink(missing_ok=True)
    before_snapshot = workspace_snapshot(workspace_dir)
    before_git = git_status_entries(workspace_dir)
    if cancel_event is not None and cancel_event.is_set():
        blockers = [f"read-only {stage} stage was interrupted before adapter execution."]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        emit_operation_event(
            operation_callback,
            "cancelled",
            blockers[0],
            artifact=str(stage_dir / "prompt.md"),
            status="cancelled",
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage was interrupted.",
            blockers=blockers,
        )
    timeout_seconds = attempt_timeout(run, status.loop_contract or {})
    terminal_result: TerminalSessionResult | None = None
    terminal_candidate_expected = False
    terminal_candidate_present = False
    terminal_candidate_limit_exceeded = False
    headless_candidate_limit_exceeded = False
    capture_codex_stream = False
    capture_kilo_stream = False
    command: list[str] = []
    stdout = b""
    stderr = b""
    artifact_stdout = b""
    try:
        if selected_execution_mode == "terminal":
            runtime_stage_dir.mkdir(parents=True, exist_ok=True)
            with runtime_prompt_path.open("x", encoding="utf-8") as prompt_file:
                prompt_file.write(prompt)
            prompt_reference = runtime_prompt_path.relative_to(workspace_dir).as_posix()
            candidate_reference = candidate_path.relative_to(workspace_dir).as_posix()
            interactive_prompt = (
                "Read and follow the complete LoopForge "
                f"{stage} prompt in {prompt_reference}. Before ending this session, "
                f"write the complete final UTF-8 Markdown artifact to {candidate_reference}. "
                "Do not only print the artifact in the terminal. Do not modify, stage, "
                "or commit any other worktree file. The candidate file is the only "
                "worktree write LoopForge permits for this stage."
            )
            command = interactive_stage_command(
                adapter=adapter,
                adapter_args=adapter_args or [],
                workspace_dir=workspace_dir,
                prompt=interactive_prompt,
            )
            try:
                terminal_result = launch_terminal_session(
                    command=tuple(command),
                    cwd=workspace_dir,
                    title=f"LoopForge {run.get('run_id')} / {stage} / {adapter}",
                    timeout_seconds=timeout_seconds,
                    artifacts_dir=stage_dir,
                    cancel_event=cancel_event,
                    terminal_launcher=terminal_launcher,
                    output_chunk_callback=(
                        (
                            lambda stream, chunk: emit_adapter_output(
                                operation_callback, stage, stream, chunk
                            )
                        )
                        if operation_callback is not None
                        else None
                    ),
                )
            finally:
                runtime_prompt_path.unlink(missing_ok=True)

            cancelled_before_fallback = terminal_result.interrupted or (
                not terminal_result.launched
                and cancel_event is not None
                and cancel_event.is_set()
            )
            if (
                not terminal_result.launched
                and execution_mode == "auto"
                and not cancelled_before_fallback
            ):
                terminal_fallback_reason = (
                    terminal_result.error or "terminal launcher was unavailable"
                )
                selected_execution_mode = "headless"
                prompt = render_stage_prompt(
                    stage=stage,
                    run=run,
                    run_dir=status.run_dir,
                    workspace_dir=workspace_dir,
                    adapter=adapter,
                )
                (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
            else:
                terminal_candidate_expected = terminal_result.launched
                try:
                    with candidate_path.open("rb") as candidate_file:
                        terminal_candidate_present = True
                        artifact_stdout = candidate_file.read(
                            MAX_STAGE_ARTIFACT_BYTES + 1
                        )
                except FileNotFoundError:
                    artifact_stdout = b""
                if len(artifact_stdout) > MAX_STAGE_ARTIFACT_BYTES:
                    terminal_candidate_limit_exceeded = True
                    artifact_stdout = artifact_stdout[:MAX_STAGE_ARTIFACT_BYTES]
                stdout = terminal_result.output
                stderr = terminal_result.error.encode("utf-8", errors="replace")
                child = {
                    "completed": terminal_result.launched
                    and not terminal_result.timed_out,
                    "returncode": terminal_result.returncode,
                    "timed_out": terminal_result.timed_out,
                    "interrupted": cancelled_before_fallback,
                    "output_limit_exceeded": terminal_result.output_truncated,
                }

        if selected_execution_mode == "headless":
            capture_codex_stream = adapter == "codex" and operation_callback is not None
            capture_kilo_stream = adapter == "kilo-code"
            command = command_for_readonly_stage(
                adapter=adapter,
                adapter_args=adapter_args or [],
                workspace_dir=workspace_dir,
                run_dir=status.run_dir,
                json_output=capture_codex_stream,
                output_last_message_path=(
                    last_message_path if capture_codex_stream else None
                ),
            )
            if adapter == "local-adapter-fixture":
                child, stdout, stderr = execute_fixture_command(
                    command=command,
                    prompt=prompt.encode("utf-8"),
                    project_dir=workspace_dir,
                    timeout_seconds=timeout_seconds,
                )
                artifact_stdout = stdout
            else:
                child, stdout, stderr = execute_readonly_adapter_command(
                    command=command,
                    prompt=prompt.encode("utf-8"),
                    project_dir=workspace_dir,
                    timeout_seconds=timeout_seconds,
                    operation_callback=operation_callback,
                    cancel_event=cancel_event,
                )
                if capture_codex_stream:
                    try:
                        with last_message_path.open("rb") as message_file:
                            artifact_stdout = message_file.read(
                                MAX_STAGE_ARTIFACT_BYTES + 1
                            )
                    except FileNotFoundError:
                        artifact_stdout = b""
                    if len(artifact_stdout) > MAX_STAGE_ARTIFACT_BYTES:
                        headless_candidate_limit_exceeded = True
                        artifact_stdout = artifact_stdout[
                            :MAX_STAGE_ARTIFACT_BYTES
                        ]
                elif capture_kilo_stream and isinstance(
                    child.get("artifact_output"), bytes
                ):
                    artifact_stdout = child["artifact_output"]
                    if len(artifact_stdout) > MAX_STAGE_ARTIFACT_BYTES:
                        headless_candidate_limit_exceeded = True
                        artifact_stdout = artifact_stdout[:MAX_STAGE_ARTIFACT_BYTES]
                else:
                    artifact_stdout = stdout
    except (OSError, RuntimeError, ValueError) as error:
        blockers = [f"read-only {stage} adapter execution could not start: {error}"]
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )
    finally:
        runtime_prompt_path.unlink(missing_ok=True)
        candidate_path.unlink(missing_ok=True)
        last_message_path.unlink(missing_ok=True)

    write_json_atomic(
        stage_dir / "execution.json",
        {
            "adapter": adapter,
            "execution_mode": selected_execution_mode,
            "stream_format": (
                "codex-jsonl"
                if capture_codex_stream
                else "kilo-jsonl"
                if capture_kilo_stream
                else "text"
            ),
            "terminal_launcher": (
                terminal_result.launcher if terminal_result is not None else None
            ),
            "terminal_launched": (
                terminal_result.launched if terminal_result is not None else False
            ),
            "terminal_fallback_reason": terminal_fallback_reason,
            "candidate_present": terminal_candidate_present,
            "candidate_limit_exceeded": (
                terminal_candidate_limit_exceeded
                or headless_candidate_limit_exceeded
            ),
            "transcript_truncated": (
                terminal_result.output_truncated
                if terminal_result is not None
                else False
            ),
            "returncode": child.get("returncode"),
            "command": (
                redacted_interactive_command(command, interactive_prompt)
                if terminal_candidate_expected
                else command
            ),
        },
    )
    after_snapshot = workspace_snapshot(workspace_dir)
    after_git = git_status_entries(workspace_dir)
    write_bytes(stage_dir / "adapter.stdout", stdout)
    write_bytes(stage_dir / "adapter.stderr", stderr)
    if adapter == "local-adapter-fixture":
        # Fixtures use the compatibility runner and only have output once they
        # finish. Real adapters stream each chunk through the callback below.
        emit_adapter_output(operation_callback, stage, "stdout", stdout)
        emit_adapter_output(operation_callback, stage, "stderr", stderr)
    worktree_changes = readonly_worktree_changes(
        before_snapshot=before_snapshot,
        before_git=before_git,
        after_snapshot=after_snapshot,
        after_git=after_git,
    )
    returncode = child.get("returncode")
    execution_interrupted = bool(child.get("interrupted")) or (
        selected_execution_mode == "headless"
        and cancel_event is not None
        and cancel_event.is_set()
    )
    if (
        selected_execution_mode == "terminal"
        and terminal_result is not None
        and not terminal_result.launched
    ):
        blockers = [
            f"interactive {stage} terminal could not start: "
            + (terminal_result.error or "launcher unavailable")
        ]
    elif execution_interrupted:
        blockers = [f"read-only {stage} stage was interrupted; its evidence was retained."]
    elif bool(child.get("timed_out")):
        blockers = [f"read-only {stage} adapter timed out."]
    elif not bool(child.get("completed")):
        blockers = [f"read-only {stage} adapter did not complete."]
    elif returncode != 0 and not (terminal_candidate_expected and artifact_stdout):
        blockers = [f"read-only {stage} adapter failed with return code {returncode}."]
    else:
        blockers = []
    if worktree_changes:
        blockers.append(
            f"read-only {stage} stage changed the worktree: "
            + "; ".join(worktree_changes[:10])
        )
    artifact_validation_blockers: list[str] = []
    if terminal_candidate_limit_exceeded:
        artifact_validation_blockers.append(
            f"interactive {stage} candidate exceeded "
            f"{MAX_STAGE_ARTIFACT_BYTES} bytes."
        )
    elif headless_candidate_limit_exceeded:
        artifact_validation_blockers.append(
            f"headless {stage} candidate exceeded "
            f"{MAX_STAGE_ARTIFACT_BYTES} bytes."
        )
    elif terminal_candidate_expected and not terminal_candidate_present:
        artifact_validation_blockers.append(
            f"interactive {stage} terminal did not produce its candidate artifact."
        )
    try:
        artifact_text = artifact_stdout.decode("utf-8")
    except UnicodeDecodeError:
        artifact_text = ""
        artifact_validation_blockers.append(f"{stage}.md stdout must be valid UTF-8.")
    if not artifact_text:
        artifact_validation_blockers.append(f"{stage}.md stdout was empty.")
    if artifact_text:
        artifact_validation_blockers.extend(validate_readonly_stage_artifact(stage, artifact_text))
    if artifact_validation_blockers:
        rejected_artifact_path = retain_rejected_readonly_artifact(
            stage_dir=stage_dir,
            stage=stage,
            content=artifact_stdout,
        )
        blockers.extend(artifact_validation_blockers)
        blockers.append(
            f"{stage}.md candidate was rejected; inspect {rejected_artifact_path}."
        )
    if blockers:
        updated = update_run_for_stage_blocker(
            project_dir=status.project_dir,
            run_json_path=run_json_path,
            run=run,
            stage=stage,
            blockers=blockers,
        )
        emit_operation_event(
            operation_callback,
            "cancelled" if execution_interrupted else "blocked",
            f"Read-only {stage} stage is blocked.",
            artifact=str(stage_dir),
            status="cancelled" if execution_interrupted else "blocked",
        )
        return StageResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated,
            stage=stage,
            ok=False,
            message=f"LoopForge {stage} stage is blocked.",
            blockers=blockers,
        )

    artifact_path = status.run_dir / f"{stage}.md"
    artifact_path.write_bytes(artifact_stdout)
    updated = normalize_run_workflow_state(run)
    stage_status, current_stage = READONLY_STAGE_SUCCESS[stage]
    updated["stage_statuses"][stage] = stage_status
    updated["current_stage"] = current_stage
    if stage == "plan":
        updated["human_gates"]["plan_approval"] = {
            **initial_workflow_state()["human_gates"]["plan_approval"],
            "status": "pending",
        }
    updated["blockers"] = []
    updated["updated_at"] = utc_now()
    persist_run_json(status.project_dir, run_json_path, updated)
    emit_operation_event(
        operation_callback,
        "completed",
        f"Read-only {stage} stage completed.",
        artifact=str(artifact_path),
        status="completed",
    )
    return StageResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated,
        stage=stage,
        ok=True,
        message=f"LoopForge {stage} stage completed.",
        blockers=[],
        artifact_path=artifact_path,
    )
