#!/usr/bin/env python3
"""Build a deterministic post-run metrics record from bounded explicit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import build_stage_context
import diff_policy


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / ".agent" / "policies" / "run-metrics.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,119}")
RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
FALSE_FIELDS = (
    "authorized",
    "agent_invocation_authorized",
    "implementation_authorized",
    "repository_mutation_authorized",
    "network_authorized",
    "publication_authorized",
    "runner_selected",
    "session_start_authorized",
)

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "agentic_run_metrics_record",
    "mode": "manual-evidence-recording-only",
    "max_observation_bytes": 30000,
    "max_patch_bytes": 20000000,
    "max_record_bytes": 50000,
    "max_duration_ms": 604800000,
    "require_external_observation": True,
    "require_external_patch": True,
    "require_external_record": True,
    "require_absent_record": True,
    "stages": ["research", "plan", "implement", "review"],
    "outcome_statuses": ["succeeded", "failed", "blocked", "cancelled", "timed_out"],
    "measurement_statuses": ["reported", "estimated", "unavailable"],
    "final_dispositions": ["pending", "merged", "rejected", "not_applicable"],
    "regression_statuses": ["not_assessed", "none_detected", "detected"],
    "bindings": [
        ".agent/checks/record_run_metrics.py",
        ".agent/policies/run-metrics.json",
        ".agent/checks/diff_policy.py",
    ],
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Run-metrics policy does not match the pilot contract")
    return policy


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def binding_records(repo: Path, names: list[str]) -> list[dict[str, Any]]:
    records = []
    for name in names:
        path = repo / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Run-metrics binding must be an existing regular file: {name}")
        content = path.read_bytes()
        records.append(
            {
                "name": name,
                "sha256": sha256_bytes(content),
                "size_bytes": len(content),
            }
        )
    return records


def require_exact_fields(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} fields do not match the contract")
    return value


def require_identifier(value: Any, name: str) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def parse_timestamp(value: Any, name: str) -> datetime:
    if type(value) is not str or UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp ending in Z")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{name} must use UTC")
    return parsed


def validate_measurement(
    value: Any,
    name: str,
    policy: dict[str, Any],
    value_fields: tuple[str, ...],
    extra_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    fields = {"status", "source", *value_fields, *extra_fields}
    measurement = require_exact_fields(value, fields, name)
    status = measurement["status"]
    if status not in policy["measurement_statuses"]:
        raise ValueError(f"{name}.status is unsupported")
    expected_source = {
        "reported": "provider_report",
        "estimated": "manual_estimate",
        "unavailable": "unavailable",
    }[status]
    if measurement["source"] != expected_source:
        raise ValueError(f"{name}.source is inconsistent with its status")
    for field in value_fields:
        measured = measurement[field]
        if status == "unavailable":
            if measured is not None:
                raise ValueError(f"{name}.{field} must be null when unavailable")
        elif type(measured) is not int or measured < 0:
            raise ValueError(f"{name}.{field} must be a non-negative integer")
    return measurement


def validate_observation(value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "observation_version",
        "purpose",
        "mode",
        "run_id",
        "issue",
        "stage",
        "base_commit",
        "adapter",
        "model",
        "timing",
        "tokens",
        "cost",
        "outcome",
        "human_corrections",
        "final_disposition",
        "regression_status",
        "diff_status",
        "patch_sha256",
    }
    observation = require_exact_fields(value, fields, "Observation")
    if (
        type(observation["observation_version"]) is not int
        or observation["observation_version"] != policy["version"]
        or observation["purpose"] != "agentic_run_metrics_observation"
        or observation["mode"] != "post-run-observation"
        or type(observation["run_id"]) is not str
        or RUN_ID.fullmatch(observation["run_id"]) is None
        or type(observation["issue"]) is not int
        or observation["issue"] < 1
        or observation["stage"] not in policy["stages"]
        or type(observation["base_commit"]) is not str
        or COMMIT.fullmatch(observation["base_commit"]) is None
    ):
        raise ValueError("Observation identity does not match the contract")

    adapter = require_exact_fields(observation["adapter"], {"id", "version"}, "adapter")
    require_identifier(adapter["id"], "adapter.id")
    require_identifier(adapter["version"], "adapter.version")
    model = require_exact_fields(observation["model"], {"provider", "id"}, "model")
    require_identifier(model["provider"], "model.provider")
    require_identifier(model["id"], "model.id")

    timing = require_exact_fields(
        observation["timing"],
        {"started_at", "completed_at"},
        "timing",
    )
    started = parse_timestamp(timing["started_at"], "timing.started_at")
    completed = parse_timestamp(timing["completed_at"], "timing.completed_at")
    duration_ms = int((completed - started).total_seconds() * 1000)
    if duration_ms < 0 or duration_ms > policy["max_duration_ms"]:
        raise ValueError("Observed duration is negative or exceeds the pilot maximum")

    validate_measurement(
        observation["tokens"],
        "tokens",
        policy,
        ("input_tokens", "output_tokens"),
    )
    cost = validate_measurement(
        observation["cost"],
        "cost",
        policy,
        ("amount_microunits",),
        ("currency",),
    )
    if cost["status"] == "unavailable":
        if cost.get("currency") is not None:
            raise ValueError("cost.currency must be null when cost is unavailable")
    elif type(cost.get("currency")) is not str or re.fullmatch(r"[A-Z]{3}", cost["currency"]) is None:
        raise ValueError("cost.currency must be a three-letter uppercase currency code")

    outcome = require_exact_fields(observation["outcome"], {"status"}, "outcome")
    if outcome["status"] not in policy["outcome_statuses"]:
        raise ValueError("outcome.status is unsupported")
    corrections = require_exact_fields(
        observation["human_corrections"],
        {"status", "count"},
        "human_corrections",
    )
    if corrections["status"] == "not_assessed":
        if corrections["count"] is not None:
            raise ValueError("human_corrections.count must be null when not assessed")
    elif corrections["status"] == "measured":
        if type(corrections["count"]) is not int or corrections["count"] < 0:
            raise ValueError("human_corrections.count must be a non-negative integer")
    else:
        raise ValueError("human_corrections.status is unsupported")
    if observation["final_disposition"] not in policy["final_dispositions"]:
        raise ValueError("final_disposition is unsupported")
    if observation["regression_status"] not in policy["regression_statuses"]:
        raise ValueError("regression_status is unsupported")
    if observation["diff_status"] not in {"measured", "not_applicable"}:
        raise ValueError("diff_status is unsupported")
    outcome_status = outcome["status"]
    if (
        observation["stage"] == "implement"
        and outcome_status == "succeeded"
        and observation["diff_status"] != "measured"
    ):
        raise ValueError("Successful implement observations require a measured patch")
    if observation["diff_status"] == "measured":
        if type(observation["patch_sha256"]) is not str or SHA256.fullmatch(
            observation["patch_sha256"]
        ) is None:
            raise ValueError("Measured diff requires patch_sha256")
    elif observation["patch_sha256"] is not None:
        raise ValueError("Non-applicable diff requires a null patch_sha256")
    observation["_duration_ms"] = duration_ms
    return observation


def inspect_patch(
    patch: Path | None,
    observation: dict[str, Any],
    repo_root: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if observation["diff_status"] == "not_applicable":
        if patch is not None:
            raise ValueError("--patch is not allowed when diff_status is not_applicable")
        return {
            "status": "not_applicable",
            "sha256": None,
            "size_bytes": 0,
            "file_count": 0,
            "changed_lines": 0,
            "additions": 0,
            "deletions": 0,
            "paths": [],
            "binary_paths": [],
            "symlink_paths": [],
        }
    if patch is None:
        raise ValueError("--patch is required when diff_status is measured")
    if patch.is_symlink() or not patch.is_file():
        raise ValueError("Patch must be an existing regular file")
    resolved = patch.resolve()
    if policy["require_external_patch"] and build_stage_context.is_within(resolved, repo_root):
        raise ValueError("Patch must be outside the Git checkout")
    content = resolved.read_bytes()
    if len(content) > policy["max_patch_bytes"]:
        raise ValueError("Patch exceeds max_patch_bytes")
    digest = sha256_bytes(content)
    if digest != observation["patch_sha256"]:
        raise ValueError("Patch SHA-256 does not match the observation")
    text = content.decode("utf-8-sig")
    facts = diff_policy.parse_patch(text)
    if facts.malformed or (text.strip() and facts.file_count == 0):
        raise ValueError("Patch is malformed and cannot produce reliable metrics")
    return {
        "status": "measured",
        "sha256": digest,
        "size_bytes": len(content),
        "file_count": facts.file_count,
        "changed_lines": facts.changed_lines,
        "additions": len(facts.added_lines),
        "deletions": len(facts.removed_lines),
        "paths": list(facts.paths),
        "binary_paths": list(facts.binary_paths),
        "symlink_paths": list(facts.symlink_paths),
    }


def validate_paths(
    repo_root: Path,
    observation: Path,
    record: Path,
    policy: dict[str, Any],
    require_existing_record: bool,
) -> tuple[Path, Path]:
    if observation.is_symlink() or not observation.is_file():
        raise ValueError("Observation must be an existing regular file")
    observation = observation.resolve()
    record = record.resolve()
    if record.is_symlink():
        raise ValueError("Metrics record symbolic links are not allowed")
    if policy["require_external_observation"] and build_stage_context.is_within(
        observation,
        repo_root,
    ):
        raise ValueError("Observation must be outside the Git checkout")
    if policy["require_external_record"] and build_stage_context.is_within(record, repo_root):
        raise ValueError("Metrics record must be outside the Git checkout")
    if require_existing_record:
        if not record.is_file():
            raise ValueError("Metrics record must be an existing regular file")
    elif policy["require_absent_record"] and record.exists():
        raise ValueError("Metrics record already exists")
    if not record.parent.is_dir():
        raise ValueError("Metrics record parent must exist")
    return observation, record


def build_record(
    repo: Path,
    observation_path: Path,
    record_path: Path,
    patch: Path | None,
    policy: dict[str, Any],
    require_existing_record: bool = False,
) -> tuple[dict[str, Any], bytes]:
    repo_root = Path(
        diff_policy.run_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    observation_path, _record_path = validate_paths(
        repo_root,
        observation_path,
        record_path,
        policy,
        require_existing_record,
    )
    observation_bytes = observation_path.read_bytes()
    if len(observation_bytes) > policy["max_observation_bytes"]:
        raise ValueError("Observation exceeds max_observation_bytes")
    observation = validate_observation(
        json.loads(observation_bytes.decode("utf-8-sig")),
        policy,
    )
    duration_ms = observation.pop("_duration_ms")
    patch_metrics = inspect_patch(patch, observation, repo_root, policy)
    record = {
        "metrics_version": policy["version"],
        "purpose": policy["purpose"],
        "mode": policy["mode"],
        **{field: False for field in FALSE_FIELDS},
        "run_id": observation["run_id"],
        "issue": observation["issue"],
        "stage": observation["stage"],
        "base_commit": observation["base_commit"],
        "adapter": observation["adapter"],
        "model": observation["model"],
        "timing": {
            **observation["timing"],
            "duration_ms": duration_ms,
        },
        "tokens": observation["tokens"],
        "cost": observation["cost"],
        "outcome": observation["outcome"],
        "human_corrections": observation["human_corrections"],
        "final_disposition": observation["final_disposition"],
        "regression_status": observation["regression_status"],
        "diff": patch_metrics,
        "source_evidence": {
            "observation_sha256": sha256_bytes(observation_bytes),
            "observation_size_bytes": len(observation_bytes),
            "patch_sha256": patch_metrics["sha256"],
            "patch_size_bytes": patch_metrics["size_bytes"],
        },
        "policy_bindings": binding_records(repo_root, policy["bindings"]),
    }
    content = canonical_bytes(record)
    if len(content) > policy["max_record_bytes"]:
        raise ValueError("Metrics record exceeds max_record_bytes")
    return record, content


def write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "record", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--repo", type=Path, required=True)
        subparser.add_argument("--observation", type=Path, required=True)
        subparser.add_argument("--record", type=Path, required=True)
        subparser.add_argument("--patch", type=Path)
        if command == "validate":
            subparser.add_argument("--record-sha256", required=True)
        subparser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def format_text(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"run-metrics: {result['status'].upper()}",
            f"run_id={result['record']['run_id']}",
            f"stage={result['record']['stage']}",
            f"duration_ms={result['record']['timing']['duration_ms']}",
            f"record_sha256={result['record_sha256']}",
            "authorized=false",
        ]
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        policy = load_policy()
        record, content = build_record(
            args.repo,
            args.observation,
            args.record,
            args.patch,
            policy,
            require_existing_record=args.command == "validate",
        )
        result = {
            "status": "checked",
            "recorded": False,
            "record_path": str(args.record.resolve()),
            "record_sha256": sha256_bytes(content),
            "record_size_bytes": len(content),
            "record": record,
        }
        if args.command == "record":
            write_exclusive(args.record.resolve(), content)
            result["status"] = "recorded"
            result["recorded"] = True
        elif args.command == "validate":
            if SHA256.fullmatch(args.record_sha256) is None:
                raise ValueError("record-sha256 must be 64 lowercase hexadecimal characters")
            actual = args.record.resolve().read_bytes()
            if len(actual) > policy["max_record_bytes"]:
                raise ValueError("Metrics record exceeds max_record_bytes")
            if sha256_bytes(actual) != args.record_sha256:
                raise ValueError("Metrics record SHA-256 does not match")
            if actual != content:
                raise ValueError("Metrics record does not match the current exact evidence")
            result["status"] = "validated"
            result["valid"] = True
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"run-metrics: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
