"""Git-aware workspace observations for interactive implementation attempts."""

from __future__ import annotations

from pathlib import Path

from loopforge.engine.process_runner import ProcessReceipt, ProcessRunner
from loopforge.engine.workspace import _resolve_git_executable, detect_git_base_commit


GitFingerprint = tuple[str | None, tuple[tuple[str, tuple[int, int] | None], ...]]


def git_status_entry_paths(entries: list[str] | None) -> set[str]:
    paths: set[str] = set()
    for entry in entries or []:
        value = entry[3:] if len(entry) > 3 else ""
        if " -> " in value:
            paths.update(value.split(" -> ", 1))
        elif value:
            paths.add(value.strip('"'))
    return paths


def _git_query(project_dir: Path, arguments: list[str]) -> ProcessReceipt | None:
    git_path = _resolve_git_executable()
    if git_path is None:
        return None
    return ProcessRunner(output_limit_bytes=50000, timeout=10).run(
        [git_path, *arguments],
        cwd=project_dir,
    )


def git_status_paths(project_dir: Path) -> set[str] | None:
    receipt = _git_query(
        project_dir,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    if receipt is None or not receipt.completed:
        return None
    records = receipt.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        status = record[:2]
        path = record[3:] if len(record) > 3 else ""
        if path:
            paths.add(path)
        if ("R" in status or "C" in status) and index + 1 < len(records):
            original = records[index + 1]
            if original:
                paths.add(original)
            index += 1
        index += 1
    return paths


def git_commit_changes(project_dir: Path, before_head: str, after_head: str) -> list[str]:
    if before_head == after_head:
        return []
    receipt = _git_query(
        project_dir,
        ["diff", "--name-status", before_head, after_head],
    )
    if receipt is None or not receipt.completed:
        return [f"HEAD changed from {before_head[:12]} to {after_head[:12]}"]
    return [line for line in receipt.stdout.splitlines() if line.strip()]


def gitlink_paths(project_dir: Path) -> list[str]:
    receipt = _git_query(project_dir, ["ls-files", "--stage", "-z"])
    if receipt is None or not receipt.completed:
        return []
    paths: list[str] = []
    for record in receipt.stdout.split("\0"):
        if not record or "\t" not in record:
            continue
        metadata, path = record.split("\t", 1)
        if metadata.split(" ", 1)[0] == "160000":
            paths.append(path)
    return paths


def nested_git_fingerprints(project_dir: Path) -> dict[str, GitFingerprint]:
    fingerprints: dict[str, GitFingerprint] = {}
    pending = [(project_dir, "")]
    visited: set[Path] = set()
    while pending:
        parent_root, parent_prefix = pending.pop()
        for name in gitlink_paths(parent_root):
            nested_root = parent_root / name
            if not nested_root.is_dir():
                continue
            resolved = nested_root.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            relative_root = f"{parent_prefix}{name}".replace("\\", "/")
            pending.append((nested_root, f"{relative_root.rstrip('/')}/"))
            status_paths = git_status_paths(nested_root)
            head = detect_git_base_commit(nested_root)
            if status_paths is None and head is None:
                continue
            path_states: list[tuple[str, tuple[int, int] | None]] = []
            for path_name in sorted(status_paths or set()):
                path = nested_root / path_name
                try:
                    stat = path.stat()
                except OSError:
                    state = None
                else:
                    state = (stat.st_size, stat.st_mtime_ns)
                path_states.append((path_name, state))
            fingerprints[relative_root] = (head, tuple(path_states))
    return fingerprints


def terminal_snapshot_change_visible(
    path: str,
    visible_paths: set[str],
    before_nested: dict[str, GitFingerprint],
    after_nested: dict[str, GitFingerprint],
) -> bool:
    for nested_root in sorted(set(before_nested) | set(after_nested), key=len, reverse=True):
        prefix = f"{nested_root.rstrip('/')}/"
        if not path.startswith(prefix):
            continue
        before = before_nested.get(nested_root)
        after = after_nested.get(nested_root)
        if before is None or after is None or before[0] != after[0]:
            return True
        local_path = path[len(prefix) :]
        nested_visible_paths = {name for name, _state in (*before[1], *after[1])}
        return any(
            local_path == name or local_path.startswith(f"{name.rstrip('/')}/")
            for name in nested_visible_paths
        )
    return any(
        path == visible or path.startswith(f"{visible.rstrip('/')}/")
        for visible in visible_paths
    )
