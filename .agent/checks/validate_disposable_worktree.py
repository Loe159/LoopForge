#!/usr/bin/env python3
"""Validate one exact prepared disposable worktree without authorizing its use."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import prepare_disposable_worktree


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / ".agent" / "policies" / "disposable-worktree-validation.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
FALSE_FIELDS = prepare_disposable_worktree.FALSE_FIELDS
INVARIANT_FIELDS = (
    "workspace_head_matches_base",
    "workspace_detached",
    "workspace_clean",
    "workspace_root_matches_target",
    "source_head_unchanged",
    "source_branches_unchanged",
    "source_status_unchanged",
    "worktree_registration_added",
)

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "disposable_implementation_worktree_validation",
    "mode": "validation-only",
    "command_timeout_seconds": 15,
    "max_receipt_bytes": 20000,
    "require_external_receipt": True,
    "require_receipt_outside_workspace": True,
    "require_source_clean": True,
    "require_source_head_match": True,
    "require_workspace_registered": True,
    "require_workspace_detached": True,
    "require_workspace_clean": True,
    "require_workspace_head_match": True,
    "trusted_receipt_bindings": [
        ".agent/checks/prepare_disposable_worktree.py",
        ".agent/policies/disposable-worktree-preparation.json",
    ],
    "validator_bindings": [
        ".agent/checks/validate_disposable_worktree.py",
        ".agent/policies/disposable-worktree-validation.json",
    ],
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Disposable-worktree validation policy does not match the pilot contract")
    return policy


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def binding_record(name: str) -> dict[str, Any]:
    path = REPO_ROOT / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Validation binding must be an existing regular file: {name}")
    content = path.read_bytes()
    return {"name": name, "sha256": sha256_bytes(content), "size_bytes": len(content)}


def binding_records(names: list[str]) -> list[dict[str, Any]]:
    return [binding_record(name) for name in names]


def exact_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            exact_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def failure(rule: str, message: str) -> dict[str, str]:
    return {"rule": rule, "message": message}


def base_result(expected_sha256: str) -> dict[str, Any]:
    return {
        "valid": False,
        **{field: False for field in FALSE_FIELDS},
        "receipt_sha256": expected_sha256,
        "base_commit": None,
        "failures": [],
    }


def validate_binding_values(value: Any, expected_names: list[str]) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(expected_names)
        and all(
            isinstance(record, dict)
            and set(record) == {"name", "sha256", "size_bytes"}
            and record["name"] == name
            and isinstance(record["sha256"], str)
            and SHA256.fullmatch(record["sha256"]) is not None
            and type(record["size_bytes"]) is int
            and record["size_bytes"] > 0
            for record, name in zip(value, expected_names, strict=True)
        )
    )


def validate_receipt_value(
    value: Any,
    source: Path,
    workspace: Path,
    policy: dict[str, Any],
) -> tuple[list[dict[str, str]], str | None]:
    failures: list[dict[str, str]] = []
    expected_fields = {
        "receipt_version",
        "purpose",
        "mode",
        *FALSE_FIELDS,
        "workspace_prepared",
        "cleanup_required",
        "source_git_metadata_changed",
        "source_repo",
        "workspace",
        "base_commit",
        "invariants",
        "bindings",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        return [failure("receipt_schema", "Receipt fields do not match the contract.")], None
    if (
        type(value["receipt_version"]) is not int
        or value["receipt_version"] != prepare_disposable_worktree.EXPECTED_POLICY["version"]
        or value["purpose"] != prepare_disposable_worktree.EXPECTED_POLICY["purpose"]
        or value["mode"] != prepare_disposable_worktree.EXPECTED_POLICY["mode"]
        or any(value[field] is not False for field in FALSE_FIELDS)
        or value["workspace_prepared"] is not True
        or value["cleanup_required"] is not True
        or value["source_git_metadata_changed"] is not True
    ):
        failures.append(failure("receipt_metadata", "Receipt safety metadata does not match."))
    base = value["base_commit"]
    if (
        type(value["source_repo"]) is not str
        or Path(value["source_repo"]).resolve() != source
        or type(value["workspace"]) is not str
        or Path(value["workspace"]).resolve() != workspace
        or type(base) is not str
        or prepare_disposable_worktree.COMMIT.fullmatch(base) is None
    ):
        failures.append(failure("receipt_identity", "Receipt identity does not match inputs."))
        base = None
    expected_invariants = {name: True for name in INVARIANT_FIELDS}
    if not exact_equal(value["invariants"], expected_invariants):
        failures.append(failure("receipt_invariants", "Receipt invariants do not match."))
    if not validate_binding_values(value["bindings"], policy["trusted_receipt_bindings"]):
        failures.append(failure("receipt_bindings", "Receipt bindings do not match the contract."))
    elif not exact_equal(value["bindings"], binding_records(policy["trusted_receipt_bindings"])):
        failures.append(failure("trusted_binding_mismatch", "Receipt bindings differ from trusted bytes."))
    return failures, base


def registered_worktree(output: bytes, workspace: Path, base: str) -> bool:
    records = output.decode("utf-8").strip().split("\n\n")
    expected_path = str(workspace).replace("\\", "/")
    for record in records:
        lines = record.splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        path = lines[0][len("worktree ") :].replace("\\", "/")
        if path == expected_path:
            return f"HEAD {base}" in lines and "detached" in lines
    return False


def validate(
    source: Path,
    workspace: Path,
    receipt: Path,
    expected_sha256: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    result = base_result(expected_sha256)
    if not SHA256.fullmatch(expected_sha256):
        raise ValueError("Expected receipt SHA-256 must be 64 lowercase hexadecimal characters")
    if source.is_symlink() or workspace.is_symlink() or receipt.is_symlink():
        raise ValueError("Source, workspace, and receipt symbolic links are not allowed")
    timeout = policy["command_timeout_seconds"]
    source_root = Path(
        prepare_disposable_worktree.git_output(source, timeout, "rev-parse", "--show-toplevel")
        .decode("utf-8")
        .strip()
    ).resolve()
    workspace = workspace.resolve()
    receipt = receipt.resolve()
    if policy["require_external_receipt"] and prepare_disposable_worktree.is_within(
        receipt,
        source_root,
    ):
        raise ValueError("Disposable-worktree receipt must be outside the source checkout")
    if policy["require_receipt_outside_workspace"] and prepare_disposable_worktree.is_within(
        receipt,
        workspace,
    ):
        raise ValueError("Disposable-worktree receipt must be outside the workspace")
    if not workspace.is_dir():
        raise ValueError("Disposable workspace must be an existing directory")
    if not receipt.is_file():
        raise ValueError("Disposable-worktree receipt must be an existing regular file")
    if receipt.stat().st_size > policy["max_receipt_bytes"]:
        result["failures"].append(failure("max_receipt_bytes", "Receipt exceeds the byte limit."))
        return result

    receipt_bytes = receipt.read_bytes()
    if sha256_bytes(receipt_bytes) != expected_sha256:
        result["failures"].append(
            failure("receipt_sha256", "Receipt does not match its expected SHA-256.")
        )
        return result
    value = json.loads(receipt_bytes.decode("utf-8-sig"))
    failures, base = validate_receipt_value(value, source_root, workspace, policy)
    result["failures"].extend(failures)
    result["base_commit"] = base
    if base is None:
        return result

    source_before = prepare_disposable_worktree.source_snapshot(source_root, timeout)
    workspace_before = prepare_disposable_worktree.workspace_snapshot(workspace, timeout)
    if policy["require_source_clean"] and source_before["status"]:
        result["failures"].append(failure("source_clean", "Source checkout must be clean."))
    if policy["require_source_head_match"] and source_before["head"].decode("ascii") != base:
        result["failures"].append(failure("source_head_match", "Source HEAD differs from receipt base."))
    if policy["require_workspace_head_match"] and workspace_before["head"].decode("ascii") != base:
        result["failures"].append(
            failure("workspace_head_match", "Workspace HEAD differs from receipt base.")
        )
    if policy["require_workspace_detached"] and not workspace_before["detached"]:
        result["failures"].append(failure("workspace_detached", "Workspace must be detached."))
    if policy["require_workspace_clean"] and workspace_before["status"]:
        result["failures"].append(failure("workspace_clean", "Workspace must be clean."))
    if Path(workspace_before["root"]).resolve() != workspace:
        result["failures"].append(failure("workspace_root", "Workspace root differs from input."))
    if policy["require_workspace_registered"] and not registered_worktree(
        source_before["worktrees"],
        workspace,
        base,
    ):
        result["failures"].append(
            failure("workspace_registered", "Workspace is not exactly registered as detached.")
        )
    if result["failures"]:
        return result

    validator_bindings = binding_records(policy["validator_bindings"])
    source_after = prepare_disposable_worktree.source_snapshot(source_root, timeout)
    workspace_after = prepare_disposable_worktree.workspace_snapshot(workspace, timeout)
    refreshed_validator_bindings = binding_records(policy["validator_bindings"])
    refreshed_receipt = receipt.read_bytes()
    if (
        sha256_bytes(refreshed_receipt) != expected_sha256
        or not exact_equal(source_after, source_before)
        or not exact_equal(workspace_after, workspace_before)
        or not exact_equal(refreshed_validator_bindings, validator_bindings)
    ):
        result["failures"].append(
            failure("state_changed", "Receipt, repository, workspace, or validator changed.")
        )
        return result
    result.update(valid=True, validator_bindings=validator_bindings)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def format_text(result: dict[str, Any]) -> str:
    status = "VALID" if result["valid"] else "INVALID"
    lines = [
        f"disposable-worktree-validation: {status}",
        "workspace_use_authorized=false",
        "agent_invocation_authorized=false",
    ]
    lines.extend(f"- {item['rule']}: {item['message']}" for item in result["failures"])
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = validate(
            args.source,
            args.workspace,
            args.receipt,
            args.receipt_sha256,
            load_policy(),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"disposable-worktree-validation: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
