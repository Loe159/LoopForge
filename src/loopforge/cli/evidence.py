"""Read-only evidence models for the interactive console.

The engine owns artifact production and workflow transitions.  This module only
indexes those artifacts for search, preview, and approval explanations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


MAX_PREVIEW_CHARS = 12_000
TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".diff", ".patch"}
KIND_ORDER = {"plan": 0, "review": 1, "check": 2, "diff": 3, "log": 4, "memory": 5, "markdown": 6, "file": 7}


@dataclass(frozen=True)
class EvidenceItem:
    """One file produced by a run, with a presentation-safe relative path."""

    path: Path
    relative_path: str
    kind: str
    label: str
    searchable_text: str


@dataclass(frozen=True)
class ApprovalSummary:
    """Facts shown before a human approves a plan or review gate."""

    title: str
    artifact: str
    lines: tuple[str, ...]


def evidence_items(run_dir: Path | None, *, query: str = "") -> tuple[EvidenceItem, ...]:
    """Return searchable artifacts without following paths outside a run."""

    if run_dir is None or not run_dir.exists():
        return ()
    root = run_dir.resolve()
    paths = {
        path
        for path in root.rglob("*")
        if path.is_file() and _is_within_root(path, root)
    }
    items = [_evidence_item(root, path) for path in paths]
    items.sort(key=lambda item: (KIND_ORDER[item.kind], item.relative_path.casefold()))
    needle = query.strip().casefold()
    if not needle:
        return tuple(items)
    return tuple(item for item in items if needle in _searchable(item).casefold())


def preview_evidence(item: EvidenceItem, *, query: str = "") -> str:
    """Read a bounded UTF-8 preview, optionally retaining matching lines."""

    try:
        text = item.path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"Unable to read {item.relative_path}: {error}"
    text = text[:MAX_PREVIEW_CHARS]
    needle = query.strip().casefold()
    if needle:
        matches = [line for line in text.splitlines() if needle in line.casefold()]
        if matches:
            text = "\n".join(matches[:80])
        else:
            text = "No matching content in this artifact."
    try:
        source_size = item.path.stat().st_size
    except OSError:
        source_size = 0
    if source_size > len(text.encode("utf-8", errors="replace")):
        text += "\n… preview truncated"
    return text or "(empty artifact)"


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


def _evidence_item(root: Path, path: Path) -> EvidenceItem:
    relative_path = path.resolve().relative_to(root).as_posix()
    kind, label = _kind_for(relative_path)
    return EvidenceItem(
        path=path,
        relative_path=relative_path,
        kind=kind,
        label=label,
        searchable_text=_read_searchable(path),
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


def _read_searchable(path: Path) -> str:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_PREVIEW_CHARS]
    except OSError:
        return ""


def _searchable(item: EvidenceItem) -> str:
    return f"{item.label} {item.relative_path}\n{item.searchable_text}"


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
    for item in evidence_items(run_dir):
        if item.kind != "diff":
            continue
        for line in item.searchable_text.splitlines():
            match = re.match(r"\+\+\+ b/(.+)$", line)
            if match and match.group(1) != "/dev/null":
                files.add(match.group(1))
    return len(files)
