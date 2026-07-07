#!/usr/bin/env python3
"""Validate portable agent-work Markdown artifacts without external dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLACEHOLDER = re.compile(r"\{\{[a-z0-9_]+\}\}")
COMMIT = re.compile(r"[0-9a-f]{40}")
ISSUE = re.compile(r"[1-9][0-9]*")
HEADING = re.compile(r"^# ([^\r\n]+)$", re.MULTILINE)


@dataclass(frozen=True)
class Artifact:
    name: str
    frontmatter: dict[str, str]
    sections: dict[str, str]
    text: str


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "max_artifact_bytes", "common_frontmatter", "artifacts"}
    missing = required.difference(contract)
    if missing:
        raise ValueError(f"Artifact contract is missing fields: {', '.join(sorted(missing))}")
    if (
        not isinstance(contract["version"], int)
        or isinstance(contract["version"], bool)
        or contract["version"] != 1
    ):
        raise ValueError(f"Unsupported artifact contract version: {contract['version']}")
    if (
        not isinstance(contract["max_artifact_bytes"], int)
        or isinstance(contract["max_artifact_bytes"], bool)
        or contract["max_artifact_bytes"] < 1
    ):
        raise ValueError("max_artifact_bytes must be a positive integer")
    common = contract["common_frontmatter"]
    if (
        not isinstance(common, list)
        or not common
        or not all(isinstance(field, str) and field for field in common)
        or len(common) != len(set(common))
    ):
        raise ValueError("common_frontmatter must be a non-empty unique list of strings")
    artifacts = contract["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("artifacts must be a non-empty object")
    identities: set[str] = set()
    for name, specification in artifacts.items():
        if not isinstance(name, str) or not name.endswith(".md") or not isinstance(specification, dict):
            raise ValueError("Each artifact must be a Markdown filename mapped to an object")
        required_spec = {
            "artifact",
            "allowed_statuses",
            "required_frontmatter",
            "required_sections",
        }
        missing_spec = required_spec.difference(specification)
        if missing_spec:
            raise ValueError(
                f"{name} contract is missing fields: {', '.join(sorted(missing_spec))}"
            )
        identity = specification["artifact"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError(f"{name} artifact must be a unique non-empty string")
        identities.add(identity)
        for field in ("allowed_statuses", "required_frontmatter", "required_sections"):
            values = specification[field]
            empty_allowed = field == "required_frontmatter"
            if (
                not isinstance(values, list)
                or (not values and not empty_allowed)
                or not all(isinstance(value, str) and value for value in values)
                or len(values) != len(set(values))
            ):
                qualifier = "unique list of strings"
                if empty_allowed:
                    qualifier = "unique list of strings, or an empty list"
                raise ValueError(f"{name} {field} must be a {qualifier}")
    return contract


def parse_artifact_text(source_name: str, text: str) -> Artifact:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{source_name}: missing opening frontmatter delimiter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{source_name}: missing closing frontmatter delimiter") from error
    frontmatter: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if separator != ":" or not key or not value or key in frontmatter:
            raise ValueError(f"{source_name}: invalid scalar frontmatter line")
        frontmatter[key] = value
    body = "\n".join(lines[closing + 1 :])
    matches = list(HEADING.finditer(body))
    if matches and body[: matches[0].start()].strip():
        raise ValueError(f"{source_name}: unexpected content before first section")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        section_name = match.group(1).strip()
        if section_name in sections:
            raise ValueError(f"{source_name}: duplicate section {section_name}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[section_name] = body[match.end() : end].strip()
    return Artifact(source_name, frontmatter, sections, text)


def parse_artifact(path: Path) -> Artifact:
    return parse_artifact_text(path.name, path.read_text(encoding="utf-8-sig"))


def validate_directory(
    directory: Path,
    contract: dict[str, Any],
    allow_placeholders: bool,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    artifacts: dict[str, Artifact] = {}

    def add_error(artifact: str, rule: str, message: str) -> None:
        errors.append({"artifact": artifact, "rule": rule, "message": message})

    unexpected = sorted(
        path.name
        for path in directory.glob("*.md")
        if path.name not in contract["artifacts"]
    )
    for name in unexpected:
        add_error(name, "unexpected_artifact", "Markdown artifact is outside the contract.")

    for name, specification in contract["artifacts"].items():
        path = directory / name
        if not path.is_file():
            add_error(name, "required_artifact", "Required artifact is missing.")
            continue
        if path.stat().st_size > contract["max_artifact_bytes"]:
            add_error(
                name,
                "max_artifact_bytes",
                f"Artifact exceeds {contract['max_artifact_bytes']} bytes.",
            )
        try:
            artifact = parse_artifact(path)
        except (OSError, UnicodeError, ValueError) as error:
            add_error(name, "parse_artifact", str(error))
            continue
        artifacts[name] = artifact
        required_frontmatter = set(contract["common_frontmatter"]) | set(
            specification["required_frontmatter"]
        )
        missing_frontmatter = sorted(required_frontmatter - set(artifact.frontmatter))
        if missing_frontmatter:
            add_error(
                name,
                "required_frontmatter",
                f"Missing frontmatter: {', '.join(missing_frontmatter)}",
            )
        if artifact.frontmatter.get("artifact") != specification["artifact"]:
            add_error(name, "artifact_identity", "Frontmatter artifact value does not match.")
        if artifact.frontmatter.get("artifact_version") != str(contract["version"]):
            add_error(name, "artifact_version", "Frontmatter artifact_version does not match.")
        status = artifact.frontmatter.get("status")
        if status is not None and status not in specification["allowed_statuses"]:
            add_error(name, "allowed_status", f"Unsupported status: {status}")
        missing_sections = [
            section
            for section in specification["required_sections"]
            if section not in artifact.sections
        ]
        if missing_sections:
            add_error(name, "required_sections", f"Missing sections: {', '.join(missing_sections)}")
        for section in specification["required_sections"]:
            if section in artifact.sections and not artifact.sections[section]:
                add_error(name, "non_empty_sections", f"Section is empty: {section}")
        if not allow_placeholders and PLACEHOLDER.search(artifact.text):
            add_error(name, "no_placeholders", "Artifact contains unresolved placeholders.")

    if not allow_placeholders and artifacts:
        issues = {artifact.frontmatter.get("issue") for artifact in artifacts.values()}
        commits = {artifact.frontmatter.get("base_commit") for artifact in artifacts.values()}
        if len(issues) != 1 or None in issues or not ISSUE.fullmatch(next(iter(issues), "")):
            add_error("*", "consistent_issue", "Artifacts must share one positive numeric issue ID.")
        if len(commits) != 1 or None in commits or not COMMIT.fullmatch(next(iter(commits), "")):
            add_error("*", "consistent_base_commit", "Artifacts must share one full lowercase commit SHA.")
        task = artifacts.get("task.md")
        if task is not None and task.frontmatter.get("risk") not in {"low", "medium", "high"}:
            add_error("task.md", "valid_risk", "Task risk must be low, medium, or high.")

    return {
        "valid": not errors,
        "mode": "templates" if allow_placeholders else "run",
        "directory": str(directory.resolve()),
        "artifacts": sorted(artifacts),
        "errors": errors,
    }


def format_text(result: dict[str, Any]) -> str:
    status = "VALID" if result["valid"] else "INVALID"
    lines = [f"artifact-contract: {status} mode={result['mode']}"]
    for error in result["errors"]:
        lines.append(f"- {error['artifact']} {error['rule']}: {error['message']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--templates", type=Path, help="Template directory to validate")
    mode.add_argument("--run", type=Path, help="Filled run-artifact directory to validate")
    parser.add_argument(
        "--contract",
        type=Path,
        default=repo_root / ".agent" / "policies" / "artifact-contract.json",
        help="Artifact contract JSON file",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        contract = load_contract(args.contract)
        directory = args.templates if args.templates is not None else args.run
        result = validate_directory(directory, contract, args.templates is not None)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"artifact-contract: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
