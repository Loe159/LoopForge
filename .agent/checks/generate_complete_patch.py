#!/usr/bin/env python3
"""Generate and validate a complete patch without modifying the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import diff_policy


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_snapshot(repo: Path) -> dict[str, Any]:
    status = diff_policy.run_git_with_environment(
        repo,
        {"GIT_OPTIONAL_LOCKS": "0"},
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    index_path = Path(
        diff_policy.run_git(repo, "rev-parse", "--git-path", "index").decode("utf-8").strip()
    )
    if not index_path.is_absolute():
        index_path = repo / index_path
    return {
        "head": diff_policy.run_git(repo, "rev-parse", "HEAD").decode("ascii").strip(),
        "index_digest": file_digest(index_path),
        "status": status,
    }


def configured_filter_drivers(repo: Path) -> set[str]:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={diff_policy.git_safe_directory(repo)}",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            "config",
            "--get-regexp",
            r"^filter\..*\.(clean|process)$",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode not in (0, 1):
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Unable to inspect Git content filters: {message or 'unknown error'}")
    drivers: set[str] = set()
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        key = line.split(maxsplit=1)[0]
        if key.startswith("filter.") and key.endswith((".clean", ".process")):
            drivers.add(key.removeprefix("filter.").rsplit(".", 1)[0])
    return drivers


def ensure_no_active_content_filters(repo: Path, paths: tuple[str, ...]) -> None:
    if not paths:
        return
    configured = configured_filter_drivers(repo)
    if not configured:
        return
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={diff_policy.git_safe_directory(repo)}",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            "check-attr",
            "-z",
            "--stdin",
            "filter",
        ],
        check=False,
        capture_output=True,
        input=b"\0".join(path.encode("utf-8") for path in paths) + b"\0",
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Unable to inspect Git attributes: {message or 'unknown error'}")
    fields = completed.stdout.decode("utf-8", errors="replace").split("\0")
    active: list[str] = []
    for index in range(0, len(fields) - 2, 3):
        path, attribute, value = fields[index : index + 3]
        if attribute == "filter" and value in configured:
            active.append(f"{path}: filter={value}")
    if active:
        raise ValueError(f"Active Git content filters are not allowed: {', '.join(active)}")


def generate_patch_bytes(repo: Path, base_commit: str) -> bytes:
    objects_path = Path(
        diff_policy.run_git(repo, "rev-parse", "--git-path", "objects").decode("utf-8").strip()
    )
    if not objects_path.is_absolute():
        objects_path = repo / objects_path
    objects_path = objects_path.resolve()

    with tempfile.TemporaryDirectory(prefix="complete-patch-git-") as temp_dir:
        temp = Path(temp_dir)
        temporary_objects = temp / "objects"
        temporary_objects.mkdir()
        environment = {
            "GIT_INDEX_FILE": str(temp / "index"),
            "GIT_OBJECT_DIRECTORY": str(temporary_objects),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(objects_path),
        }
        diff_policy.run_git_with_environment(repo, environment, "read-tree", base_commit)
        diff_policy.run_git_with_environment(repo, environment, "add", "-A", "--", ".")
        return diff_policy.run_git_with_environment(
            repo,
            environment,
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            base_commit,
            "--",
        )


def write_atomic(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary_output = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary_output, output)
    finally:
        temporary_output.unlink(missing_ok=True)


def generate_and_validate(
    repo: Path,
    base: str,
    output: Path,
    policy_path: Path,
    force: bool,
) -> dict[str, Any]:
    repo_root, base_commit, expected_paths = diff_policy.collect_worktree_paths(repo, base)
    output = output.resolve()
    if is_within(output, repo_root):
        raise ValueError("Output patch must be outside the Git checkout")
    if output.exists() and not force:
        raise ValueError("Output patch already exists; use --force to replace it")

    ensure_no_active_content_filters(repo_root, expected_paths)
    before = repository_snapshot(repo_root)
    patch_bytes = generate_patch_bytes(repo_root, base_commit)
    after_generation = repository_snapshot(repo_root)
    if before != after_generation:
        raise ValueError("Repository state changed while generating the patch")

    try:
        patch_text = patch_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Generated patch is not valid UTF-8") from error

    policy = diff_policy.load_policy(policy_path)
    result = diff_policy.evaluate_patch(patch_text, policy, expected_paths)
    contains_secret = any(
        violation["rule"] == "high_confidence_secret"
        for violation in result["violations"]
    )
    if contains_secret:
        if force:
            output.unlink(missing_ok=True)
    else:
        write_atomic(output, patch_bytes)
        if patch_text.strip() and not diff_policy.parse_patch(patch_text).malformed:
            result["violations"].extend(
                diff_policy.verify_patch_content(repo_root, base_commit, output)
            )
    result["allowed"] = not result["violations"]
    result["artifact"] = {
        "patch": str(output),
        "retained": not contains_secret,
        "sha256": hashlib.sha256(patch_bytes).hexdigest(),
        "size_bytes": len(patch_bytes),
    }
    result["worktree"] = {
        "repo": str(repo_root),
        "base_commit": base_commit,
        "unchanged_after_generation": True,
    }
    after_validation = repository_snapshot(repo_root)
    if before != after_validation:
        raise ValueError("Repository state changed while validating the patch")
    return result


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Git checkout to snapshot")
    parser.add_argument("--base", required=True, help="Base commit for the patch")
    parser.add_argument("--output", type=Path, required=True, help="Patch path outside the checkout")
    parser.add_argument(
        "--policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "diff-policy.json",
        help="Policy JSON file",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing output patch")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = generate_and_validate(
            args.repo,
            args.base,
            args.output,
            args.policy,
            args.force,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"complete-patch: ERROR\n- {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(diff_policy.format_text(result))
        print(f"patch_retained={str(result['artifact']['retained']).lower()}")
        if result["artifact"]["retained"]:
            print(f"patch={result['artifact']['patch']}")
        else:
            print(f"requested_patch={result['artifact']['patch']}")
        print(f"sha256={result['artifact']['sha256']}")
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
