#!/usr/bin/env python3
"""Check declared artifact prerequisites for a manual workflow stage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import validate_artifacts


RISKS = {"low", "medium", "high"}


def load_readiness_policy(
    path: Path,
    artifact_contract: dict[str, Any],
) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "blocked_status", "stages"}
    missing = required.difference(policy)
    if missing:
        raise ValueError(f"Readiness policy is missing fields: {', '.join(sorted(missing))}")
    if (
        not isinstance(policy["version"], int)
        or isinstance(policy["version"], bool)
        or policy["version"] != 1
    ):
        raise ValueError(f"Unsupported readiness policy version: {policy['version']}")
    blocked_status = policy["blocked_status"]
    if not isinstance(blocked_status, str) or not blocked_status:
        raise ValueError("blocked_status must be a non-empty string")
    stages = policy["stages"]
    if not isinstance(stages, dict) or not stages:
        raise ValueError("stages must be a non-empty object")
    for stage, risk_rules in stages.items():
        if not isinstance(stage, str) or not stage or not isinstance(risk_rules, dict):
            raise ValueError("Each stage must be a non-empty string mapped to an object")
        if set(risk_rules) != RISKS:
            raise ValueError(f"{stage} must define exactly low, medium, and high risk rules")
        for risk, requirements in risk_rules.items():
            if not isinstance(requirements, dict) or not requirements:
                raise ValueError(f"{stage}/{risk} requirements must be a non-empty object")
            for artifact_name, statuses in requirements.items():
                if artifact_name not in artifact_contract["artifacts"]:
                    raise ValueError(f"{stage}/{risk} references unknown artifact: {artifact_name}")
                allowed = artifact_contract["artifacts"][artifact_name]["allowed_statuses"]
                if (
                    not isinstance(statuses, list)
                    or not statuses
                    or not all(isinstance(status, str) and status for status in statuses)
                    or len(statuses) != len(set(statuses))
                    or any(status not in allowed for status in statuses)
                ):
                    raise ValueError(
                        f"{stage}/{risk}/{artifact_name} must contain unique allowed statuses"
                    )
    return policy


def check_readiness(
    directory: Path,
    stage: str,
    artifact_contract: dict[str, Any],
    readiness_policy: dict[str, Any],
) -> dict[str, Any]:
    if stage not in readiness_policy["stages"]:
        raise ValueError(f"Unknown stage: {stage}")
    contract_result = validate_artifacts.validate_directory(directory, artifact_contract, False)
    result: dict[str, Any] = {
        "ready": False,
        "authorized": False,
        "stage": stage,
        "risk": None,
        "directory": str(directory.resolve()),
        "requirements": {},
        "failures": [],
        "artifact_contract_valid": contract_result["valid"],
    }
    if not contract_result["valid"]:
        result["failures"].append(
            {
                "rule": "artifact_contract",
                "message": "Artifact directory must satisfy the portable artifact contract.",
                "errors": contract_result["errors"],
            }
        )
        return result

    artifacts = {
        name: validate_artifacts.parse_artifact(directory / name)
        for name in artifact_contract["artifacts"]
    }
    risk = artifacts["task.md"].frontmatter["risk"]
    requirements = readiness_policy["stages"][stage][risk]
    result["risk"] = risk
    result["requirements"] = requirements

    blocked = sorted(
        name
        for name, artifact in artifacts.items()
        if artifact.frontmatter["status"] == readiness_policy["blocked_status"]
    )
    if blocked:
        result["failures"].append(
            {
                "rule": "blocked_artifacts",
                "message": "A blocked artifact stops every later stage.",
                "artifacts": blocked,
            }
        )

    for name, expected_statuses in requirements.items():
        actual = artifacts[name].frontmatter["status"]
        if actual not in expected_statuses:
            result["failures"].append(
                {
                    "rule": "required_status",
                    "artifact": name,
                    "actual": actual,
                    "expected": expected_statuses,
                    "message": "Artifact status does not satisfy the stage prerequisite.",
                }
            )
    result["ready"] = not result["failures"]
    return result


def format_text(result: dict[str, Any]) -> str:
    status = "READY" if result["ready"] else "NOT_READY"
    lines = [
        f"stage-readiness: {status} stage={result['stage']} risk={result['risk'] or 'unknown'}",
        "authorized=false",
    ]
    for failure in result["failures"]:
        lines.append(f"- {failure['rule']}: {failure['message']}")
        if "artifact" in failure:
            lines.append(
                f"  {failure['artifact']} actual={failure['actual']} "
                f"expected={','.join(failure['expected'])}"
            )
        for artifact in failure.get("artifacts", []):
            lines.append(f"  {artifact}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Filled run-artifact directory")
    parser.add_argument("--stage", required=True, help="Stage to check")
    parser.add_argument(
        "--artifact-contract",
        type=Path,
        default=repo_root / ".agent" / "policies" / "artifact-contract.json",
        help="Artifact contract JSON file",
    )
    parser.add_argument(
        "--readiness-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "stage-readiness.json",
        help="Stage readiness policy JSON file",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        artifact_contract = validate_artifacts.load_contract(args.artifact_contract)
        readiness_policy = load_readiness_policy(args.readiness_policy, artifact_contract)
        result = check_readiness(args.run, args.stage, artifact_contract, readiness_policy)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"stage-readiness: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
