"""Read-only, confined projections of retained workspace change evidence."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shlex
import stat
from typing import Any

from loopforge.cli.run_artifacts import _clean_text
from loopforge.engine.path_resolvers import resolve_artifact

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_RENDER_CHARS = 128 * 1024


@dataclass(frozen=True)
class RunFileChange:
    path: str
    status: str
    previous_path: str | None = None
    binary: bool = False
    additions: int | None = None
    deletions: int | None = None
    diff: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class RunChangesSnapshot:
    scope: str = "execution"
    capture_state: str = "unavailable"
    base_commit: str | None = None
    before_head: str | None = None
    after_head: str | None = None
    files: tuple[RunFileChange, ...] = ()
    message: str = "No retained workspace snapshot for this execution."
    stale: bool = False
    source: str = ""


def safe_artifact(root: Path, reference: Any) -> Path | None:
    """Reject traversal and links, even links whose target stays under the root."""
    if not isinstance(reference, (str, Path)) or not str(reference):
        return None
    ref = Path(reference)
    if ref.is_absolute() or ".." in ref.parts:
        return None
    try:
        current = root
        for part in ref.parts:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or int(getattr(info, "st_file_attributes", 0)) & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                return None
        return resolve_artifact(root, str(ref))
    except (OSError, ValueError, RuntimeError):
        return None


def read_artifact(root: Path, reference: Any, maximum: int = MAX_ARTIFACT_BYTES) -> bytes | None:
    path = safe_artifact(root, reference)
    try:
        if path is None or not path.is_file() or path.stat().st_size > maximum:
            return None
        with path.open("rb") as source:
            value = source.read(maximum + 1)
        return value if len(value) <= maximum else None
    except OSError:
        return None


def read_object(root: Path, reference: Any) -> dict[str, Any]:
    raw = read_artifact(root, reference)
    try:
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, ValueError):
        return {}


def session_reference(session: Any) -> str:
    if isinstance(session, (str, Path)):
        return str(session)
    if isinstance(session, dict):
        return str(session.get("session_dir") or session.get("session_id") or "")
    return str(getattr(session, "session_dir", "") or getattr(session, "session_id", "") or "")


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        return ""
    return _clean_text(value, 1024)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _retained_files(values: Any) -> tuple[RunFileChange, ...]:
    if not isinstance(values, list):
        return ()
    rows = []
    remaining = 512 * 1024
    for item in values[:4000]:
        if not isinstance(item, dict) or not (name := _safe_name(item.get("path"))):
            continue
        raw = str(item.get("diff") or "")
        budget = min(MAX_RENDER_CHARS, remaining)
        diff = _clean_text(raw[:budget])
        # Bound a single terminal line as well as the total widget payload.
        diff = "\n".join(line[:2000] for line in diff.splitlines())
        remaining -= len(diff)
        rows.append(RunFileChange(name, str(item.get("status") or "unknown"),
            _safe_name(item.get("previous_path")) or None, item.get("binary") is True,
            _count(item.get("additions")), _count(item.get("deletions")), diff,
            item.get("truncated") is True or len(raw) > budget or any(len(line) > 2000 for line in raw.splitlines())))
    return tuple(rows)


def _patch_files(text: str) -> tuple[RunFileChange, ...]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            try:
                paths = shlex.split(line)[2:]
            except ValueError:
                paths = []
            current = {"path": paths[-1][2:] if paths else "", "status": "modified", "diff": "", "additions": 0, "deletions": 0}
            entries.append(current)
        if current is None:
            continue
        current["diff"] += line
        if line.startswith("new file mode "):
            current["status"] = "added"
        elif line.startswith("deleted file mode "):
            current["status"] = "deleted"
        elif line.startswith("rename from "):
            current.update(status="renamed", previous_path=line[len("rename from "):].strip())
        elif line.startswith("rename to "):
            current["path"] = line[len("rename to "):].strip()
        elif line.startswith(("Binary files ", "GIT binary patch")):
            current.update(binary=True, additions=None, deletions=None)
        elif line.startswith("+") and not line.startswith("+++") and current.get("additions") is not None:
            current["additions"] += 1
        elif line.startswith("-") and not line.startswith("---") and current.get("deletions") is not None:
            current["deletions"] += 1
    return _retained_files(entries)


def verified_patch(root: Path, verification: dict[str, Any]) -> tuple[bytes | None, str]:
    patch = verification.get("patch")
    if not isinstance(patch, dict):
        return None, "No retained cumulative patch."
    raw = read_artifact(root, patch.get("path"))
    if raw is None:
        return None, "The cumulative patch is unavailable or exceeds the preview budget."
    expected = patch.get("sha256")
    if not isinstance(expected, str) or sha256(raw).hexdigest() != expected.lower() or patch.get("size_bytes") != len(raw):
        return None, "The retained patch no longer matches its verification receipt."
    return raw, ""


def load_run_changes(status: Any, session: Any = None, *, cumulative: bool = False) -> RunChangesSnapshot:
    root, run = getattr(status, "run_dir", None), getattr(status, "run", None)
    if root is None or not isinstance(run, dict):
        return RunChangesSnapshot()
    if cumulative:
        verification = run.get("verification")
        if not isinstance(verification, dict):
            history = run.get("verification_history")
            verification = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
        raw, reason = verified_patch(root, verification)
        stale = verification.get("candidate_revision") != run.get("candidate_revision", 0)
        return RunChangesSnapshot(scope="run cumulative", capture_state="complete" if raw is not None else "unavailable",
            base_commit=run.get("base_commit"), files=_patch_files(raw.decode("utf-8", "replace")) if raw else (),
            message=reason or ("Retained cumulative patch for an earlier candidate." if stale else "Retained cumulative patch from the run Git base."),
            stale=stale, source="deterministic-verification-patch")
    ref = session_reference(session)
    if not ref:
        return RunChangesSnapshot()
    data = read_object(root, f"{ref}/changes.json")
    if data.get("schema_version") != 1 or data.get("run_id") != run.get("run_id") or data.get("source") != "runner-workspace-snapshots":
        return RunChangesSnapshot()
    files = _retained_files(data.get("files"))
    state = str(data.get("capture_state") or "unavailable")
    readonly = data.get("stage_id") in {"research", "plan", "review"}
    message = ("No workspace changes expected; none observed." if readonly else "No workspace changes observed.") if not files and state == "complete" else "Workspace snapshots captured before and after this execution."
    if readonly and files:
        message = "Workspace changes observed during a read-only stage; inspect the engine's violation evidence."
    if state == "bounded":
        message += " Capture was bounded; unknown paths are not attributed."
    if state == "unavailable":
        message = "Workspace snapshots were unavailable for this execution."
    return RunChangesSnapshot(capture_state=state, base_commit=data.get("base_commit"),
        before_head=data.get("before_head"), after_head=data.get("after_head"), files=files,
        message=message, source="runner-workspace-snapshots")
