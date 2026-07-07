#!/usr/bin/env python3
"""Initialize one external portable run from an already normalized local task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import build_stage_context
import check_stage_readiness
import diff_policy
import validate_artifacts
import validate_disposable_worktree


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = REPO_ROOT / ".agent" / "policies"
TEMPLATES_DIR = REPO_ROOT / ".agent" / "templates"
POLICY_PATH = POLICY_DIR / "portable-run-initialization.json"
TASK_FIELDS = (
    "goal",
    "expected_behavior",
    "acceptance_criteria",
    "constraints",
    "out_of_scope",
)
FALSE_FIELDS = (
    "authorized",
    "agent_invocation_authorized",
    "implementation_authorized",
    "network_authorized",
    "publication_authorized",
    "repository_mutation_authorized",
    "stage_start_authorized",
    "task_approval_authenticated",
)
PENDING_TEXT = "Not recorded; this workflow stage has not run."

EXPECTED_POLICY: dict[str, Any] = {
    "version": 1,
    "purpose": "portable_run_initialization",
    "mode": "initialization-only",
    "max_input_bytes": 30000,
    "max_receipt_bytes": 30000,
    "max_source_reference_characters": 500,
    "max_task_section_characters": 5000,
    "require_external_input": True,
    "require_external_run": True,
    "require_external_receipt": True,
    "require_receipt_outside_run": True,
    "require_absent_run": True,
    "require_absent_receipt": True,
    "require_clean_worktree": True,
    "require_repo_head_match": True,
    "rollback_on_failure": True,
    "source_kind": "human_normalized_input",
    "initial_statuses": {
        "task.md": "awaiting_approval",
        "research.md": "pending",
        "plan.md": "awaiting_approval",
        "progress.md": "not_started",
        "verification.md": "pending",
        "review.md": "pending",
    },
    "bindings": [
        ".agent/checks/initialize_portable_run.py",
        ".agent/checks/build_stage_context.py",
        ".agent/checks/check_stage_readiness.py",
        ".agent/checks/diff_policy.py",
        ".agent/checks/validate_artifacts.py",
        ".agent/checks/validate_disposable_worktree.py",
        ".agent/policies/portable-run-initialization.json",
        ".agent/policies/artifact-contract.json",
        ".agent/policies/diff-policy.json",
        ".agent/policies/stage-readiness.json",
        ".agent/templates/task.md",
        ".agent/templates/research.md",
        ".agent/templates/plan.md",
        ".agent/templates/progress.md",
        ".agent/templates/verification.md",
        ".agent/templates/review.md",
    ],
}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy != EXPECTED_POLICY:
        raise ValueError("Portable-run initialization policy does not match the pilot contract")
    return policy


def load_policies() -> dict[str, Any]:
    artifact = validate_artifacts.load_contract(POLICY_DIR / "artifact-contract.json")
    return {
        "initialization": load_policy(),
        "artifact": artifact,
        "readiness": check_stage_readiness.load_readiness_policy(
            POLICY_DIR / "stage-readiness.json",
            artifact,
        ),
        "diff": diff_policy.load_policy(POLICY_DIR / "diff-policy.json"),
    }


def failure(rule: str, message: str, **details: Any) -> dict[str, Any]:
    return {"rule": rule, "message": message, **details}


def base_result(run: Path, receipt: Path) -> dict[str, Any]:
    return {
        "initialized": False,
        **{field: False for field in FALSE_FIELDS},
        "task_approved": False,
        "research_ready": False,
        "run": str(run),
        "receipt": str(receipt),
        "rollback_attempted": False,
        "rollback_succeeded": False,
        "failures": [],
    }


def validate_input(value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "input_version",
        "purpose",
        "mode",
        "issue",
        "risk",
        "base_commit",
        "source",
        "task",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Normalized task input fields do not match the contract")
    if (
        type(value["input_version"]) is not int
        or value["input_version"] != policy["version"]
        or value["purpose"] != "portable_run_normalized_task_input"
        or value["mode"] != "normalized-task-only"
        or type(value["issue"]) is not int
        or value["issue"] < 1
        or value["risk"] not in {"low", "medium", "high"}
        or type(value["base_commit"]) is not str
        or validate_artifacts.COMMIT.fullmatch(value["base_commit"]) is None
    ):
        raise ValueError("Normalized task input metadata does not match the contract")
    source = value["source"]
    if (
        not isinstance(source, dict)
        or set(source) != {"kind", "reference"}
        or source["kind"] != policy["source_kind"]
        or type(source["reference"]) is not str
        or not source["reference"].strip()
        or len(source["reference"]) > policy["max_source_reference_characters"]
    ):
        raise ValueError("Normalized task source does not match the contract")
    task = value["task"]
    if not isinstance(task, dict) or set(task) != set(TASK_FIELDS):
        raise ValueError("Normalized task sections do not match the contract")
    if any(
        type(task[field]) is not str
        or not task[field].strip()
        or len(task[field]) > policy["max_task_section_characters"]
        for field in TASK_FIELDS
    ):
        raise ValueError("Normalized task sections must be bounded non-empty strings")
    return value


def binding_records(names: list[str]) -> list[dict[str, Any]]:
    return validate_disposable_worktree.binding_records(names)


def render_template(name: str, replacements: dict[str, str]) -> bytes:
    text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    return validate_artifacts.PLACEHOLDER.sub(
        lambda match: replacements.get(match.group(0)[2:-2], PENDING_TEXT),
        text,
    ).encode("utf-8")


def manifest(run: Path, names: list[str]) -> list[dict[str, Any]]:
    records = []
    for name in names:
        content = (run / name).read_bytes()
        artifact = validate_artifacts.parse_artifact(run / name)
        records.append(
            {
                "name": name,
                "status": artifact.frontmatter["status"],
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    return records


def write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def initialize(
    repo: Path,
    input_path: Path,
    run: Path,
    receipt: Path,
    policies: dict[str, Any],
    receipt_writer: Callable[[Path, bytes], None] = write_exclusive,
) -> dict[str, Any]:
    policy = policies["initialization"]
    run = run.resolve()
    receipt = receipt.resolve()
    result = base_result(run, receipt)
    if repo.is_symlink() or input_path.is_symlink() or run.is_symlink() or receipt.is_symlink():
        raise ValueError("Repository, input, run, and receipt symbolic links are not allowed")
    repo_root = Path(
        diff_policy.run_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise ValueError("Normalized task input must be an existing regular file")
    if policy["require_external_input"] and build_stage_context.is_within(input_path, repo_root):
        raise ValueError("Normalized task input must be outside the Git checkout")
    if policy["require_external_run"] and build_stage_context.is_within(run, repo_root):
        raise ValueError("Portable run must be outside the Git checkout")
    if policy["require_external_receipt"] and build_stage_context.is_within(receipt, repo_root):
        raise ValueError("Initialization receipt must be outside the Git checkout")
    if policy["require_receipt_outside_run"] and build_stage_context.is_within(receipt, run):
        raise ValueError("Initialization receipt must be outside the portable run")
    if policy["require_absent_run"] and run.exists():
        raise ValueError("Portable run already exists")
    if policy["require_absent_receipt"] and receipt.exists():
        raise ValueError("Initialization receipt already exists")
    if not run.parent.is_dir() or not receipt.parent.is_dir():
        raise ValueError("Run and receipt parents must be existing directories")
    if input_path.stat().st_size > policy["max_input_bytes"]:
        result["failures"].append(failure("max_input_bytes", "Normalized task input is too large."))
        return result

    input_bytes = input_path.read_bytes()
    input_value = validate_input(json.loads(input_bytes.decode("utf-8-sig")), policy)
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    result.update(
        issue=input_value["issue"],
        risk=input_value["risk"],
        base_commit=input_value["base_commit"],
        input_sha256=input_sha256,
    )
    detections = build_stage_context.detect_secrets(
        [
            build_stage_context.content_record(
                "normalized-task-input.json",
                input_bytes.decode("utf-8-sig"),
            )
        ],
        policies["diff"],
    )
    if detections:
        result["failures"].append(
            failure(
                "high_confidence_secret",
                "Normalized task input contains a high-confidence secret signature.",
                detections=detections,
            )
        )
        return result
    head = diff_policy.run_git(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
    status = diff_policy.run_git_with_environment(
        repo_root,
        {"GIT_OPTIONAL_LOCKS": "0"},
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if policy["require_repo_head_match"] and head != input_value["base_commit"]:
        result["failures"].append(
            failure("repo_head_match", "Repository HEAD differs from normalized task base.")
        )
    if policy["require_clean_worktree"] and status:
        result["failures"].append(
            failure("clean_worktree", "Repository worktree must be clean before initialization.")
        )
    if result["failures"]:
        return result

    artifact_names = list(policies["artifact"]["artifacts"])
    replacements = {
        "issue": str(input_value["issue"]),
        "base_commit": input_value["base_commit"],
        "risk": input_value["risk"],
        **input_value["task"],
    }
    temp_run: Path | None = None
    created_run = False
    try:
        temp_run = Path(tempfile.mkdtemp(prefix=".portable-run-", dir=run.parent))
        for name in artifact_names:
            content = render_template(name, replacements)
            write_exclusive(temp_run / name, content)
        contract = validate_artifacts.validate_directory(temp_run, policies["artifact"], False)
        if not contract["valid"]:
            raise ValueError("Initialized run does not satisfy the artifact contract")
        initial_manifest = manifest(temp_run, artifact_names)
        if {
            record["name"]: record["status"] for record in initial_manifest
        } != policy["initial_statuses"]:
            raise ValueError("Initialized run statuses do not match the pilot contract")
        research_readiness = check_stage_readiness.check_readiness(
            temp_run,
            "research",
            policies["artifact"],
            policies["readiness"],
        )
        if research_readiness["ready"]:
            raise ValueError("Initialized run unexpectedly reports research ready")
        current_head = diff_policy.run_git(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
        current_status = diff_policy.run_git_with_environment(
            repo_root,
            {"GIT_OPTIONAL_LOCKS": "0"},
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if (
            input_path.read_bytes() != input_bytes
            or current_head != head
            or current_status != status
        ):
            raise ValueError("Input or repository changed during initialization")
        run.mkdir()
        created_run = True
        for name in artifact_names:
            (temp_run / name).replace(run / name)
        temp_run.rmdir()
        temp_run = None
        bindings = binding_records(policy["bindings"])
        receipt_value = {
            "initialization_receipt_version": policy["version"],
            "purpose": policy["purpose"],
            "mode": policy["mode"],
            **{field: False for field in FALSE_FIELDS},
            "run_initialized": True,
            "task_approved": False,
            "research_ready": False,
            "source": input_value["source"],
            "issue": input_value["issue"],
            "risk": input_value["risk"],
            "base_commit": input_value["base_commit"],
            "input_sha256": input_sha256,
            "run": str(run),
            "manifest": manifest(run, artifact_names),
            "bindings": bindings,
        }
        receipt_bytes = (json.dumps(receipt_value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(receipt_bytes) > policy["max_receipt_bytes"]:
            raise ValueError("Initialization receipt exceeds max_receipt_bytes")
        receipt_writer(receipt, receipt_bytes)
        final_head = diff_policy.run_git(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
        final_status = diff_policy.run_git_with_environment(
            repo_root,
            {"GIT_OPTIONAL_LOCKS": "0"},
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if (
            input_path.read_bytes() != input_bytes
            or manifest(run, artifact_names) != receipt_value["manifest"]
            or receipt.read_bytes() != receipt_bytes
            or final_head != head
            or final_status != status
        ):
            raise ValueError("Input, run, receipt, or repository changed during final validation")
        result.update(
            initialized=True,
            receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
            receipt_size_bytes=len(receipt_bytes),
            manifest=receipt_value["manifest"],
            bindings=bindings,
        )
        return result
    except (OSError, UnicodeError, ValueError) as error:
        receipt.unlink(missing_ok=True)
        result["rollback_attempted"] = temp_run is not None or created_run
        if temp_run is not None:
            shutil.rmtree(temp_run, ignore_errors=True)
        if created_run and policy["rollback_on_failure"]:
            shutil.rmtree(run, ignore_errors=True)
        result["rollback_succeeded"] = not run.exists() and (
            temp_run is None or not temp_run.exists()
        )
        status_text = "succeeded" if result["rollback_succeeded"] else "failed"
        raise ValueError(f"Portable-run initialization failed; rollback {status_text}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def format_text(result: dict[str, Any]) -> str:
    status = "INITIALIZED" if result["initialized"] else "NOT_INITIALIZED"
    lines = [
        f"portable-run-initialization: {status}",
        "task_approved=false",
        "research_ready=false",
        "authorized=false",
    ]
    lines.extend(f"- {item['rule']}: {item['message']}" for item in result["failures"])
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = initialize(args.repo, args.input, args.run, args.receipt, load_policies())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"portable-run-initialization: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["initialized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
