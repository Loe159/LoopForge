#!/usr/bin/env python3
"""Classify patch supervision risk using deterministic local rules."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

import diff_policy


RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
ROUTES = {"low": "A", "medium": "B", "high": "C"}
HUMAN_GATES = {
    "low": {
        "required": ["implementation_review"],
        "recommended": [],
    },
    "medium": {
        "required": ["plan_review", "implementation_review"],
        "recommended": ["research_review"],
    },
    "high": {
        "required": [
            "research_review",
            "plan_review",
            "intermediate_implementation_review",
            "implementation_review",
        ],
        "recommended": [],
    },
}


def load_risk_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "version",
        "medium_file_count",
        "medium_changed_lines",
        "high_path_patterns",
        "medium_path_patterns",
    }
    missing = required.difference(policy)
    if missing:
        raise ValueError(f"Risk policy is missing required fields: {', '.join(sorted(missing))}")
    if (
        not isinstance(policy["version"], int)
        or isinstance(policy["version"], bool)
        or policy["version"] != 1
    ):
        raise ValueError(f"Unsupported risk policy version: {policy['version']}")
    for field in ("medium_file_count", "medium_changed_lines"):
        if not isinstance(policy[field], int) or isinstance(policy[field], bool) or policy[field] < 1:
            raise ValueError(f"{field} must be a positive integer")
    for field in ("high_path_patterns", "medium_path_patterns"):
        patterns = policy[field]
        if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
            raise ValueError(f"{field} must be a list of strings")
    return policy


def matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if any(
            fnmatch.fnmatchcase(path.casefold(), pattern.casefold())
            for pattern in patterns
        )
    )


def classify(
    policy_result: dict[str, Any],
    risk_policy: dict[str, Any],
) -> dict[str, Any]:
    facts = policy_result["facts"]
    reasons: list[dict[str, Any]] = []
    risk = "low"

    def elevate(level: str, rule: str, message: str, **details: Any) -> None:
        nonlocal risk
        if RISK_ORDER[level] > RISK_ORDER[risk]:
            risk = level
        reason: dict[str, Any] = {"level": level, "rule": rule, "message": message}
        reason.update(details)
        reasons.append(reason)

    if policy_result["violations"]:
        elevate(
            "high",
            "policy_blocked",
            "Any deterministic policy violation requires high-risk supervision.",
            violations=sorted({violation["rule"] for violation in policy_result["violations"]}),
        )

    high_paths = matching_paths(facts["paths"], risk_policy["high_path_patterns"])
    if high_paths:
        elevate(
            "high",
            "high_risk_paths",
            "Patch changes parser, semantic-boundary, or debugger internals.",
            paths=high_paths,
        )

    medium_paths = matching_paths(facts["paths"], risk_policy["medium_path_patterns"])
    if medium_paths:
        elevate(
            "medium",
            "application_code",
            "Patch changes application code and requires the standard research/plan route.",
            paths=medium_paths,
        )

    if facts["file_count"] >= risk_policy["medium_file_count"]:
        elevate(
            "medium",
            "medium_file_count",
            "Patch reaches the configured standard-change file threshold.",
            actual=facts["file_count"],
            threshold=risk_policy["medium_file_count"],
        )

    if facts["changed_lines"] >= risk_policy["medium_changed_lines"]:
        elevate(
            "medium",
            "medium_changed_lines",
            "Patch reaches the configured standard-change line threshold.",
            actual=facts["changed_lines"],
            threshold=risk_policy["medium_changed_lines"],
        )

    return {
        "risk": risk,
        "label": f"risk:{risk}",
        "route": ROUTES[risk],
        "human_gates": HUMAN_GATES[risk],
        "policy_allowed": policy_result["allowed"],
        "reasons": reasons,
        "facts": {
            "file_count": facts["file_count"],
            "changed_lines": facts["changed_lines"],
            "paths": facts["paths"],
        },
    }


def format_text(result: dict[str, Any]) -> str:
    lines = [
        f"patch-risk: {result['risk'].upper()} route={result['route']}",
        f"policy_allowed={str(result['policy_allowed']).lower()}",
        f"required_gates={','.join(result['human_gates']['required'])}",
        f"recommended_gates={','.join(result['human_gates']['recommended'])}",
    ]
    for reason in result["reasons"]:
        lines.append(f"- {reason['level']} {reason['rule']}: {reason['message']}")
        for path in reason.get("paths", []):
            lines.append(f"  {path}")
        if "violations" in reason:
            lines.append(f"  violations={','.join(reason['violations'])}")
        if "actual" in reason:
            lines.append(f"  actual={reason['actual']} threshold={reason['threshold']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True, help="Git unified diff to classify")
    parser.add_argument(
        "--diff-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "diff-policy.json",
        help="Diff policy JSON file",
    )
    parser.add_argument(
        "--risk-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "risk-rules.json",
        help="Risk rules JSON file",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--repo", type=Path, help="Git checkout for reinforced validation")
    parser.add_argument("--base", help="Base commit for reinforced validation")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if (args.repo is None) != (args.base is None):
            raise ValueError("--repo and --base must be provided together")
        patch = args.patch.read_text(encoding="utf-8")
        policy = diff_policy.load_policy(args.diff_policy)
        expected_paths = None
        if args.repo is not None and args.base is not None:
            repo_root, base_commit, expected_paths = diff_policy.collect_worktree_paths(
                args.repo,
                args.base,
            )
        policy_result = diff_policy.evaluate_patch(patch, policy, expected_paths)
        contains_secret = any(
            violation["rule"] == "high_confidence_secret"
            for violation in policy_result["violations"]
        )
        if (
            args.repo is not None
            and args.base is not None
            and patch.strip()
            and not diff_policy.parse_patch(patch).malformed
            and not contains_secret
        ):
            policy_result["violations"].extend(
                diff_policy.verify_patch_content(repo_root, base_commit, args.patch)
            )
            policy_result["allowed"] = not policy_result["violations"]
        result = classify(policy_result, load_risk_policy(args.risk_policy))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"patch-risk: ERROR\n- {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
