"""Attempt, adapter-execution, metrics, and continue domain for LoopForge runs.

Owns adapter attempt execution (``execute_attempt``), run-state updates after
an attempt (``update_run_after_attempt``), the bounded ``continue_run`` entry
point, the attempt/timeout record helpers, and the metrics record builders
(``build_metrics_record`` / ``record_run_metrics`` / ``summarize_run_metrics``
plus the per-field metric extractors).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; lifecycle primitives are a safe
top-level import.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

@dataclass(frozen=True)
class ContinueResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    contract: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]
    attempt: dict[str, Any] | None = None


@dataclass(frozen=True)
class MetricsRecordResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    record_path: Path | None
    record: dict[str, Any] | None
    blockers: list[str]


@dataclass(frozen=True)
class MetricsSummaryResult:
    project_dir: Path
    run_root: Path | None
    ok: bool
    message: str
    records: list[dict[str, Any]]
    summary: dict[str, Any]
    blockers: list[str]


OperationCallback = Callable[[dict[str, Any]], None]


def nonnegative_int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def first_nonnegative_int(*values: object) -> int | None:
    for value in values:
        parsed = nonnegative_int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def latest_attempt(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = attempt_records(run)
    return attempts[-1] if attempts else None


def read_attempt_protocol_result(run_dir: Path, attempt: dict[str, Any] | None) -> dict[str, Any]:
    from loopforge.engine import read_json

    if attempt is None:
        return {}
    raw_path = attempt.get("result_path")
    if not isinstance(raw_path, str) or not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = run_dir / path
    if not path.exists():
        return {}
    try:
        result = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return result


def model_from_command(command: object) -> str | None:
    if not isinstance(command, list):
        return None
    parts = [str(part) for part in command]
    for index, part in enumerate(parts):
        if part in {"-m", "--model"} and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith("--model="):
            return part.split("=", 1)[1] or None
    return None


def metrics_model(
    *,
    override: str | None,
    attempt: dict[str, Any] | None,
    protocol_result: dict[str, Any],
) -> dict[str, Any]:
    model: str | None = override.strip() if isinstance(override, str) and override.strip() else None
    if model is None:
        raw_model = protocol_result.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        elif isinstance(raw_model, dict):
            candidate = raw_model.get("id") or raw_model.get("name")
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
    if model is None:
        for key in ("model_id", "model_name"):
            candidate = protocol_result.get(key)
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
                break
    if model is None and attempt is not None:
        model = model_from_command(attempt.get("command"))
    return {
        "status": "reported" if model is not None else "unavailable",
        "id": model,
    }


def metrics_tokens(
    *,
    protocol_result: dict[str, Any],
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
) -> dict[str, Any]:
    source = protocol_result.get("tokens")
    if not isinstance(source, dict):
        source = protocol_result.get("usage")
    if not isinstance(source, dict):
        source = {}
    measured_input = first_nonnegative_int(
        input_tokens,
        source.get("input_tokens"),
        source.get("prompt_tokens"),
    )
    measured_output = first_nonnegative_int(
        output_tokens,
        source.get("output_tokens"),
        source.get("completion_tokens"),
    )
    measured_total = first_nonnegative_int(total_tokens, source.get("total_tokens"))
    if measured_total is None and measured_input is not None and measured_output is not None:
        measured_total = measured_input + measured_output
    status = (
        "reported"
        if any(value is not None for value in (measured_input, measured_output, measured_total))
        else "unavailable"
    )
    return {
        "status": status,
        "input_tokens": measured_input,
        "output_tokens": measured_output,
        "total_tokens": measured_total,
    }


def metrics_cost(
    *,
    protocol_result: dict[str, Any],
    amount_microunits: int | None,
    currency: str | None,
) -> dict[str, Any]:
    source = protocol_result.get("cost")
    if not isinstance(source, dict):
        source = {}
    measured_amount = first_nonnegative_int(
        amount_microunits,
        source.get("amount_microunits"),
        source.get("total_microunits"),
    )
    measured_currency = (
        currency.strip().upper()
        if isinstance(currency, str) and currency.strip()
        else None
    )
    if measured_currency is None:
        raw_currency = source.get("currency")
        if isinstance(raw_currency, str) and raw_currency.strip():
            measured_currency = raw_currency.strip().upper()
    return {
        "status": "reported" if measured_amount is not None else "unavailable",
        "amount_microunits": measured_amount,
        "currency": measured_currency if measured_amount is not None else None,
    }


def metrics_patch(verification: dict[str, Any] | None) -> dict[str, Any]:
    if verification is None:
        return {
            "status": "unavailable",
            "path": None,
            "size_bytes": None,
            "sha256": None,
        }
    patch = verification.get("patch", {})
    if not isinstance(patch, dict):
        patch = {}
    size = nonnegative_int_or_none(patch.get("size_bytes"))
    generated = bool(patch.get("generated"))
    if generated or patch.get("status") == "generated":
        status = "measured"
    else:
        status = "not_generated"
    return {
        "status": status,
        "path": patch.get("path") if isinstance(patch.get("path"), str) else None,
        "size_bytes": size if size is not None else (0 if status == "not_generated" else None),
        "sha256": patch.get("sha256") if isinstance(patch.get("sha256"), str) else None,
    }


def inferred_final_disposition(run_status: object) -> str:
    from loopforge.engine import (
        ADAPTER_BLOCKED,
        LOOP_CONTRACT_DRAFT,
        LOOP_CONTRACT_READY,
        READY_FOR_VERIFICATION,
        VERIFICATION_FAILED,
        VERIFIED,
    )

    status = str(run_status or "unknown")
    if status == VERIFIED:
        return "verified"
    if status == VERIFICATION_FAILED:
        return "failed"
    if status == ADAPTER_BLOCKED:
        return "blocked"
    if status == READY_FOR_VERIFICATION:
        return "pending_verification"
    if status in {LOOP_CONTRACT_DRAFT, LOOP_CONTRACT_READY}:
        return "pending"
    return status


def build_metrics_record(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> dict[str, Any]:
    from loopforge.engine import (
        duration_seconds,
        utc_now,
        verification_state,
    )

    attempt = latest_attempt(run)
    protocol_result = read_attempt_protocol_result(run_dir, attempt)
    verification = verification_state(run)
    finished_at = (
        verification.get("finished_at")
        if isinstance(verification, dict) and verification.get("finished_at")
        else (attempt or {}).get("finished_at")
    )
    if not finished_at:
        finished_at = run.get("updated_at") or run.get("created_at")
    measured_duration = duration_seconds(run.get("created_at"), finished_at)
    attempt_count = run.get("attempt_count")
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = len(attempt_records(run))
    adapter = attempt.get("adapter") if isinstance(attempt, dict) else None
    final = (
        final_disposition.strip()
        if isinstance(final_disposition, str) and final_disposition.strip()
        else inferred_final_disposition(run.get("status"))
    )
    corrections = nonnegative_int_or_none(human_corrections)
    if corrections is None:
        corrections = nonnegative_int_or_none(run.get("human_correction_count"))
    return {
        "metrics_version": 1,
        "recorded_at": utc_now(),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "task": run.get("task"),
        "project_root": str(project_dir),
        "profile": run.get("profile"),
        "pack": run.get("pack"),
        "timing": {
            "started_at": run.get("created_at"),
            "finished_at": finished_at,
            "duration_seconds": measured_duration,
            "status": "measured" if measured_duration is not None else "unavailable",
        },
        "adapter": {
            "status": "reported" if isinstance(adapter, str) and adapter else "unavailable",
            "id": adapter if isinstance(adapter, str) and adapter else None,
        },
        "model": metrics_model(
            override=model,
            attempt=attempt,
            protocol_result=protocol_result,
        ),
        "attempts": {
            "count": attempt_count,
            "statuses": [
                str(item.get("status") or "unknown")
                for item in attempt_records(run)
            ],
        },
        "tokens": metrics_tokens(
            protocol_result=protocol_result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        "cost": metrics_cost(
            protocol_result=protocol_result,
            amount_microunits=cost_microunits,
            currency=cost_currency,
        ),
        "patch": metrics_patch(verification),
        "verification": {
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "checks_passed": (
                verification.get("checks_passed") if isinstance(verification, dict) else None
            ),
            "checks_total": (
                verification.get("checks_total") if isinstance(verification, dict) else None
            ),
        },
        "human_corrections": {
            "status": "measured" if corrections is not None else "unavailable",
            "count": corrections,
        },
        "final_disposition": {
            "status": final,
            "source": "reported" if final_disposition else "run_status",
        },
    }


def record_run_metrics(
    project_dir: Path,
    *,
    run_id: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> MetricsRecordResult:
    from loopforge.engine import (
        METRICS_RECORD_FILE,
        current_or_selected_run,
        write_json_atomic,
    )

    status, run_dir, _run_json_path, run, blockers = current_or_selected_run(project_dir, run_id)
    if blockers or run is None or run_dir is None:
        return MetricsRecordResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge metrics record failed.",
            record_path=None,
            record=None,
            blockers=blockers,
        )
    record = build_metrics_record(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_microunits=cost_microunits,
        cost_currency=cost_currency,
        human_corrections=human_corrections,
        final_disposition=final_disposition,
    )
    record_path = run_dir / "metrics" / METRICS_RECORD_FILE
    write_json_atomic(record_path, record)
    return MetricsRecordResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        ok=True,
        message="LoopForge metrics recorded.",
        record_path=record_path,
        record=record,
        blockers=[],
    )


def summarize_run_metrics(project_dir: Path) -> MetricsSummaryResult:
    from loopforge.engine import (
        _metrics_service,
        build_metrics_summary,
        current_status,
    )

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return MetricsSummaryResult(
            project_dir=status.project_dir,
            run_root=None,
            ok=False,
            message="LoopForge metrics summarize failed.",
            records=[],
            summary=build_metrics_summary([]),
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    records, blockers = _metrics_service().load_records(run_root)
    summary = build_metrics_summary(records)
    return MetricsSummaryResult(
        project_dir=status.project_dir,
        run_root=run_root,
        ok=not blockers,
        message=(
            "LoopForge metrics summary ready."
            if not blockers
            else "LoopForge metrics summary has warnings."
        ),
        records=records,
        summary=summary,
        blockers=blockers,
    )


def attempt_limit(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 1


def attempt_timeout(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 540


def attempt_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attempts = run.get("attempts", [])
    if not isinstance(raw_attempts, list):
        return []
    return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]


def execute_attempt(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    contract: dict[str, Any],
    adapter: str,
    adapter_args: list[str],
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
    stream_output: bool = True,
) -> dict[str, Any]:
    from loopforge.engine import (
        SUPPORTED_ADAPTERS,
        adapter_protocol_command,
        adapter_result_stop_reasons,
        append_progress,
        command_for_attempt,
        decode_output,
        emit_operation_event,
        execute_adapter_command,
        expected_session_for,
        git_status_entries,
        normalize_profile,
        parse_adapter_result,
        parse_adapter_result_file,
        relative_to_run,
        render_adapter_prompt,
        run_workspace_path,
        synthetic_adapter_result,
        utc_now,
        validate_attempt_result,
        workspace_snapshot,
        workspace_snapshot_changes,
        write_bytes,
        write_json_atomic,
    )

    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter}")
    workspace_dir = run_workspace_path(run, project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        raise ValueError(f"run workspace is not available: {workspace_dir}")
    command = command_for_attempt(
        adapter=adapter,
        adapter_args=adapter_args,
        workspace_dir=workspace_dir,
        run_dir=run_dir,
    )
    attempts = attempt_records(run)
    number = len(attempts) + 1
    attempt_id = f"attempt-{number:03d}"
    attempt_dir = run_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)

    emit_operation_event(
        operation_callback,
        "attempt_started",
        f"Starting {adapter} implementation attempt {attempt_id}.",
        artifact=str(attempt_dir),
    )

    started = utc_now()
    prompt_path = attempt_dir / "adapter-prompt.md"
    prompt_path.write_text(
        render_adapter_prompt(
            run=run,
            contract=contract,
            run_dir=run_dir,
            workspace_dir=workspace_dir,
            adapter=adapter,
            attempt_id=attempt_id,
        ),
        encoding="utf-8",
    )
    session = expected_session_for(run, adapter, workspace_dir)
    expected_session_path = attempt_dir / "expected-session.json"
    write_json_atomic(expected_session_path, session)
    before_snapshot = workspace_snapshot(workspace_dir)
    before_git = git_status_entries(workspace_dir)
    timeout_seconds = attempt_timeout(run, contract)

    result_path = attempt_dir / "result.json"
    child_stderr_path = attempt_dir / "adapter-child.stderr"
    protocol_command = adapter_protocol_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=prompt_path,
        result_output=result_path,
        child_stderr_output=child_stderr_path,
    )
    child, stdout, stderr = execute_adapter_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        workspace_dir=workspace_dir,
        stdin_file=prompt_path,
        result_output=result_path,
        child_stderr_output=child_stderr_path,
        timeout_seconds=timeout_seconds,
        operation_callback=operation_callback,
        cancel_event=cancel_event,
        stream_output=stream_output,
    )
    result = parse_adapter_result_file(result_path) or parse_adapter_result(stdout)

    finished = utc_now()
    after_snapshot = workspace_snapshot(workspace_dir)
    after_git = git_status_entries(workspace_dir)
    workspace_changes = (
        after_git
        if after_git is not None
        else workspace_snapshot_changes(before_snapshot, after_snapshot)
    )
    snapshot_changed = before_snapshot != after_snapshot
    returncode = child.get("returncode")
    completed = bool(child.get("completed")) and returncode == 0
    timed_out = bool(child.get("timed_out"))
    output_limit_exceeded = bool(child.get("output_limit_exceeded"))
    interrupted = bool(child.get("interrupted"))

    if interrupted:
        status = "interrupted"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary="Adapter execution was interrupted.",
            workspace_changed=snapshot_changed,
        )
    elif result is None:
        status = "failed"
        stderr_text = decode_output(stderr).strip()
        stdout_text = decode_output(stdout).strip()
        detail = stderr_text or stdout_text or "adapter produced no protocol result"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=f"Adapter failed before producing a result: {detail}"[:1000],
            workspace_changed=snapshot_changed,
        )
    else:
        status = str(result.get("status", "failed"))
        if "workspace_changed" not in result:
            result["workspace_changed"] = snapshot_changed
        if "summary" not in result:
            result["summary"] = f"Adapter reported {status}."

    profile_stop_reasons: list[str] = []
    if normalize_profile(run.get("profile")) == "autonomous":
        profile_stop_reasons = adapter_result_stop_reasons(result)
        if profile_stop_reasons and status == "completed":
            status = "blocked"
            result["status"] = status
            result["next_action"] = "human_review"
            result["summary"] = (
                str(result.get("summary", "")).rstrip()
                + " Autonomy profile stopped for human review."
            ).strip()

    contract_validation_error = ""
    invalid_result_path: Path | None = None
    try:
        result = validate_attempt_result(result, session)
        status = str(result["status"])
    except ValueError as error:
        contract_validation_error = str(error)
        invalid_result_path = attempt_dir / "result.invalid.json"
        write_json_atomic(invalid_result_path, result)
        status = "failed"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=(
                f"Implementation result contract validation failed: {error}"
            )[:1000],
            workspace_changed=snapshot_changed,
        )
        result = validate_attempt_result(result, session)

    stdout_path = attempt_dir / "adapter.stdout"
    stderr_path = attempt_dir / "adapter.stderr"
    result_path = attempt_dir / "result.json"
    write_bytes(stdout_path, stdout)
    write_bytes(stderr_path, stderr)
    write_json_atomic(result_path, result)

    attempt = {
        "id": attempt_id,
        "number": number,
        "adapter": adapter,
        "command": command,
        "protocol_command": protocol_command,
        "started_at": started,
        "finished_at": finished,
        "status": status,
        "summary": str(result.get("summary", "")),
        "workspace_changed": bool(result.get("workspace_changed", snapshot_changed)),
        "workspace_changes": workspace_changes,
        "returncode": returncode,
        "timed_out": timed_out,
        "interrupted": interrupted,
        "output_limit_exceeded": output_limit_exceeded,
        "profile_stop_reasons": profile_stop_reasons,
        "contract_validation_error": contract_validation_error or None,
        "invalid_result_path": (
            relative_to_run(run_dir, invalid_result_path)
            if invalid_result_path is not None
            else None
        ),
        "publication_requested": bool(result.get("publication_requested", False)),
        "network_requested": bool(result.get("network_requested", False)),
        "attempt_dir": str(attempt_dir),
        "workspace": str(workspace_dir),
        "expected_session_path": relative_to_run(run_dir, expected_session_path),
        "prompt_path": relative_to_run(run_dir, prompt_path),
        "stdout_path": relative_to_run(run_dir, stdout_path),
        "stderr_path": relative_to_run(run_dir, stderr_path),
        "child_stderr_path": (
            relative_to_run(run_dir, child_stderr_path)
            if child_stderr_path.exists()
            else None
        ),
        "result_path": relative_to_run(run_dir, result_path),
        "before_git_status": before_git,
        "after_git_status": after_git,
    }
    write_json_atomic(attempt_dir / "attempt.json", attempt)
    append_progress(run_dir, attempt)
    emit_operation_event(
        operation_callback,
        "attempt_finished",
        f"Implementation attempt {attempt_id} {status}.",
        artifact=str(attempt_dir / "attempt.json"),
        status=status,
    )
    return attempt


def update_run_after_attempt(
    *,
    project_dir: Path,
    run_json_path: Path,
    run: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    from loopforge.engine import (
        ADAPTER_BLOCKED,
        READY_FOR_VERIFICATION,
        normalize_run_workflow_state,
        persist_run_json,
        utc_now,
    )

    updated = dict(run)
    attempts = attempt_records(updated)
    attempts.append(attempt)
    updated["attempts"] = attempts
    updated["attempt_count"] = len(attempts)
    updated["last_attempt"] = attempt
    updated["updated_at"] = utc_now()
    if attempt["status"] == "completed":
        updated["status"] = READY_FOR_VERIFICATION
        updated["blockers"] = []
        updated = normalize_run_workflow_state(updated)
        updated["stage_statuses"]["implementation"] = "complete"
        updated["current_stage"] = "implementation_ready"
    else:
        updated["status"] = ADAPTER_BLOCKED
        blockers = [
            f"attempt {attempt['id']} with adapter {attempt['adapter']} "
            f"reported {attempt['status']}: {attempt['summary']}"
        ]
        for reason in attempt.get("profile_stop_reasons", []):
            blockers.append(str(reason))
        updated["blockers"] = blockers
        updated = normalize_run_workflow_state(updated)
        updated["stage_statuses"]["implementation"] = "blocked"
        updated["current_stage"] = "implementation_in_progress"
    persist_run_json(project_dir, run_json_path, updated)
    return updated


def continue_run(
    project_dir: Path,
    *,
    adapter: str | None = None,
    adapter_args: list[str] | None = None,
    confirmed: bool = False,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
    stream_output: bool = True,
) -> ContinueResult:
    from loopforge.engine import (
        ADAPTER_BLOCKED,
        DEFAULT_PROFILE,
        VERIFICATION_FAILED,
        append_unique,
        codex_workspace_preflight_blockers,
        current_status,
        implementation_gate_blockers,
        loop_contract_state,
        normalize_run_workflow_state,
        persist_run_json,
        profile_transition_blockers,
        run_workspace_path,
        utc_now,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            contract=None,
            ok=False,
            message="Initialize LoopForge before continuing.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            contract=status.loop_contract,
            ok=False,
            message="No current run is ready to continue.",
            blockers=status.blockers or [status.next_step],
        )

    contract = status.loop_contract or loop_contract_state(status.run_dir / "loop.md")
    run_status = str(status.run.get("status") or "")
    # Failed deterministic checks are evidence for a bounded correction attempt,
    # not permanent implementation gates.  Contract, approval, and attempt-limit
    # checks below are still evaluated before an adapter can run.
    blockers = [] if run_status in {ADAPTER_BLOCKED, VERIFICATION_FAILED} else list(status.blockers)
    for blocker in implementation_gate_blockers(status.run):
        append_unique(blockers, blocker)
    if contract["status"] != "valid":
        for error in contract.get("errors", []):
            append_unique(blockers, str(error))
    if not contract.get("success_checks"):
        append_unique(
            blockers,
            "loop contract has no success checks; add at least one under # Success Checks.",
        )
    profile = str(status.run.get("profile", ""))
    if profile == "autonomous" and contract.get("subjective") and not contract.get("rubric"):
        append_unique(
            blockers,
            "subjective work needs a rubric before autonomous attempts; "
            "add it under # Subjective Rubric.",
        )
    attempts = attempt_records(status.run)
    max_attempts = attempt_limit(status.run, contract)
    if len(attempts) >= max_attempts:
        append_unique(
            blockers,
            f"max attempts reached ({len(attempts)}/{max_attempts}); human review is required.",
        )
    workspace_dir = run_workspace_path(status.run, status.project_dir)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        append_unique(blockers, f"run workspace is not available: {workspace_dir}")
    for blocker in codex_workspace_preflight_blockers(
        adapter or "",
        workspace_dir,
        implementation=adapter is not None,
    ):
        append_unique(blockers, blocker)
    if blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the loop contract.",
            blockers=blockers,
        )

    if adapter is None:
        profile_blockers = profile_transition_blockers(
            profile=status.run.get("profile", DEFAULT_PROFILE),
            action="adapter_attempt",
            confirmed=confirmed,
            run=status.run,
            contract=contract,
        )
        if profile_blockers:
            message = "Loop contract accepted; profile policy blocks adapter execution."
        else:
            message = (
                "Loop contract accepted; Phase 4 adapter execution is available "
                "with `loopforge continue --adapter <adapter>`."
            )
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=True,
            message=message,
            blockers=profile_blockers,
        )

    profile_blockers = profile_transition_blockers(
        profile=status.run.get("profile", DEFAULT_PROFILE),
        action="adapter_attempt",
        confirmed=confirmed,
        run=status.run,
        contract=contract,
    )
    if profile_blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the autonomy profile.",
            blockers=profile_blockers,
        )

    run = normalize_run_workflow_state(status.run)
    current_stage = run.get("current_stage", "")
    if current_stage == "plan_approved":
        run["current_stage"] = "implementation_ready"
        run["stage_statuses"]["implementation"] = "in_progress"
    elif current_stage == "implementation_ready":
        run["current_stage"] = "implementation_in_progress"
        run["stage_statuses"]["implementation"] = "in_progress"

    try:
        attempt = execute_attempt(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=run,
            contract=contract,
            adapter=adapter,
            adapter_args=adapter_args or [],
            operation_callback=operation_callback,
            cancel_event=cancel_event,
            stream_output=stream_output,
        )
        updated_run = update_run_after_attempt(
            project_dir=status.project_dir,
            run_json_path=status.run_json_path or (status.run_dir / "run.json"),
            run=run,
            attempt=attempt,
        )
    except (OSError, RuntimeError, ValueError) as error:
        blocker = f"adapter execution could not start: {error}"
        updated_run = dict(status.run)
        updated_run["status"] = ADAPTER_BLOCKED
        updated_run["blockers"] = [blocker]
        if status.run_json_path is not None:
            persist_run_json(status.project_dir, status.run_json_path, updated_run)
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=False,
            message="LoopForge adapter execution is blocked.",
            blockers=[blocker],
        )

    if attempt["status"] == "completed":
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=True,
            message="LoopForge adapter attempt completed; run is ready for verification.",
            blockers=[],
            attempt=attempt,
        )

    return ContinueResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated_run,
        contract=contract,
        ok=False,
        message="LoopForge adapter attempt ended in a blocked state.",
        blockers=updated_run.get("blockers", []),
        attempt=attempt,
    )
