"""Read-only evidence models for the interactive console.

The engine owns artifact production and workflow transitions.  This module only
indexes those artifacts for search, preview, and approval explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterator


MAX_PREVIEW_CHARS = 12_000
MAX_PREVIEW_BYTES = 64 * 1024
PREVIEW_LINE_WINDOW = 240
TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".diff", ".patch"}
KIND_ORDER = {"plan": 0, "review": 1, "check": 2, "diff": 3, "log": 4, "memory": 5, "markdown": 6, "file": 7}


@dataclass(frozen=True)
class EvidenceItem:
    """One file produced by a run, with a presentation-safe relative path."""

    path: Path
    relative_path: str
    kind: str
    label: str
    size: int
    mtime_ns: int

    @property
    def cache_key(self) -> tuple[Path, int, int]:
        """Return the versioned key shared by preview and search caches."""

        return (self.path, self.size, self.mtime_ns)


@dataclass(frozen=True)
class ApprovalSummary:
    """Facts shown before a human approves a plan or review gate."""

    title: str
    artifact: str
    lines: tuple[str, ...]


class EvidenceIndex:
    """Lazy, metadata-only index for one run's evidence directory.

    Artifact discovery is intentionally separate from content access: building
    the index stats files but never opens them.  Content is read in bounded
    windows only for an explicit preview or a background search.
    """

    def __init__(self, root: Path | None, items: tuple[EvidenceItem, ...]) -> None:
        self.root = root
        self.items = items
        self._preview_cache: dict[tuple[Path, int, int], dict[int, str]] = {}
        self._search_cache: dict[tuple[Path, int, int], str] = {}

    @classmethod
    def build(cls, run_dir: Path | None) -> "EvidenceIndex":
        if run_dir is None or not run_dir.exists():
            return cls(None, ())
        root = run_dir.resolve()
        items: list[EvidenceItem] = []
        for path in root.rglob("*"):
            if not path.is_file() or not _is_within_root(path, root):
                continue
            item = _evidence_item(root, path)
            if item is not None:
                items.append(item)
        items.sort(key=lambda item: (KIND_ORDER[item.kind], item.relative_path.casefold()))
        return cls(root, tuple(items))

    def metadata_matches(self, query: str) -> tuple[EvidenceItem, ...]:
        needle = query.strip().casefold()
        if not needle:
            return self.items
        return tuple(
            item
            for item in self.items
            if needle in f"{item.label} {item.relative_path}".casefold()
        )

    def search_batches(self, query: str, *, batch_size: int = 32) -> Iterator[tuple[EvidenceItem, ...]]:
        """Yield progressively larger result sets for a background search."""

        needle = query.strip().casefold()
        if not needle:
            yield self.items
            return
        results: list[EvidenceItem] = []
        seen: set[tuple[Path, int, int]] = set()
        for item in self.metadata_matches(query):
            results.append(item)
            seen.add(item.cache_key)
        if results:
            yield tuple(results)
        checked = 0
        for item in self.items:
            if item.cache_key in seen or not _is_searchable(item):
                continue
            checked += 1
            if needle in self.searchable_content(item).casefold():
                results.append(item)
            if checked % max(1, batch_size) == 0:
                yield tuple(results)
        yield tuple(results)

    def searchable_content(self, item: EvidenceItem) -> str:
        cached = self._search_cache.get(item.cache_key)
        if cached is not None:
            return cached
        text = _read_bounded_text(item.path, maximum_bytes=MAX_PREVIEW_BYTES)
        self._search_cache[item.cache_key] = text[:MAX_PREVIEW_CHARS]
        return self._search_cache[item.cache_key]

    def preview(self, item: EvidenceItem, *, query: str = "", line_start: int = 0) -> str:
        """Return one bounded line window, caching it by the item fingerprint."""

        key = item.cache_key
        windows = self._preview_cache.setdefault(key, {})
        text = windows.get(line_start)
        if text is None:
            text = _read_preview_window(item.path, line_start=line_start)
            windows[line_start] = text
        return _filter_preview(text, item, query=query)

    def cached_preview(self, item: EvidenceItem, *, query: str = "", line_start: int = 0) -> str | None:
        text = self._preview_cache.get(item.cache_key, {}).get(line_start)
        return _filter_preview(text, item, query=query) if text is not None else None

    def invalidate(self, artifact: str | Path | None) -> bool:
        """Refresh just the artifact named by an operation event, if it is local."""

        if self.root is None or not artifact:
            return False
        candidate = Path(artifact)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            candidate = candidate.resolve()
            relative_path = candidate.relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return False
        previous = next((item for item in self.items if item.path.resolve() == candidate), None)
        updated = _evidence_item(self.root, candidate) if candidate.is_file() else None
        if previous is None and updated is None:
            return False
        if previous is not None:
            self._preview_cache.pop(previous.cache_key, None)
            self._search_cache.pop(previous.cache_key, None)
        items = [item for item in self.items if item.relative_path != relative_path]
        if updated is not None:
            items.append(updated)
        items.sort(key=lambda item: (KIND_ORDER[item.kind], item.relative_path.casefold()))
        self.items = tuple(items)
        return True


def evidence_items(run_dir: Path | None, *, query: str = "") -> tuple[EvidenceItem, ...]:
    """Compatibility helper; callers with a live UI should retain the index."""

    index = EvidenceIndex.build(run_dir)
    if not query.strip():
        return index.items
    results: tuple[EvidenceItem, ...] = ()
    for results in index.search_batches(query):
        pass
    return results


def preview_evidence(item: EvidenceItem, *, query: str = "") -> str:
    """Compatibility helper for an explicitly selected evidence item."""

    return EvidenceIndex(None, ()).preview(item, query=query)


def approval_summary(run_dir: Path | None, run: dict[str, Any] | None, stage: str) -> ApprovalSummary:
    """Describe exactly the recorded evidence affected by an approval action."""

    artifact_name = f"{stage}.md"
    artifact_path = run_dir / artifact_name if run_dir is not None else None
    if artifact_path is None or not artifact_path.exists():
        return ApprovalSummary(
            title=f"Approve {stage}?",
            artifact=artifact_name,
            lines=(f"{artifact_name} is not available yet.", "No workflow transition will be approved."),
        )
    text = artifact_path.read_text(encoding="utf-8", errors="replace")
    if stage == "plan":
        checks = _success_checks(run)
        steps = _section_item_count(text, "implementation") or _numbered_item_count(text)
        files = _section_item_count(text, "files")
        lines = [f"Evidence: {artifact_name}"]
        lines.append(f"{steps} planned step{'s' if steps != 1 else ''} recorded.")
        if files:
            lines.append(f"{files} file{'s' if files != 1 else ''} in recorded scope.")
        lines.append(f"{len(checks)} success check{'s' if len(checks) != 1 else ''} required before review.")
        return ApprovalSummary("Approve implementation plan?", artifact_name, tuple(lines))

    verification = run.get("verification", {}) if isinstance(run, dict) else {}
    verification = verification if isinstance(verification, dict) else {}
    findings = _section_item_count(text, "findings")
    risk = verification.get("risk", {})
    risk_value = risk.get("risk") if isinstance(risk, dict) else None
    lines = [f"Evidence: {artifact_name}", f"Verification: {verification.get('status') or 'not recorded'}."]
    lines.append(f"{findings} review finding{'s' if findings != 1 else ''} recorded.")
    if risk_value:
        lines.append(f"Recorded risk: {risk_value}.")
    changed_files = _changed_file_count(run_dir)
    if changed_files:
        lines.append(f"{changed_files} changed file{'s' if changed_files != 1 else ''} recorded in the patch evidence.")
    lines.append("Approval permits local draft preparation only; it does not publish anything.")
    return ApprovalSummary("Approve review for draft preparation?", artifact_name, tuple(lines))


def _evidence_item(root: Path, path: Path) -> EvidenceItem | None:
    try:
        resolved = path.resolve()
        relative_path = resolved.relative_to(root).as_posix()
        stat = resolved.stat()
    except OSError:
        return None
    kind, label = _kind_for(relative_path)
    return EvidenceItem(
        path=resolved,
        relative_path=relative_path,
        kind=kind,
        label=label,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _kind_for(relative_path: str) -> tuple[str, str]:
    path = Path(relative_path)
    lowered = relative_path.casefold()
    name = path.name.casefold()
    if name == "plan.md":
        return "plan", "Plan"
    if name == "review.md":
        return "review", "Review"
    if name == "verification.md" or "check" in lowered:
        return "check", "Check"
    if path.suffix.casefold() in {".diff", ".patch"} or "patch" in lowered:
        return "diff", "Diff"
    if "attempt" in lowered or name.startswith(("stdout", "stderr")) or path.suffix.casefold() == ".log":
        return "log", "Log"
    if "memory" in lowered or "proposal" in name:
        return "memory", "Memory"
    if path.suffix.casefold() == ".md":
        return "markdown", "Markdown"
    return "file", "File"


def _is_searchable(item: EvidenceItem) -> bool:
    return item.path.suffix.casefold() in TEXT_SUFFIXES


def _read_bounded_text(path: Path, *, maximum_bytes: int) -> str:
    try:
        with path.open("rb") as source:
            return source.read(maximum_bytes).decode("utf-8", errors="replace")
    except OSError as error:
        return f"Unable to read {path.name}: {error}"


def _read_preview_window(path: Path, *, line_start: int) -> str:
    # Byte-bounded reads avoid both whole-file allocations and widget payloads.
    text = _read_bounded_text(path, maximum_bytes=MAX_PREVIEW_BYTES)
    if text.startswith("Unable to read "):
        return text
    lines = text.splitlines()
    start = max(0, line_start)
    preview = "\n".join(lines[start : start + PREVIEW_LINE_WINDOW])
    if len(text) >= MAX_PREVIEW_BYTES or len(lines) > start + PREVIEW_LINE_WINDOW:
        preview += "\n… preview truncated"
    return preview[:MAX_PREVIEW_CHARS] or "(empty artifact)"


def _filter_preview(text: str, item: EvidenceItem, *, query: str) -> str:
    needle = query.strip().casefold()
    if not needle:
        return text
    matches = [line for line in text.splitlines() if needle in line.casefold()]
    return "\n".join(matches[:80]) if matches else "No matching content in this artifact."


def _section_item_count(text: str, section_name: str) -> int:
    lines = text.splitlines()
    target = section_name.casefold()
    active = False
    items = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            active = target in stripped.lstrip("#").strip().casefold()
            continue
        if active and (re.match(r"[-*+]\s+", stripped) or re.match(r"\d+[.)]\s+", stripped)):
            items += 1
    return items


def _numbered_item_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if re.match(r"\s*\d+[.)]\s+", line))


def _success_checks(run: dict[str, Any] | None) -> list[object]:
    if not isinstance(run, dict):
        return []
    contract = run.get("loop_contract", {})
    if not isinstance(contract, dict):
        contract = run.get("pack_contract", {})
    checks = contract.get("success_checks", []) if isinstance(contract, dict) else []
    if not checks:
        checks = run.get("success_checks", [])
    return checks if isinstance(checks, list) else []


def _changed_file_count(run_dir: Path | None) -> int:
    files: set[str] = set()
    index = EvidenceIndex.build(run_dir)
    for item in index.items:
        if item.kind != "diff":
            continue
        for line in index.searchable_content(item).splitlines():
            match = re.match(r"\+\+\+ b/(.+)$", line)
            if match and match.group(1) != "/dev/null":
                files.add(match.group(1))
    return len(files)
