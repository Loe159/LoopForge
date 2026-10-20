"""Bounded, read-only Git workspace snapshots at execution boundaries.

These observations never authorize a transition. A dirty starting tree is the
baseline, so earlier edits and commits cannot be attributed to a later attempt.
"""
from __future__ import annotations

from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
import stat
from typing import Any

from loopforge.engine.process_runner import ProcessRunner
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.workspace import _resolve_git_executable

MAX_FILES = 4000
MAX_FILE_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_DIFF_CHARS = 128 * 1024
MAX_TOTAL_DIFF_CHARS = 512 * 1024


def _query(workspace: Path, *args: str) -> str | None:
    git = _resolve_git_executable()
    if git is None:
        return None
    receipt = ProcessRunner(output_limit_bytes=1024 * 1024, timeout=10).run(
        [git, *args], cwd=workspace,
    )
    if (not receipt.completed or receipt.returncode != 0
            or receipt.output_truncated or receipt.output_limit_exceeded):
        return None
    return receipt.stdout


def capture_workspace_state(workspace_dir: Path) -> dict[str, Any]:
    """Capture bounded file content without altering Git's index or object store."""
    result: dict[str, Any] = {"capture_state": "unavailable", "files": {}}
    try:
        workspace = workspace_dir.resolve(strict=True)
        names = _query(workspace, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        if names is None:
            return result
        head = _query(workspace, "rev-parse", "HEAD")
        result.update(capture_state="complete", head=head.strip() if head else None)
        paths = sorted(set(filter(None, names.split("\0"))))
        if len(paths) > MAX_FILES:
            result["capture_state"] = "bounded"
        remaining = MAX_SNAPSHOT_BYTES
        for name in paths[:MAX_FILES]:
            if name.startswith((".loopforge/runtime-prompts/", ".loopforge/runtime-stages/")):
                continue
            path = workspace / name
            # Links are not followed, including links in an ancestor directory.
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts:
                result["capture_state"] = "bounded"
                continue
            current = workspace
            unsafe = False
            for part in parts:
                current /= part
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    break
                attrs = int(getattr(info, "st_file_attributes", 0))
                if stat.S_ISLNK(info.st_mode) or attrs & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                    unsafe = True
                    break
            if unsafe:
                result["files"][name] = {"unavailable": "symlink or junction"}
                result["capture_state"] = "bounded"
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue  # Tracked, deleted file: absent in this workspace snapshot.
            if not stat.S_ISREG(info.st_mode) or info.st_size > min(MAX_FILE_BYTES, remaining):
                result["files"][name] = {"unavailable": "capture budget", "size": info.st_size}
                result["capture_state"] = "bounded"
                continue
            with path.open("rb") as source:
                content = source.read(min(MAX_FILE_BYTES, remaining) + 1)
            if len(content) > min(MAX_FILE_BYTES, remaining):
                result["files"][name] = {"unavailable": "file grew during capture"}
                result["capture_state"] = "bounded"
                continue
            remaining -= len(content)
            binary = b"\0" in content
            try:
                text = None if binary else content.decode("utf-8")
            except UnicodeDecodeError:
                binary, text = True, None
            result["files"][name] = {
                "sha256": sha256(content).hexdigest(), "size": len(content),
                "text": text, "binary": binary, "executable": bool(info.st_mode & stat.S_IXUSR),
            }
    except (OSError, ValueError):
        result["capture_state"] = "unavailable"
    return result


def execution_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare retained snapshots, marking uncertain paths instead of guessing."""
    state = "complete"
    if "unavailable" in (before.get("capture_state"), after.get("capture_state")):
        return {"capture_state": "unavailable", "files": []}
    if before.get("capture_state") != "complete" or after.get("capture_state") != "complete":
        state = "bounded"
    old, new = before.get("files", {}), after.get("files", {})
    removed = {name: item for name, item in old.items() if name not in new and item.get("sha256")}
    added = {name: item for name, item in new.items() if name not in old and item.get("sha256")}
    renames: dict[str, str] = {}
    for name, item in added.items():
        matches = [previous for previous, previous_item in removed.items()
                   if previous_item["sha256"] == item["sha256"]]
        destinations = [value for value in added.values() if value["sha256"] == item["sha256"]]
        if len(matches) == len(destinations) == 1:
            renames[name] = matches[0]
    entries: list[dict[str, Any]] = []
    remaining = MAX_TOTAL_DIFF_CHARS
    for name in sorted(set(old) | set(new)):
        if name in renames.values():
            continue
        previous = renames.get(name)
        left, right = old.get(previous or name), new.get(name)
        if left == right:
            continue
        unknown = bool((left and left.get("unavailable")) or (right and right.get("unavailable")))
        if not left and before.get("capture_state") == "bounded":
            unknown = True
        if not right and after.get("capture_state") == "bounded":
            unknown = True
        status = "unknown" if unknown else "renamed" if previous else "added" if left is None else "deleted" if right is None else "modified"
        binary = bool((left or {}).get("binary") or (right or {}).get("binary"))
        diff, additions, deletions, truncated = "", None, None, False
        if not unknown and not binary:
            old_lines = (left or {}).get("text", "").splitlines(keepends=True)
            new_lines = (right or {}).get("text", "").splitlines(keepends=True)
            lines = list(unified_diff(old_lines, new_lines,
                fromfile=f"a/{previous or name}" if left else "/dev/null",
                tofile=f"b/{name}" if right else "/dev/null"))
            additions = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
            deletions = sum(line.startswith("-") and not line.startswith("---") for line in lines)
            full = "".join(lines)
            limit = min(MAX_DIFF_CHARS, remaining)
            diff, truncated = full[:limit], len(full) > limit
            remaining -= len(diff)
        entries.append({"path": name, "previous_path": previous, "status": status,
            "binary": binary, "additions": additions, "deletions": deletions,
            "diff": diff, "truncated": truncated,
            "before_sha256": (left or {}).get("sha256"), "after_sha256": (right or {}).get("sha256")})
    return {"capture_state": state, "files": entries,
        "before_head": before.get("head"), "after_head": after.get("head")}


def write_execution_changes(*, run_dir: Path, execution_dir: Path, run: dict[str, Any],
    stage_id: str, session_id: str, attempt_id: str | None,
    before: dict[str, Any], after: dict[str, Any]) -> None:
    """Persist observation only; capture failures must not change workflow policy."""
    try:
        from loopforge.engine import utc_now
        execution_dir.resolve().relative_to(run_dir.resolve())
        payload = execution_changes(before, after)
        payload.update(schema_version=1, source="runner-workspace-snapshots",
            run_id=run.get("run_id"), stage_id=stage_id, session_id=session_id,
            attempt_id=attempt_id, candidate_revision=run.get("candidate_revision"),
            base_commit=run.get("base_commit"), captured_at=utc_now())
        DEFAULT_JSON_STORE.write_object(execution_dir / "changes.json", payload)
    except (OSError, ValueError):
        return
