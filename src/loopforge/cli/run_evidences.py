"""Read-only run evidence, separated from agent output and historical sessions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.cli.evidence import EvidenceIndex
from loopforge.cli.run_changes import read_artifact, session_reference
from loopforge.cli.run_artifacts import _clean_text


@dataclass(frozen=True)
class RunEvidenceSection:
    key: str
    title: str
    body: str
    expanded: bool = False


@dataclass(frozen=True)
class RunEvidencesSnapshot:
    sections: tuple[RunEvidenceSection, ...] = ()


def _safe(value: Any) -> str:
    return _clean_text(str(value or ""), 260)


def load_run_evidences(status: Any, session: Any = None, *, stage_id: str | None = None) -> RunEvidencesSnapshot:
    root, run = getattr(status, "run_dir", None), getattr(status, "run", None)
    if not isinstance(root, Path) or not isinstance(run, dict):
        return RunEvidencesSnapshot()
    ref = session_reference(session).rstrip("/")
    number = getattr(session, "attempt_number", None)
    latest = max((a.get("number", 0) for a in run.get("attempts", [])
                  if isinstance(a, dict) and isinstance(a.get("number"), int)), default=None)
    historical = (stage_id or getattr(session, "stage_id", "")) not in ("", run.get("current_stage")) or (
        number is not None and number != latest)
    paths = []
    for item in EvidenceIndex.build(root).items:
        name = item.relative_path
        if ref and not name.startswith(ref + "/"):
            continue
        if name.endswith(("context-raw-prompt.md", "context-instructions.md")):
            continue
        if name.endswith((".md", ".json", ".log", ".diff", ".patch", ".stdout")):
            paths.append(f"{_safe(item.kind)} · {_safe(name)} · {item.size} bytes")
    sections = []
    blockers = getattr(status, "blockers", None) or run.get("blockers") or ()
    if blockers:
        sections.append(RunEvidenceSection("problems", "Problems · engine",
            "Source: LoopForge workflow state\n" + "\n".join(_safe(problem) for problem in tuple(blockers)[:30]), True))
    sections.append(RunEvidenceSection("deliverables", f"Deliverables ({len(paths)})",
        "\n".join(paths[:100]) if paths else "No retained deliverable for this execution.", True))
    contract = []
    if number is not None:
        attempt = next((a for a in run.get("attempts", []) if isinstance(a, dict)
                        and a.get("number") == number), None)
        if attempt:
            path = attempt.get("result_path")
            if read_artifact(root, path, 128_000) is not None:
                contract.append(f"Agent output extracted: {_safe(path)} (not deterministic verification)")
            if attempt.get("contract_validation_error"):
                contract.append("Contract rejected: " + _safe(attempt["contract_validation_error"]))
    sections.append(RunEvidenceSection("contracts", "Output contracts",
        "\n".join(contract) or "No output contract receipt for this execution."))
    verification = run.get("verification") if isinstance(run.get("verification"), dict) else {}
    lines = []
    if verification:
        lines.append(f"LoopForge deterministic verification · candidate {verification.get('candidate_revision', '?')}")
        if historical:
            lines.append("Run-level receipt; NOT attributed to this historical execution.")
        if verification.get("candidate_revision") != run.get("candidate_revision", 0):
            lines.append("STALE: verification does not cover the current candidate.")
        lines.append("Outcome: " + _safe(verification.get("status")))
        for name in ("patch", "diff_policy", "risk"):
            sub = verification.get(name)
            if isinstance(sub, dict):
                lines.append(name + ": " + _safe(sub.get("status") or sub.get("risk") or "unknown"))
        for check in (verification.get("checks") or [])[:100]:
            if isinstance(check, dict):
                lines.append(_safe(check.get("name")) + ": " + _safe(check.get("status") or "unknown"))
        for message in (verification.get("blockers") or [])[:20]:
            lines.append("BLOCKER: " + _safe(message))
    sections.append(RunEvidenceSection("checks", "Tests & verification",
        "\n".join(lines) or "No deterministic verification recorded."))
    decisions = []
    gates = run.get("human_gates")
    for name, gate in (gates if isinstance(gates, dict) else {}).items():
        if isinstance(gate, dict):
            line = f"{_safe(name)}: {_safe(gate.get('status') or 'unknown')}"
            if gate.get("source"):
                line += " · source " + _safe(gate["source"])
            if gate.get("approved_at"):
                line += " · " + _safe(gate["approved_at"])
            if name == "review_approval" and gate.get("status") == "approved" and gate.get("candidate_revision") != run.get("candidate_revision", 0):
                line += " · STALE"
            decisions.append(line)
    sections.append(RunEvidenceSection("decisions", "Human decisions",
        "Run-level gates (not agent claims)\n" + "\n".join(decisions) if decisions else "No human decisions recorded."))
    return RunEvidencesSnapshot(tuple(sections))
