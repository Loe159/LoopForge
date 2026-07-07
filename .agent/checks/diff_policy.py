#!/usr/bin/env python3
"""Validate a unified Git patch against a small deterministic policy."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class PatchFacts:
    file_count: int
    changed_lines: int
    paths: tuple[str, ...]
    binary_paths: tuple[str, ...]
    symlink_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    rename_from_paths: tuple[str, ...]
    added_lines: tuple[tuple[str, str], ...]
    removed_lines: tuple[tuple[str, str], ...]
    malformed: bool


def normalize_path(raw_path: str, strip_git_prefix: bool = False) -> str | None:
    path = raw_path.replace("\\", "/")
    if path == "/dev/null":
        return None
    if strip_git_prefix and (path.startswith("a/") or path.startswith("b/")):
        path = path[2:]
    return str(PurePosixPath(path))


def has_path_traversal(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts


def parse_patch(patch: str) -> PatchFacts:
    paths: set[str] = set()
    file_count = 0
    changed_lines = 0
    in_file = False
    in_hunk = False
    malformed = False
    current_paths: set[str] = set()
    binary_paths: set[str] = set()
    symlink_paths: set[str] = set()
    deleted_paths: set[str] = set()
    rename_from_paths: set[str] = set()
    added_lines: list[tuple[str, str]] = []
    removed_lines: list[tuple[str, str]] = []
    current_binary = False
    current_symlink = False
    current_deleted = False

    def add_path(raw_path: str, strip_git_prefix: bool = False) -> str | None:
        normalized = normalize_path(raw_path, strip_git_prefix)
        if normalized is not None:
            paths.add(normalized)
        return normalized

    def finalize_file() -> None:
        if current_binary:
            binary_paths.update(current_paths)
        if current_symlink:
            symlink_paths.update(current_paths)
        if current_deleted:
            deleted_paths.update(current_paths)

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            finalize_file()
            in_file = True
            in_hunk = False
            current_paths = set()
            current_binary = False
            current_symlink = False
            current_deleted = False
            file_count += 1
            try:
                parts = shlex.split(line)
            except ValueError:
                malformed = True
                continue
            if len(parts) != 4:
                malformed = True
                continue
            for raw_path in parts[2:]:
                if normalized := add_path(raw_path, strip_git_prefix=True):
                    current_paths.add(normalized)
            continue

        if not in_file:
            if line.strip():
                malformed = True
            continue

        if line.startswith("@@"):
            in_hunk = True
            continue

        if not in_hunk and line.startswith(("+++ ", "--- ")):
            try:
                parts = shlex.split(line)
            except ValueError:
                malformed = True
                continue
            if len(parts) < 2:
                malformed = True
                continue
            if normalized := add_path(parts[1], strip_git_prefix=True):
                current_paths.add(normalized)
            continue

        if not in_hunk and line.startswith(("rename from ", "rename to ")):
            _, _, raw_path = line.partition(" ")
            _, _, raw_path = raw_path.partition(" ")
            if not raw_path:
                malformed = True
                continue
            normalized = add_path(raw_path)
            if line.startswith("rename from ") and normalized is not None:
                rename_from_paths.add(normalized)
            continue
        if not in_hunk and line.startswith("deleted file mode "):
            current_deleted = True
        if not in_hunk and (
            line == "GIT binary patch" or line.startswith("Binary files ")
        ):
            current_binary = True
            continue
        if not in_hunk and (
            line.startswith(
                (
                    "new file mode 120000",
                    "deleted file mode 120000",
                    "old mode 120000",
                    "new mode 120000",
                )
            )
            or (line.startswith("index ") and line.endswith(" 120000"))
        ):
            current_symlink = True
            continue
        if in_hunk and line.startswith("+"):
            added_lines.extend((path, line[1:]) for path in sorted(current_paths))
            changed_lines += 1
        elif in_hunk and line.startswith("-"):
            removed_lines.extend((path, line[1:]) for path in sorted(current_paths))
            changed_lines += 1

    finalize_file()
    if patch.strip() and file_count == 0:
        malformed = True

    return PatchFacts(
        file_count=file_count,
        changed_lines=changed_lines,
        paths=tuple(sorted(paths)),
        binary_paths=tuple(sorted(binary_paths)),
        symlink_paths=tuple(sorted(symlink_paths)),
        deleted_paths=tuple(sorted(deleted_paths)),
        rename_from_paths=tuple(sorted(rename_from_paths)),
        added_lines=tuple(added_lines),
        removed_lines=tuple(removed_lines),
        malformed=malformed,
    )


def load_policy(policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    required = {
        "version",
        "max_files",
        "max_changed_lines",
        "protected_patterns",
        "allow_binary_files",
        "allow_symlinks",
        "test_path_patterns",
        "forbidden_added_test_patterns",
        "forbidden_removed_test_patterns",
        "secret_patterns",
    }
    missing = required.difference(policy)
    if missing:
        raise ValueError(f"Policy is missing required fields: {', '.join(sorted(missing))}")
    if (
        not isinstance(policy["version"], int)
        or isinstance(policy["version"], bool)
        or policy["version"] != 1
    ):
        raise ValueError(f"Unsupported policy version: {policy['version']}")
    for field in ("max_files", "max_changed_lines"):
        if not isinstance(policy[field], int) or isinstance(policy[field], bool) or policy[field] < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    patterns = policy["protected_patterns"]
    if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
        raise ValueError("protected_patterns must be a list of strings")
    for field in ("allow_binary_files", "allow_symlinks"):
        if not isinstance(policy[field], bool):
            raise ValueError(f"{field} must be a boolean")
    for field in (
        "test_path_patterns",
        "forbidden_added_test_patterns",
        "forbidden_removed_test_patterns",
    ):
        values = policy[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{field} must be a list of strings")
    for field in ("forbidden_added_test_patterns", "forbidden_removed_test_patterns"):
        for pattern in policy[field]:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"Invalid regular expression in {field}: {pattern}") from error
    secret_patterns = policy["secret_patterns"]
    if not isinstance(secret_patterns, list):
        raise ValueError("secret_patterns must be a list")
    secret_ids: set[str] = set()
    for secret_pattern in secret_patterns:
        if (
            not isinstance(secret_pattern, dict)
            or set(secret_pattern) != {"id", "pattern"}
            or not isinstance(secret_pattern["id"], str)
            or not secret_pattern["id"]
            or not isinstance(secret_pattern["pattern"], str)
        ):
            raise ValueError("Each secret_patterns entry must contain string id and pattern fields")
        if secret_pattern["id"] in secret_ids:
            raise ValueError(f"Duplicate secret pattern id: {secret_pattern['id']}")
        secret_ids.add(secret_pattern["id"])
        try:
            re.compile(secret_pattern["pattern"])
        except re.error as error:
            raise ValueError(
                f"Invalid regular expression for secret pattern {secret_pattern['id']}"
            ) from error
    return policy


def decode_git_paths(output: bytes) -> set[str]:
    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Git returned a path that is not valid UTF-8") from error
    return {
        normalized
        for raw_path in decoded.split("\0")
        if raw_path and (normalized := normalize_path(raw_path, strip_git_prefix=False)) is not None
    }


def run_git(repo: Path, *arguments: str) -> bytes:
    return run_git_with_environment(repo, None, *arguments)


def git_safe_directory(repo: Path) -> str:
    return str(repo.resolve()).replace("\\", "/")


def run_git_with_environment(
    repo: Path,
    environment: dict[str, str] | None,
    *arguments: str,
) -> bytes:
    command_environment = os.environ.copy()
    if environment is not None:
        command_environment.update(environment)
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={git_safe_directory(repo)}",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=command_environment,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git command failed: {message or 'unknown error'}")
    return completed.stdout


def check_git_apply(
    repo: Path,
    patch_path: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> str | None:
    command_environment = os.environ.copy()
    if environment is not None:
        command_environment.update(environment)
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={git_safe_directory(repo)}",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            "apply",
            "--check",
            "--binary",
            "--whitespace=nowarn",
            *arguments,
            str(patch_path.resolve()),
        ],
        check=False,
        capture_output=True,
        env=command_environment,
    )
    if completed.returncode == 0:
        return None
    return completed.stderr.decode("utf-8", errors="replace").strip() or "Git rejected the patch."


def collect_worktree_paths(repo: Path, base: str) -> tuple[Path, str, tuple[str, ...]]:
    repo_root = Path(run_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    base_commit = (
        run_git(repo_root, "rev-parse", "--verify", f"{base}^{{commit}}").decode("ascii").strip()
    )
    tracked = decode_git_paths(
        run_git(
            repo_root,
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "-z",
            base_commit,
            "--",
        )
    )
    untracked = decode_git_paths(
        run_git(repo_root, "ls-files", "--others", "--exclude-standard", "-z", "--")
    )
    return repo_root.resolve(), base_commit, tuple(sorted(tracked | untracked))


def verify_patch_content(repo: Path, base_commit: str, patch_path: Path) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="diff-policy-index-") as temp_dir:
        index_path = Path(temp_dir) / "index"
        environment = {"GIT_INDEX_FILE": str(index_path)}
        run_git_with_environment(repo, environment, "read-tree", base_commit)
        reverse_error = check_git_apply(
            repo,
            patch_path,
            "--reverse",
            environment=environment,
        )
        if reverse_error is not None:
            violations.append(
                {
                    "rule": "patch_matches_worktree_content",
                    "message": "Patch post-image does not match the current worktree.",
                    "detail": reverse_error,
                }
            )

        run_git_with_environment(repo, environment, "read-tree", base_commit)
        base_error = check_git_apply(
            repo,
            patch_path,
            "--cached",
            environment=environment,
        )
    if base_error is not None:
        violations.append(
            {
                "rule": "patch_applies_to_base",
                "message": "Patch pre-image does not match the declared base commit.",
                "detail": base_error,
            }
        )
    return violations


def evaluate_patch(
    patch: str,
    policy: dict[str, Any],
    expected_paths: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    facts = parse_patch(patch)
    violations: list[dict[str, Any]] = []

    if facts.malformed:
        violations.append(
            {
                "rule": "valid_git_patch",
                "message": "Patch is not an empty patch or a valid Git unified diff.",
            }
        )

    traversal_paths = [path for path in facts.paths if has_path_traversal(path)]
    if traversal_paths:
        violations.append(
            {
                "rule": "no_path_traversal",
                "message": "Patch contains unsafe paths.",
                "paths": traversal_paths,
            }
        )

    protected_paths = [
        path
        for path in facts.paths
        if any(
            fnmatch.fnmatchcase(path.casefold(), pattern.casefold())
            for pattern in policy["protected_patterns"]
        )
    ]
    if protected_paths:
        violations.append(
            {
                "rule": "protected_paths",
                "message": "Patch changes protected paths that require human approval.",
                "paths": protected_paths,
            }
        )

    if facts.binary_paths and not policy["allow_binary_files"]:
        violations.append(
            {
                "rule": "binary_files_require_approval",
                "message": "Binary file changes require explicit human approval.",
                "paths": list(facts.binary_paths),
            }
        )

    if facts.symlink_paths and not policy["allow_symlinks"]:
        violations.append(
            {
                "rule": "symlinks_require_approval",
                "message": "Symbolic link changes require explicit human approval.",
                "paths": list(facts.symlink_paths),
            }
        )

    test_path_patterns = policy["test_path_patterns"]

    def find_forbidden_test_changes(
        changed_lines_to_check: tuple[tuple[str, str], ...],
        patterns: list[str],
        change: str,
    ) -> list[dict[str, str]]:
        compiled = [re.compile(pattern) for pattern in patterns]
        return [
            {"path": path, "change": change}
            for path, line in changed_lines_to_check
            if any(
                fnmatch.fnmatchcase(path.casefold(), pattern.casefold())
                for pattern in test_path_patterns
            )
            and any(pattern.search(line) for pattern in compiled)
        ]

    added_test_disables = find_forbidden_test_changes(
        facts.added_lines,
        policy["forbidden_added_test_patterns"],
        "added_forbidden_annotation",
    )
    removed_test_annotations = find_forbidden_test_changes(
        facts.removed_lines,
        policy["forbidden_removed_test_patterns"],
        "removed_test_annotation",
    )
    if added_test_disables or removed_test_annotations:
        matches = added_test_disables + removed_test_annotations
        violations.append(
            {
                "rule": "test_disable_requires_approval",
                "message": "Patch explicitly disables tests and requires human approval.",
                "paths": sorted({match["path"] for match in matches}),
                "matches": matches,
            }
        )

    removed_test_files = sorted(
        path
        for path in set(facts.deleted_paths) | set(facts.rename_from_paths)
        if any(
            fnmatch.fnmatchcase(path.casefold(), pattern.casefold())
            for pattern in test_path_patterns
        )
    )
    if removed_test_files:
        violations.append(
            {
                "rule": "test_file_removal_requires_approval",
                "message": "Deleting or renaming test files requires human approval.",
                "paths": removed_test_files,
            }
        )

    secret_detections = sorted(
        {
            (path, secret_pattern["id"])
            for path, line in facts.added_lines
            for secret_pattern in policy["secret_patterns"]
            if re.search(secret_pattern["pattern"], line)
        }
    )
    if secret_detections:
        violations.append(
            {
                "rule": "high_confidence_secret",
                "message": "Patch adds a high-confidence secret signature.",
                "paths": sorted({path for path, _ in secret_detections}),
                "detections": [
                    {"path": path, "signature": signature}
                    for path, signature in secret_detections
                ],
            }
        )

    if facts.file_count > policy["max_files"]:
        violations.append(
            {
                "rule": "max_files",
                "message": f"Patch changes {facts.file_count} files; limit is {policy['max_files']}.",
            }
        )

    if facts.changed_lines > policy["max_changed_lines"]:
        violations.append(
            {
                "rule": "max_changed_lines",
                "message": (
                    f"Patch changes {facts.changed_lines} lines; "
                    f"limit is {policy['max_changed_lines']}."
                ),
            }
        )

    worktree_paths: list[str] | None = None
    if expected_paths is not None:
        patch_paths = set(facts.paths)
        expected = set(expected_paths)
        missing_from_patch = sorted(expected - patch_paths)
        absent_from_worktree = sorted(patch_paths - expected)
        worktree_paths = sorted(expected)
        if missing_from_patch or absent_from_worktree:
            violation: dict[str, Any] = {
                "rule": "patch_matches_worktree",
                "message": "Patch paths do not exactly match the worktree changes.",
            }
            if missing_from_patch:
                violation["missing_from_patch"] = missing_from_patch
            if absent_from_worktree:
                violation["absent_from_worktree"] = absent_from_worktree
            violations.append(violation)

    return {
        "allowed": not violations,
        "facts": {
            "file_count": facts.file_count,
            "changed_lines": facts.changed_lines,
            "paths": list(facts.paths),
            "binary_paths": list(facts.binary_paths),
            "symlink_paths": list(facts.symlink_paths),
            "deleted_paths": list(facts.deleted_paths),
            "rename_from_paths": list(facts.rename_from_paths),
            "worktree_paths": worktree_paths,
        },
        "violations": violations,
    }


def format_text(result: dict[str, Any]) -> str:
    facts = result["facts"]
    status = "ALLOWED" if result["allowed"] else "BLOCKED"
    lines = [
        f"diff-policy: {status}",
        f"files={facts['file_count']} changed_lines={facts['changed_lines']}",
    ]
    for violation in result["violations"]:
        lines.append(f"- {violation['rule']}: {violation['message']}")
        for path in violation.get("paths", []):
            lines.append(f"  {path}")
        for path in violation.get("missing_from_patch", []):
            lines.append(f"  missing_from_patch: {path}")
        for path in violation.get("absent_from_worktree", []):
            lines.append(f"  absent_from_worktree: {path}")
        for match in violation.get("matches", []):
            lines.append(f"  {match['path']}: {match['change']}")
        for detection in violation.get("detections", []):
            lines.append(f"  {detection['path']}: {detection['signature']}")
        if "detail" in violation:
            lines.append(f"  detail: {violation['detail']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True, help="Git unified diff to validate")
    parser.add_argument(
        "--policy",
        type=Path,
        default=repo_root / ".agent" / "policies" / "diff-policy.json",
        help="Policy JSON file",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--repo",
        type=Path,
        help="Git checkout whose complete worktree change set must match the patch",
    )
    parser.add_argument(
        "--base",
        help="Base commit used to calculate the complete worktree change set",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if (args.repo is None) != (args.base is None):
            raise ValueError("--repo and --base must be provided together")
        patch = args.patch.read_text(encoding="utf-8")
        policy = load_policy(args.policy)
        expected_paths = None
        if args.repo is not None and args.base is not None:
            repo_root, base_commit, expected_paths = collect_worktree_paths(args.repo, args.base)
        result = evaluate_patch(patch, policy, expected_paths)
        if args.repo is not None and args.base is not None:
            contains_secret = any(
                violation["rule"] == "high_confidence_secret"
                for violation in result["violations"]
            )
            if patch.strip() and not parse_patch(patch).malformed and not contains_secret:
                result["violations"].extend(verify_patch_content(repo_root, base_commit, args.patch))
                result["allowed"] = not result["violations"]
            result["worktree"] = {
                "repo": str(repo_root),
                "base_commit": base_commit,
            }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"diff-policy: ERROR\n- {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
