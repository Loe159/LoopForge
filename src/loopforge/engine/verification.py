"""Verification and pack-checks domain for LoopForge runs.

Owns ``load_pack_checks`` (pack check resolution via the pack registry) and
``verify_run`` (the deterministic verification transaction: patch generation,
diff/risk policy enforcement, pack-check execution, stagnation detection, and
workflow-state transitions to verified/failed).

Extracted from ``engine/__init__.py``. Cross-domain helpers are pulled in via
lazy imports to avoid an import cycle; lifecycle/workflow/path-resolver/storage
and the ``execution`` sibling primitives are safe top-level imports.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from loopforge.engine.lifecycle import (
    RunStage,
    StageStatus,
)
from loopforge.engine.workflow import VerifyResult, revoke_verification_review_authority
from loopforge.engine.path_resolvers import resolve_confined, resolve_run_dir
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.execution import OperationCallback


def load_pack_checks(project_dir: Path, pack: str) -> dict[str, Any]:
    from loopforge.engine import _pack_registry

    return _pack_registry(project_dir).load_checks(pack)


def _previous_verification_for_stagnation(run: dict[str, Any]) -> dict[str, Any] | None:
    verification = run.get("verification")
    if isinstance(verification, dict):
        return verification

    history = run.get("verification_history")
    if not isinstance(history, list):
        return None
    for previous in reversed(history):
        if isinstance(previous, dict):
            return previous
    return None


def _has_admissible_implementation_candidate(attempts: object) -> bool:
    """Only the latest attempt can supply the candidate being verified.

    An interactive terminal can exit nonzero after changing the workspace;
    execute_attempt deliberately records that case as completed for recovery.
    """
    if not isinstance(attempts, list) or not attempts:
        return False
    latest = attempts[-1]
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return False
    returncode = latest.get("returncode")
    if not isinstance(returncode, int) or isinstance(returncode, bool):
        return False
    if returncode != 0 and not (
        latest.get("execution_mode") == "terminal"
        and latest.get("workspace_changed") is True
    ):
        return False
    return True


def _checks_match_bundled(
    registry: Any,
    pack: str,
    checks: list[dict[str, Any]],
    checks_hash: str,
) -> bool:
    try:
        bundled = registry.load_bundled_checks(pack)
    except (OSError, ValueError):
        return False
    bundled_checks = bundled.get("checks", [])
    return (
        bool(checks_hash)
        and isinstance(bundled_checks, list)
        and _checks_execute_equivalently(checks, bundled_checks)
    )


def _checks_execute_equivalently(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    if len(left) != len(right):
        return False
    for left_check, right_check in zip(left, right):
        if left_check.get("command") != right_check.get("command"):
            return False
        if (left_check.get("env") or {}) != (right_check.get("env") or {}):
            return False
        if left_check.get("timeout_seconds", 300) != right_check.get(
            "timeout_seconds",
            300,
        ):
            return False
    return True


def _verification_checks_snapshot(
    run_data: dict[str, Any],
    project_dir: Path,
    pack: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    str | None,
    str | None,
]:
    frozen_contract = run_data.get("pack_contract", {})
    frozen_checks = (
        frozen_contract.get("checks")
        if isinstance(frozen_contract, dict)
        else None
    )
    checks_source = (
        frozen_contract.get("checks_source")
        if isinstance(frozen_contract, dict)
        else None
    )
    checks_origin = (
        frozen_contract.get("checks_origin")
        if isinstance(frozen_contract, dict)
        else None
    )

    verification_commands = run_data.get("verification_commands")
    if isinstance(verification_commands, list) and verification_commands:
        execution_checks: list[dict[str, Any]] = []
        for command_config in verification_commands:
            if not isinstance(command_config, dict):
                continue
            command = command_config.get("command", [])
            if not isinstance(command, list) or not command:
                continue
            execution_checks.append(
                {
                    "name": command_config.get("criterion", ""),
                    "command": command,
                    "env": command_config.get("env") or {},
                    "timeout_seconds": command_config.get("timeout", 300),
                    "criterion": command_config.get("criterion", ""),
                }
            )

        if isinstance(frozen_checks, list) and _checks_execute_equivalently(
            execution_checks,
            frozen_checks,
        ):
            return execution_checks, frozen_checks, checks_source, checks_origin

        pack_config = load_pack_checks(project_dir, pack)
        current_checks = pack_config.get("checks", [])
        if isinstance(current_checks, list) and _checks_execute_equivalently(
            execution_checks,
            current_checks,
        ):
            return (
                execution_checks,
                current_checks,
                pack_config.get("source"),
                pack_config.get("origin"),
            )

        return execution_checks, execution_checks, None, None

    if isinstance(frozen_checks, list):
        return frozen_checks, frozen_checks, checks_source, checks_origin

    pack_config = load_pack_checks(project_dir, pack)
    current_checks = pack_config.get("checks", [])
    if not isinstance(current_checks, list):
        current_checks = []
    return (
        current_checks,
        current_checks,
        pack_config.get("source"),
        pack_config.get("origin"),
    )


def verify_run(
    project_dir: Path,
    *,
    confirmed: bool = False,
    operation_callback: OperationCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> VerifyResult:
    from loopforge.engine import (
        DEFAULT_PACK,
        DEFAULT_PROFILE,
        VERIFIED,
        VERIFICATION_FAILED,
        _build_criterion_results,
        _pack_registry,
        append_unique,
        current_status,
        default_diff_policy,
        default_risk_policy,
        emit_operation_event,
        failure_signature,
        loopforge_module_command,
        merged_risk_policy_path,
        normalize_run_workflow_state,
        persist_run_json,
        profile_transition_blockers,
        relative_to_run,
        render_verification_markdown,
        repository_root,
        run_json_check,
        run_pack_check,
        run_workspace_path,
        update_loop_diagnostic,
        utc_now,
        verification_state,
        write_json_atomic,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="Initialize LoopForge before verification.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            ok=False,
            message="No current run is ready for verification.",
            blockers=status.blockers or [status.next_step],
        )

    run = status.run
    run_dir = status.run_dir
    workspace_dir = run_workspace_path(run, status.project_dir)
    run_json_path = status.run_json_path or (run_dir / "run.json")
    profile_blockers = profile_transition_blockers(
        profile=run.get("profile", DEFAULT_PROFILE),
        action="verification",
        confirmed=confirmed,
        run=run,
        contract=status.loop_contract,
    )
    if profile_blockers:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge verification refused by the autonomy profile.",
            blockers=profile_blockers,
            verification=verification_state(run),
        )

    run_data = normalize_run_workflow_state(run)
    # P0: verify gates — the run must have passed its workflow gates.
    stage_statuses = run_data.get("stage_statuses", {})
    gate_blockers: list[str] = []
    if not run_data.get("approval", {}).get("approved"):
        gate_blockers.append("task_not_approved")
    if stage_statuses.get("plan") not in ("approved", "complete"):
        gate_blockers.append("plan_not_approved")
    if not _has_admissible_implementation_candidate(run_data.get("attempts")):
        gate_blockers.append("no_implementation_candidate")
    if gate_blockers:
        failed_run = revoke_verification_review_authority(
            run_data,
            reason="deterministic verification is blocked",
        )
        failed_run["updated_at"] = utc_now()
        failed_run["status"] = VERIFICATION_FAILED
        failed_run["blockers"] = gate_blockers
        failed_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        failed_run["stage_statuses"]["verification"] = "blocked"
        failed_run["verification"] = {
            "version": 1,
            "candidate_revision": failed_run["candidate_revision"],
            "status": "blocked",
            "blockers": gate_blockers,
            "checks": [],
            "checks_total": 0,
            "checks_passed": 0,
        }
        persist_run_json(status.project_dir, run_json_path, failed_run)
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=failed_run,
            ok=False,
            message="The run has not passed its workflow gates. "
            + ", ".join(gate_blockers),
            blockers=gate_blockers,
            verification=failed_run["verification"],
        )
    if "verification" not in run_data:
        run_data["verification"] = {
            "version": 1,
            "status": "not_run",
            "started_at": utc_now(),
            "finished_at": None,
            "checks": [],
            "checks_total": 0,
            "checks_passed": 0,
            "blockers": [],
        }
    base_commit = run_data.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        failed_run = revoke_verification_review_authority(
            run_data,
            reason="deterministic verification is blocked",
        )
        failed_run["updated_at"] = utc_now()
        failed_run["status"] = VERIFICATION_FAILED
        failed_run["blockers"] = ["no_base_commit"]
        failed_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        failed_run["stage_statuses"]["verification"] = "blocked"
        failed_run["verification"] = {
            "version": 1,
            "candidate_revision": failed_run["candidate_revision"],
            "status": "blocked",
            "blockers": ["no_base_commit"],
            "checks": [],
            "checks_total": 0,
            "checks_passed": 0,
        }
        persist_run_json(status.project_dir, run_json_path, failed_run)
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=failed_run,
            ok=False,
            message="A base commit is required for verification.",
            blockers=["no_base_commit"],
            verification=failed_run["verification"],
        )

    pack = str(run_data.get("pack") or DEFAULT_PACK)
    from loopforge.engine.packs import pack_trust_store as _pts

    def blocked_before_execution(blocker: str) -> VerifyResult:
        now = utc_now()
        acceptance_criteria = (
            run_data.get("acceptance_criteria")
            if isinstance(run_data.get("acceptance_criteria"), list)
            else []
        )
        verification = {
            "version": 1,
            "candidate_revision": run_data["candidate_revision"],
            "started_at": now,
            "finished_at": now,
            "status": "blocked",
            "patch": {
                "generated": False,
                "path": None,
                "size_bytes": 0,
                "sha256": None,
                "status": "not_run",
            },
            "diff_policy": {
                "allowed": None,
                "facts": {},
                "violations": [],
                "status": "not_run",
            },
            "risk": {
                "risk": None,
                "route": None,
                "policy_allowed": None,
                "reasons": [],
                "facts": {},
                "status": "not_run",
            },
            "pack": pack,
            "pack_checks_source": None,
            "acceptance_criteria": acceptance_criteria,
            "criterion_results": [
                {
                    "criterion": criterion,
                    "status": "blocked",
                    "checks": [],
                }
                for criterion in acceptance_criteria
            ],
            "checks": [],
            "checks_total": 0,
            "checks_passed": 0,
            "blockers": [blocker],
        }
        updated_run = revoke_verification_review_authority(
            run_data,
            reason="deterministic verification is blocked",
        )
        updated_run["verification"] = verification
        updated_run["updated_at"] = now
        updated_run["status"] = VERIFICATION_FAILED
        updated_run["blockers"] = [blocker]
        updated_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        updated_run["stage_statuses"]["verification"] = StageStatus.BLOCKED.value
        persist_run_json(status.project_dir, run_json_path, updated_run)
        (run_dir / "verification.md").write_text(
            render_verification_markdown(verification),
            encoding="utf-8",
        )
        update_loop_diagnostic(run_dir, verification)
        emit_operation_event(
            operation_callback,
            "blocked",
            blocker,
            artifact=str(run_dir / "verification.md"),
            status="blocked",
        )
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=updated_run,
            ok=False,
            message="LoopForge verification is blocked.",
            blockers=[blocker],
            verification=verification,
        )

    trust_check = _pts(home=None)
    registry = _pack_registry(status.project_dir)
    try:
        (
            pack_checks,
            trust_checks,
            pack_checks_source,
            checks_origin,
        ) = _verification_checks_snapshot(
            run_data,
            status.project_dir,
            pack,
        )
    except (OSError, ValueError) as error:
        return blocked_before_execution(
            f"pack checks could not be loaded: {error}"
        )
    pack_hash = (
        registry._compute_content_hash(trust_checks)
        if trust_checks
        else ""
    )

    if pack_hash:
        bundled_match = _checks_match_bundled(
            registry,
            pack,
            trust_checks,
            pack_hash,
        )
        checks_are_bundled = (
            checks_origin == "bundled"
            or checks_origin is None
        ) and bundled_match
        if not checks_are_bundled and not trust_check.is_trusted(pack_hash):
            blocker_msg = (
                f"Pack '{pack}' is not trusted. "
                f"Run `loopforge trust pack {pack}` or use interactive mode."
            )
            return VerifyResult(
                project_dir=status.project_dir,
                run_dir=run_dir,
                run=run_data,
                ok=False,
                message=(
                    f"Pack '{pack}' is not trusted. "
                    f"Run `loopforge trust pack {pack}` or use interactive mode."
                ),
                blockers=[blocker_msg],
                verification=verification_state(run_data),
            )

    started = utc_now()
    patch_dir = run_dir / "artifacts" / "patches"
    patch_path = patch_dir / "complete.patch"
    blockers: list[str] = []
    patch_summary: dict[str, Any] = {
        "generated": False,
        "path": None,
        "size_bytes": 0,
        "sha256": None,
        "status": "not_run",
    }
    diff_summary: dict[str, Any] = {
        "allowed": None,
        "facts": {},
        "violations": [],
        "status": "not_run",
    }
    risk_summary: dict[str, Any] = {
        "risk": None,
        "route": None,
        "policy_allowed": None,
        "reasons": [],
        "facts": {},
        "status": "not_run",
    }
    checks: list[dict[str, Any]] = []
    risk_policy_sources: list[str] = []
    risk_policy_path: Path | None = None

    emit_operation_event(operation_callback, "stage_started", "Starting deterministic verification.")

    def cancelled_result() -> VerifyResult | None:
        if cancel_event is None or not cancel_event.is_set():
            return None
        blocker = "verification was interrupted before the next check."
        interrupted_run = revoke_verification_review_authority(
            run_data,
            reason="deterministic verification is blocked",
        )
        interrupted_run["updated_at"] = utc_now()
        interrupted_run["status"] = VERIFICATION_FAILED
        interrupted_run["blockers"] = [blocker]
        interrupted_run["current_stage"] = "verification_blocked"
        interrupted_run["stage_statuses"]["verification"] = "blocked"
        interrupted_run["verification"] = {
            "version": 1,
            "candidate_revision": interrupted_run["candidate_revision"],
            "status": "blocked",
            "blockers": [blocker],
            "checks": [],
            "checks_total": 0,
            "checks_passed": 0,
        }
        persist_run_json(status.project_dir, run_json_path, interrupted_run)
        emit_operation_event(operation_callback, "cancelled", blocker, status="cancelled")
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=interrupted_run,
            ok=False,
            message="LoopForge verification was interrupted.",
            blockers=[blocker],
            verification=verification_state(interrupted_run),
        )

    base_commit = run.get("base_commit")
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        blockers.append(f"patch generation requires the run workspace: {workspace_dir}.")
    else:
        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Generating complete patch.", current=1, total=4)
        generated = run_json_check(
            loopforge_module_command(
                "loopforge.checks.generate_complete_patch",
                [
                    "--repo",
                    str(workspace_dir),
                    "--base",
                    base_commit,
                    "--output",
                    str(patch_path),
                    "--policy",
                    str(default_diff_policy()),
                    "--force",
                    "--format",
                    "json",
                ],
            ),
            cwd=repository_root(),
        )
        if generated["returncode"] != 0 or generated["json"] is None:
            error = generated["stderr"].strip() or generated["stdout"].strip()
            patch_summary.update({"status": "failed", "error": error})
            blockers.append(f"patch generation failed: {error or 'unknown error'}")
        else:
            patch_result = generated["json"]
            artifact = patch_result.get("artifact", {})
            if not isinstance(artifact, dict):
                artifact = {}
            patch_summary.update(
                {
                    "generated": bool(artifact.get("retained", False)),
                    "path": relative_to_run(run_dir, patch_path) if artifact.get("retained") else None,
                    "size_bytes": artifact.get("size_bytes", 0),
                    "sha256": artifact.get("sha256"),
                    "status": "generated" if artifact.get("retained") else "not_retained",
                }
            )
            if patch_summary["generated"]:
                try:
                    actual_patch_size = patch_path.stat().st_size
                except OSError as error:
                    patch_summary.update({"status": "failed", "error": str(error)})
                    blockers.append(f"generated patch could not be inspected: {error}")
                else:
                    patch_summary["size_bytes"] = actual_patch_size
                    if actual_patch_size == 0:
                        patch_summary["status"] = "empty"
                        blockers.append("no_implementation_changes")
            diff_summary.update(
                {
                    "allowed": bool(patch_result.get("allowed", False)),
                    "facts": patch_result.get("facts", {}),
                    "violations": patch_result.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                blockers.append("diff policy blocked the generated patch.")
        emit_operation_event(operation_callback, "check_finished", "Complete patch generation finished.", current=1, total=4)

    if patch_path.exists() and isinstance(base_commit, str) and base_commit:
        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Enforcing diff policy.", current=2, total=4)
        diff_result = run_json_check(
            loopforge_module_command(
                "loopforge.checks.diff_policy",
                [
                    "--patch",
                    str(patch_path),
                    "--policy",
                    str(default_diff_policy()),
                    "--repo",
                    str(workspace_dir),
                    "--base",
                    str(base_commit),
                    "--format",
                    "json",
                ],
            ),
            cwd=repository_root(),
        )
        if diff_result["returncode"] == 0 and diff_result["json"] is not None:
            diff_payload = diff_result["json"]
            diff_summary.update(
                {
                    "allowed": bool(diff_payload.get("allowed", False)),
                    "facts": diff_payload.get("facts", {}),
                    "violations": diff_payload.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                append_unique(blockers, "diff policy blocked the generated patch.")
        else:
            error = diff_result["stderr"].strip() or diff_result["stdout"].strip()
            diff_summary.update({"status": "failed", "error": error})
            blockers.append(f"diff policy failed: {error or 'unknown error'}")
        emit_operation_event(operation_callback, "check_finished", "Diff policy finished.", current=2, total=4)

        try:
            risk_policy_path, risk_policy_sources = merged_risk_policy_path(
                project_dir=status.project_dir,
                run_dir=run_dir,
                pack=str(run.get("pack") or DEFAULT_PACK),
                run=run,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            risk_summary.update({"status": "failed", "error": str(error)})
            blockers.append(f"risk policy could not be loaded: {error}")

        interrupted = cancelled_result()
        if interrupted is not None:
            return interrupted
        emit_operation_event(operation_callback, "check_started", "Classifying patch risk.", current=3, total=4)
        risk_result = run_json_check(
            loopforge_module_command(
                "loopforge.checks.classify_patch_risk",
                [
                    "--patch",
                    str(patch_path),
                    "--diff-policy",
                    str(default_diff_policy()),
                    "--risk-policy",
                    str(risk_policy_path or default_risk_policy()),
                    "--repo",
                    str(workspace_dir),
                    "--base",
                    str(base_commit),
                    "--format",
                    "json",
                ],
            ),
            cwd=repository_root(),
        )
        if risk_result["returncode"] == 0 and risk_result["json"] is not None:
            risk_payload = risk_result["json"]
            risk_summary.update(
                {
                    "risk": risk_payload.get("risk"),
                    "route": risk_payload.get("route"),
                    "policy_allowed": risk_payload.get("policy_allowed"),
                    "reasons": risk_payload.get("reasons", []),
                    "facts": risk_payload.get("facts", {}),
                    "human_gates": risk_payload.get("human_gates", {}),
                    "required_gates": risk_payload.get("required_gates", []),
                    "policy": (
                        relative_to_run(run_dir, risk_policy_path)
                        if risk_policy_path is not None
                        else str(default_risk_policy())
                    ),
                    "policy_sources": risk_policy_sources,
                    "status": "completed",
                }
            )
            run_data["risk"] = {
                "level": risk_payload.get("risk"),
                "route": risk_payload.get("route"),
                "reasons": risk_payload.get("reasons", []),
                "required_gates": risk_payload.get("required_gates", []),
            }
        else:
            error = risk_result["stderr"].strip() or risk_result["stdout"].strip()
            risk_summary.update({"status": "failed", "error": error})
            blockers.append(f"risk classification failed: {error or 'unknown error'}")
        emit_operation_event(operation_callback, "check_finished", "Patch risk classification finished.", current=3, total=4)

    try:
        for index, check in enumerate(pack_checks, start=1):
            interrupted = cancelled_result()
            if interrupted is not None:
                return interrupted
            emit_operation_event(
                operation_callback,
                "check_started",
                f"Running {check['name']}.",
                current=index,
                total=len(pack_checks),
            )
            result = run_pack_check(
                check,
                project_dir=workspace_dir,
                run_dir=run_dir,
                patch_path=patch_path if patch_path.exists() else None,
            )
            criterion = check.get("criterion", "")
            if criterion and isinstance(criterion, str) and criterion.strip():
                result["criterion"] = criterion.strip()
            checks.append(result)
            emit_operation_event(
                operation_callback,
                "check_finished",
                f"{check['name']} {result['status']}.",
                current=index,
                total=len(pack_checks),
                status=str(result["status"]),
            )
            if result["status"] != "passed":
                criterion = check.get("criterion", "")
                if criterion and isinstance(criterion, str):
                    blockers.append(
                        f"pack check failed: {result['name']} → {criterion} "
                        f"({result['status']})."
                    )
                else:
                    blockers.append(
                        f"pack check failed: {result['name']} ({result['status']})."
                    )
    except ValueError as error:
        blockers.append(f"pack checks could not be loaded: {error}")

    finished = utc_now()
    checks_passed = sum(1 for check in checks if check.get("status") == "passed")
    verification: dict[str, Any] = {
        "version": 1,
        "candidate_revision": normalize_run_workflow_state(run_data)["candidate_revision"],
        "started_at": started,
        "finished_at": finished,
        "status": "blocked" if blockers else "passed",
        "patch": patch_summary,
        "diff_policy": diff_summary,
        "risk": risk_summary,
        "pack": run.get("pack") or DEFAULT_PACK,
        "pack_checks_source": pack_checks_source,
        "acceptance_criteria": run.get("acceptance_criteria") if isinstance(run.get("acceptance_criteria"), list) else [],
        "criterion_results": _build_criterion_results(
            run.get("acceptance_criteria") if isinstance(run.get("acceptance_criteria"), list) else [],
            checks,
        ),
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": checks_passed,
        "blockers": blockers,
    }
    signature = failure_signature(verification)
    if signature:
        previous = _previous_verification_for_stagnation(run)
        if (
            isinstance(previous, dict)
            and previous.get("failure_signature") == signature
            and previous.get("status") in ("failed", "blocked")
        ):
            verification["stagnated"] = True
            append_unique(blockers, "stagnation: repeated equivalent verification failure.")
        verification["failure_signature"] = signature
    verification["blockers"] = blockers
    if blockers:
        verification["status"] = "blocked"

    (run_dir / "verification.md").write_text(
        render_verification_markdown(verification),
        encoding="utf-8",
    )
    update_loop_diagnostic(run_dir, verification)

    updated_run = revoke_verification_review_authority(
        run_data,
        reason=(
            "deterministic verification is blocked"
            if blockers
            else "read-only review and approval are required before draft publication"
        ),
    )
    updated_run["verification"] = verification
    updated_run["updated_at"] = utc_now()
    updated_run["status"] = VERIFIED if not blockers else VERIFICATION_FAILED
    updated_run["blockers"] = [] if not blockers else blockers
    if not blockers:
        updated_run["current_stage"] = RunStage.VERIFICATION_READY.value
        updated_run["stage_statuses"]["verification"] = "complete"
    else:
        updated_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        updated_run["stage_statuses"]["verification"] = StageStatus.BLOCKED.value
    persist_run_json(status.project_dir, run_json_path, updated_run)
    emit_operation_event(
        operation_callback,
        "completed" if not blockers else "blocked",
        "Verification passed." if not blockers else "Verification is blocked.",
        artifact=str(run_dir / "verification.md"),
        status="completed" if not blockers else "blocked",
    )

    return VerifyResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=updated_run,
        ok=not blockers,
        message="LoopForge verification passed." if not blockers else "LoopForge verification failed.",
        blockers=blockers,
        verification=verification,
    )
