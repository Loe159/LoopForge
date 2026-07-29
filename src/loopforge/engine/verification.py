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
from loopforge.engine.workflow import VerifyResult
from loopforge.engine.path_resolvers import resolve_confined, resolve_run_dir
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.execution import OperationCallback


def load_pack_checks(project_dir: Path, pack: str) -> dict[str, Any]:
    from loopforge.engine import _pack_registry

    return _pack_registry(project_dir).load_checks(pack)


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
        initial_workflow_state,
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
    attempts = run_data.get("attempts", [])
    has_candidate = isinstance(attempts, list) and any(
        isinstance(a, dict) and a.get("returncode") is not None for a in attempts
    )
    if not has_candidate:
        gate_blockers.append("no_implementation_candidate")
    if gate_blockers:
        failed_run = normalize_run_workflow_state(run_data)
        failed_run["updated_at"] = utc_now()
        failed_run["status"] = VERIFICATION_FAILED
        failed_run["blockers"] = gate_blockers
        failed_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        failed_run["stage_statuses"]["verification"] = "blocked"
        failed_run["verification"] = verification_state(failed_run)
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
        failed_run = normalize_run_workflow_state(run_data)
        failed_run["updated_at"] = utc_now()
        failed_run["status"] = VERIFICATION_FAILED
        failed_run["blockers"] = ["no_base_commit"]
        failed_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        failed_run["stage_statuses"]["verification"] = "blocked"
        failed_run["verification"] = verification_state(failed_run)
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
    try:
        from loopforge.engine.packs import pack_trust_store as _pts
        trust_check = _pts(home=None)
        frozen_contract = run_data.get("pack_contract", {})
        pack_hash = frozen_contract.get("checks_content_hash", "") if isinstance(frozen_contract, dict) else ""
        pack_source = frozen_contract.get("source") if isinstance(frozen_contract, dict) else None
        if not pack_hash:
            pack_config = load_pack_checks(status.project_dir, pack)
            pack_hash = pack_config.get("content_hash", "")
            pack_source = pack_config.get("source") if not pack_source else pack_source
        if pack_hash and pack_source is not None:
            registry = _pack_registry(status.project_dir)
            bundled_root = str(registry.bundled_packs_path())
            pack_is_bundled = pack_source.startswith(bundled_root)
            if not pack_is_bundled and not trust_check.is_trusted(pack_hash):
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
    except ValueError:
        pass

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
    pack_checks_source: str | None = None
    risk_policy_sources: list[str] = []
    risk_policy_path: Path | None = None

    emit_operation_event(operation_callback, "stage_started", "Starting deterministic verification.")

    def cancelled_result() -> VerifyResult | None:
        if cancel_event is None or not cancel_event.is_set():
            return None
        blocker = "verification was interrupted before the next check."
        interrupted_run = normalize_run_workflow_state(run)
        interrupted_run["updated_at"] = utc_now()
        interrupted_run["status"] = VERIFICATION_FAILED
        interrupted_run["blockers"] = [blocker]
        interrupted_run["current_stage"] = "verification_blocked"
        interrupted_run["stage_statuses"]["verification"] = "blocked"
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
        verification_commands = run_data.get("verification_commands")
        if isinstance(verification_commands, list) and verification_commands:
            run_checks = []
            for vc in verification_commands:
                if not isinstance(vc, dict):
                    continue
                command = vc.get("command", [])
                if not isinstance(command, list) or not command:
                    continue
                run_checks.append(
                    {
                        "name": vc.get("criterion", ""),
                        "command": command,
                        "env": vc.get("env") or {},
                        "timeout_seconds": vc.get("timeout", 300),
                        "criterion": vc.get("criterion", ""),
                    }
                )
            pack_checks_source = run_data.get("pack_contract", {}).get("checks_file")
            pack_checks = run_checks
        else:
            frozen_checks = run_data.get("pack_contract", {}).get("checks")
            if frozen_checks is not None and isinstance(frozen_checks, list):
                pack_checks_source = run_data.get("pack_contract", {}).get("source")
                pack_checks = frozen_checks
            else:
                pack_config = load_pack_checks(status.project_dir, str(run_data.get("pack") or DEFAULT_PACK))
                pack_checks_source = pack_config.get("source")
                pack_checks = pack_config["checks"]
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
        previous = verification_state(run)
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

    updated_run = normalize_run_workflow_state(run_data)
    updated_run["verification"] = verification
    updated_run["updated_at"] = utc_now()
    updated_run["status"] = VERIFIED if not blockers else VERIFICATION_FAILED
    updated_run["blockers"] = [] if not blockers else blockers
    if not blockers:
        updated_run["current_stage"] = RunStage.VERIFICATION_READY.value
        updated_run["stage_statuses"]["verification"] = "complete"
        updated_run["stage_statuses"]["review"] = StageStatus.PENDING.value
        updated_run["human_gates"]["review_approval"] = {
            **initial_workflow_state()["human_gates"]["review_approval"],
            "status": "pending",
        }
        updated_run["publish_eligibility"] = {
            "eligible": False,
            "reasons": ["read-only review and approval are required before draft publication"],
        }
    else:
        updated_run["current_stage"] = RunStage.VERIFICATION_BLOCKED.value
        updated_run["stage_statuses"]["verification"] = StageStatus.BLOCKED.value
        if updated_run["stage_statuses"].get("review") not in {"approved", "complete"}:
            updated_run["stage_statuses"]["review"] = StageStatus.PENDING.value
        updated_run["publish_eligibility"] = {
            "eligible": False,
            "reasons": ["deterministic verification is blocked"],
        }
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
