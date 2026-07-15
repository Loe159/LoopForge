#!/usr/bin/env python3
"""Validate implementation adapter session and result contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from loopforge.contracts import policy_path

POLICY_PATH = policy_path("implementation-result-validation.json")

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "implementation_result_contract_validation",
    "mode": "validation-only",
    "max_result_bytes": 16384,
    "max_summary_chars": 1000,
    "allowed_statuses": ["completed", "blocked", "failed"],
    "candidate_ready_status": "completed",
    "status_next_actions": {
        "completed": "deterministic_patch_generation",
        "blocked": "human_review",
        "failed": "human_review",
    },
    "require_complete_capture": True,
    "require_completed_execution": True,
    "require_direct_child_reaped": True,
    "require_no_kill_requested": True,
    "require_zero_protocol_exit": True,
    "require_empty_stderr": True,
    "require_exact_capture_byte_counts": True,
    "require_workspace_change_for_candidate": True,
    "required_false_fields": [
        "patch_generated",
        "deterministic_checks_run",
        "publication_requested",
        "network_requested",
    ],
    "bindings": [
        "loopforge/checks/validate_implementation_result.py",
        "loopforge/contracts/policies/implementation-result-validation.json",
        "loopforge/contracts/schemas/implementation-result.schema.json",
    ],
}

SESSION_FIELDS = {
    "issue",
    "risk",
    "base_commit",
    "workspace",
    "runner_id",
    "preflight_sha256",
    "start_authorization_receipt_sha256",
}

RESULT_FIELDS = {
    "result_version",
    "purpose",
    "mode",
    "status",
    *SESSION_FIELDS,
    "summary",
    "workspace_changed",
    "patch_generated",
    "deterministic_checks_run",
    "publication_requested",
    "network_requested",
    "next_action",
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Implementation result validation policy does not match")
    return policy


def require_hex(value: Any, length: int, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError(f"{field} must be {length} lowercase hexadecimal characters")
    return value


def require_runner_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", value):
        raise ValueError(f"{field} must be a valid runner id")
    return value


def validate_expected_session(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != SESSION_FIELDS:
        missing = sorted(SESSION_FIELDS - set(value))
        extra = sorted(set(value) - SESSION_FIELDS)
        raise ValueError(f"Expected session fields mismatch; missing={missing}, extra={extra}")
    if not isinstance(value["issue"], int) or isinstance(value["issue"], bool) or value["issue"] < 1:
        raise ValueError("issue must be an integer >= 1")
    if value["risk"] not in {"low", "medium", "high"}:
        raise ValueError("risk must be low, medium, or high")
    require_hex(value["base_commit"], 40, "base_commit")
    if not isinstance(value["workspace"], str) or not value["workspace"].strip():
        raise ValueError("workspace must be a non-empty string")
    require_runner_id(value["runner_id"], "runner_id")
    require_hex(value["preflight_sha256"], 64, "preflight_sha256")
    require_hex(
        value["start_authorization_receipt_sha256"],
        64,
        "start_authorization_receipt_sha256",
    )
    return dict(value)


def validate_result(value: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy()
    if set(value) != RESULT_FIELDS:
        missing = sorted(RESULT_FIELDS - set(value))
        extra = sorted(set(value) - RESULT_FIELDS)
        raise ValueError(f"Implementation result fields mismatch; missing={missing}, extra={extra}")
    if value["result_version"] != 1:
        raise ValueError("result_version must be 1")
    if value["purpose"] != "implementation_session_result":
        raise ValueError("purpose must be implementation_session_result")
    if value["mode"] != "untrusted-runner-output":
        raise ValueError("mode must be untrusted-runner-output")
    session = validate_expected_session({key: value[key] for key in SESSION_FIELDS})
    if value["status"] not in policy["allowed_statuses"]:
        raise ValueError("status is not allowed")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        raise ValueError("summary must be a non-empty string")
    if len(value["summary"]) > policy["max_summary_chars"]:
        raise ValueError("summary exceeds the configured length limit")
    if not isinstance(value["workspace_changed"], bool):
        raise ValueError("workspace_changed must be a boolean")
    for field in policy["required_false_fields"]:
        if value[field] is not False:
            raise ValueError(f"{field} must be false")
    expected_next_action = policy["status_next_actions"][value["status"]]
    if value["next_action"] != expected_next_action:
        raise ValueError("next_action does not match status")
    if value["status"] == policy["candidate_ready_status"] and not value["workspace_changed"]:
        raise ValueError("completed results must report workspace changes")
    return {
        **value,
        **session,
    }


def canonical_result_bytes(value: dict[str, Any]) -> bytes:
    policy = load_policy()
    validated = validate_result(value, policy)
    content = json.dumps(validated, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(content) > policy["max_result_bytes"]:
        raise ValueError("Implementation result exceeds the configured size limit")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.path.read_text(encoding="utf-8"))
        canonical_result_bytes(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"validate-implementation-result: ERROR\n- {error}", file=sys.stderr)
        return 1
    print("implementation result valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
