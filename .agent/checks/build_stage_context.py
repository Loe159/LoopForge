#!/usr/bin/env python3
"""Build a bounded deterministic JSON context for one ready read-only stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import check_stage_readiness
import diff_policy
import validate_artifacts
import validate_prompts


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def load_context_policy(
    path: Path,
    prompt_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "version",
        "max_bundle_bytes",
        "require_repo_head_match",
        "require_clean_worktree",
        "require_run_outside_repo",
        "stages",
    }
    missing = required.difference(policy)
    if missing:
        raise ValueError(f"Stage-context policy is missing fields: {', '.join(sorted(missing))}")
    if (
        not isinstance(policy["version"], int)
        or isinstance(policy["version"], bool)
        or policy["version"] != 3
    ):
        raise ValueError(f"Unsupported stage-context policy version: {policy['version']}")
    if (
        not isinstance(policy["max_bundle_bytes"], int)
        or isinstance(policy["max_bundle_bytes"], bool)
        or policy["max_bundle_bytes"] < 1
    ):
        raise ValueError("max_bundle_bytes must be a positive integer")
    for field in ("require_repo_head_match", "require_clean_worktree", "require_run_outside_repo"):
        if not isinstance(policy[field], bool) or not policy[field]:
            raise ValueError(f"{field} must explicitly be true during the pilot")
    prompt_stages = {
        specification["stage"]: name
        for name, specification in prompt_contract["prompts"].items()
    }
    stages = policy["stages"]
    if not isinstance(stages, dict) or set(stages) != set(prompt_stages):
        raise ValueError("stages must exactly match the portable prompt stages")
    for stage, specification in stages.items():
        if not isinstance(specification, dict) or set(specification) != {
            "prompt",
            "artifacts",
            "provenance",
        }:
            raise ValueError(f"{stage} must define exactly prompt, artifacts, and provenance")
        if specification["prompt"] != prompt_stages[stage]:
            raise ValueError(f"{stage} prompt does not match the portable prompt contract")
        artifacts = specification["artifacts"]
        if (
            not isinstance(artifacts, list)
            or not artifacts
            or not all(
                isinstance(name, str) and name in artifact_contract["artifacts"]
                for name in artifacts
            )
            or len(artifacts) != len(set(artifacts))
        ):
            raise ValueError(f"{stage} artifacts must be a unique list of contracted artifacts")
        if "task.md" not in artifacts:
            raise ValueError(f"{stage} context must include task.md")
        expected_provenance = {
            "research": "validated_task_approval",
            "plan": "validated_stage_application",
            "compact-progress": "local_artifact_contract",
            "review": "local_artifact_contract",
        }.get(stage)
        if expected_provenance is None:
            raise ValueError(f"{stage} has no contracted provenance rule")
        if specification["provenance"] != expected_provenance:
            raise ValueError(f"{stage} provenance must be {expected_provenance}")
    return policy


def content_record(name: str, text: str) -> dict[str, Any]:
    content = text.encode("utf-8")
    return {
        "name": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "content": text,
    }


def detect_secrets(
    records: list[dict[str, Any]],
    diff_policy_config: dict[str, Any],
) -> list[dict[str, str]]:
    return sorted(
        [
            {"source": record["name"], "signature": secret["id"]}
            for record in records
            for secret in diff_policy_config["secret_patterns"]
            if re.search(secret["pattern"], record["content"])
        ],
        key=lambda item: (item["source"], item["signature"]),
    )


def write_atomic(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def check_research_provenance(
    repo: Path,
    run: Path,
    approval_receipt: Path,
    approval_receipt_sha256: str,
) -> dict[str, Any]:
    import check_research_readiness

    return check_research_readiness.check(
        repo,
        run,
        approval_receipt,
        approval_receipt_sha256,
        check_research_readiness.load_policies(),
    )


def check_stage_application_provenance(
    repo: Path,
    run: Path,
    application_receipt: Path,
    application_receipt_sha256: str,
) -> dict[str, Any]:
    import validate_stage_application

    return validate_stage_application.validate(
        repo,
        run,
        application_receipt,
        application_receipt_sha256,
        validate_stage_application.load_policies(),
    )


def build_context(
    repo: Path,
    run: Path,
    stage: str,
    output: Path,
    policies: dict[str, Any],
    prompts_dir: Path,
    approval_receipt: Path | None = None,
    approval_receipt_sha256: str | None = None,
    application_receipt: Path | None = None,
    application_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(
        diff_policy.run_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    run = run.resolve()
    output = output.resolve()
    if policies["context"]["require_run_outside_repo"] and is_within(run, repo_root):
        raise ValueError("Run artifact directory must be outside the Git checkout")
    if is_within(output, repo_root):
        raise ValueError("Context bundle output must be outside the Git checkout")
    if output.exists():
        raise ValueError("Context bundle output already exists")
    if stage not in policies["context"]["stages"]:
        raise ValueError(f"Unknown context stage: {stage}")
    provenance_kind = policies["context"]["stages"][stage]["provenance"]
    if provenance_kind == "validated_task_approval":
        if application_receipt is not None or application_receipt_sha256 is not None:
            raise ValueError("Stage-application provenance inputs are only valid for planning")
        if approval_receipt is None or approval_receipt_sha256 is None:
            return {
                "produced": False,
                "authorized": False,
                "stage": stage,
                "failures": [
                    {
                        "rule": "task_approval_provenance",
                        "message": "Research context requires task-approval receipt provenance.",
                    }
                ],
            }
        provenance_readiness = check_research_provenance(
            repo_root,
            run,
            approval_receipt,
            approval_receipt_sha256,
        )
        if not provenance_readiness["ready"]:
            return {
                "produced": False,
                "authorized": False,
                "stage": stage,
                "failures": provenance_readiness["failures"],
            }
        provenance = {
            "kind": provenance_kind,
            "task_approval_receipt_sha256": approval_receipt_sha256,
        }
    else:
        if approval_receipt is not None or approval_receipt_sha256 is not None:
            raise ValueError("Task-approval provenance inputs are only valid for research")
        if provenance_kind == "validated_stage_application":
            if application_receipt is None or application_receipt_sha256 is None:
                return {
                    "produced": False,
                    "authorized": False,
                    "stage": stage,
                    "failures": [
                        {
                            "rule": "stage_application_provenance",
                            "message": "Plan context requires validated research application provenance.",
                        }
                    ],
                }
            try:
                application_provenance = check_stage_application_provenance(
                    repo_root,
                    run,
                    application_receipt,
                    application_receipt_sha256,
                )
            except ValueError as error:
                application_provenance = {
                    "valid": False,
                    "stage": None,
                    "artifact": None,
                    "status": None,
                    "failures": [
                        {
                            "rule": "stage_application_provenance",
                            "message": str(error),
                        }
                    ],
                }
            if not (
                application_provenance["valid"]
                and application_provenance["stage"] == "research"
                and application_provenance["artifact"] == "research.md"
                and application_provenance["status"] == "complete"
            ):
                return {
                    "produced": False,
                    "authorized": False,
                    "stage": stage,
                    "failures": [
                        {
                            "rule": "stage_application_provenance",
                            "message": "Research application provenance is not valid for planning.",
                            "details": application_provenance["failures"],
                        }
                    ],
                }
            provenance = {
                "kind": provenance_kind,
                "stage_application_receipt_sha256": application_receipt_sha256,
            }
        elif provenance_kind == "local_artifact_contract":
            if application_receipt is not None or application_receipt_sha256 is not None:
                raise ValueError(
                    "Stage-application provenance inputs are only valid for planning"
                )
            provenance = {"kind": provenance_kind}
        elif application_receipt is not None or application_receipt_sha256 is not None:
            raise ValueError("Stage-application provenance inputs are only valid for planning")
        else:
            raise ValueError(f"Unsupported context provenance: {provenance_kind}")

    prompt_validation = validate_prompts.validate_prompts(
        prompts_dir,
        policies["prompt"],
        policies["artifact"],
    )
    if not prompt_validation["valid"]:
        raise ValueError("Repository portable prompts do not satisfy the prompt contract")
    readiness = check_stage_readiness.check_readiness(
        run,
        stage,
        policies["artifact"],
        policies["readiness"],
    )
    if not readiness["ready"]:
        return {
            "produced": False,
            "authorized": False,
            "stage": stage,
            "failures": readiness["failures"],
        }

    task = validate_artifacts.parse_artifact(run / "task.md")
    base_commit = task.frontmatter["base_commit"]
    head = diff_policy.run_git(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
    if policies["context"]["require_repo_head_match"] and head != base_commit:
        return {
            "produced": False,
            "authorized": False,
            "stage": stage,
            "failures": [
                {
                    "rule": "repo_head_match",
                    "message": "Repository HEAD does not match the artifact base commit.",
                }
            ],
        }
    status = diff_policy.run_git_with_environment(
        repo_root,
        {"GIT_OPTIONAL_LOCKS": "0"},
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if policies["context"]["require_clean_worktree"] and status:
        return {
            "produced": False,
            "authorized": False,
            "stage": stage,
            "failures": [
                {
                    "rule": "clean_worktree",
                    "message": "Repository worktree must be clean before building stage context.",
                }
            ],
        }

    stage_policy = policies["context"]["stages"][stage]
    prompt_path = prompts_dir / stage_policy["prompt"]
    prompt_record = content_record(prompt_path.name, prompt_path.read_text(encoding="utf-8-sig"))
    artifact_records = [
        content_record(name, (run / name).read_text(encoding="utf-8-sig"))
        for name in stage_policy["artifacts"]
    ]
    detections = detect_secrets([prompt_record, *artifact_records], policies["diff"])
    if detections:
        return {
            "produced": False,
            "authorized": False,
            "stage": stage,
            "failures": [
                {
                    "rule": "high_confidence_secret",
                    "message": "Context source contains a high-confidence secret signature.",
                    "detections": detections,
                }
            ],
        }

    bundle = {
        "bundle_version": policies["context"]["version"],
        "stage": stage,
        "mode": "read-only",
        "authorized": False,
        "issue": int(task.frontmatter["issue"]),
        "risk": task.frontmatter["risk"],
        "base_commit": base_commit,
        "provenance": provenance,
        "prompt": prompt_record,
        "artifacts": artifact_records,
    }
    bundle_bytes = (json.dumps(bundle, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(bundle_bytes) > policies["context"]["max_bundle_bytes"]:
        return {
            "produced": False,
            "authorized": False,
            "stage": stage,
            "failures": [
                {
                    "rule": "max_bundle_bytes",
                    "message": "Context bundle exceeds the configured byte limit.",
                    "actual": len(bundle_bytes),
                    "limit": policies["context"]["max_bundle_bytes"],
                }
            ],
        }
    if provenance_kind == "validated_task_approval":
        assert approval_receipt is not None
        assert approval_receipt_sha256 is not None
        refreshed_provenance = check_research_provenance(
            repo_root,
            run,
            approval_receipt,
            approval_receipt_sha256,
        )
        if not refreshed_provenance["ready"]:
            return {
                "produced": False,
                "authorized": False,
                "stage": stage,
                "failures": [
                    {
                        "rule": "provenance_state_changed",
                        "message": "Research approval provenance changed before bundle write.",
                        "details": refreshed_provenance["failures"],
                    }
                ],
            }
    if provenance_kind == "validated_stage_application":
        assert application_receipt is not None
        assert application_receipt_sha256 is not None
        try:
            refreshed_provenance = check_stage_application_provenance(
                repo_root,
                run,
                application_receipt,
                application_receipt_sha256,
            )
        except ValueError as error:
            refreshed_provenance = {
                "valid": False,
                "stage": None,
                "artifact": None,
                "status": None,
                "failures": [
                    {
                        "rule": "stage_application_provenance",
                        "message": str(error),
                    }
                ],
            }
        if not (
            refreshed_provenance["valid"]
            and refreshed_provenance["stage"] == "research"
            and refreshed_provenance["artifact"] == "research.md"
            and refreshed_provenance["status"] == "complete"
        ):
            return {
                "produced": False,
                "authorized": False,
                "stage": stage,
                "failures": [
                    {
                        "rule": "provenance_state_changed",
                        "message": "Research application provenance changed before bundle write.",
                        "details": refreshed_provenance["failures"],
                    }
                ],
            }
    write_atomic(output, bundle_bytes)
    return {
        "produced": True,
        "authorized": False,
        "stage": stage,
        "output": str(output),
        "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "size_bytes": len(bundle_bytes),
        "sources": [prompt_record["name"], *[record["name"] for record in artifact_records]],
    }


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Git checkout to expose read-only")
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="External filled artifact directory",
    )
    parser.add_argument("--stage", required=True, help="Read-only stage to bundle")
    parser.add_argument("--output", type=Path, required=True, help="External JSON output path")
    parser.add_argument("--approval-receipt", type=Path)
    parser.add_argument("--approval-receipt-sha256")
    parser.add_argument("--application-receipt", type=Path)
    parser.add_argument("--application-receipt-sha256")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--artifact-contract",
        type=Path,
        default=repo_root / ".agent" / "policies" / "artifact-contract.json",
    )
    parser.add_argument(
        "--prompt-contract",
        type=Path,
        default=repo_root / ".agent" / "policies" / "prompt-contract.json",
    )
    parser.add_argument(
        "--readiness-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "stage-readiness.json",
    )
    parser.add_argument(
        "--context-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "stage-context.json",
    )
    parser.add_argument(
        "--diff-policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "diff-policy.json",
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        default=repo_root / ".agent" / "prompts",
    )
    return parser


def format_text(result: dict[str, Any]) -> str:
    status = "PRODUCED" if result["produced"] else "NOT_PRODUCED"
    lines = [f"stage-context: {status} stage={result['stage']}", "authorized=false"]
    for failure in result.get("failures", []):
        lines.append(f"- {failure['rule']}: {failure['message']}")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    try:
        artifact = validate_artifacts.load_contract(args.artifact_contract)
        prompt = validate_prompts.load_prompt_contract(args.prompt_contract, artifact)
        policies = {
            "artifact": artifact,
            "prompt": prompt,
            "readiness": check_stage_readiness.load_readiness_policy(
                args.readiness_policy,
                artifact,
            ),
            "context": load_context_policy(args.context_policy, prompt, artifact),
            "diff": diff_policy.load_policy(args.diff_policy),
        }
        result = build_context(
            args.repo,
            args.run,
            args.stage,
            args.output,
            policies,
            args.prompts,
            args.approval_receipt,
            args.approval_receipt_sha256,
            args.application_receipt,
            args.application_receipt_sha256,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"stage-context: ERROR\n- {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["produced"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
