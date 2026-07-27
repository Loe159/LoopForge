"""Project memory, templates, and durable learning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_MEMORY_FILE = "memory.md"

DURABLE_MEMORY_SECTIONS = (
    "Stable Project Facts",
    "User Preferences",
    "Verification Patterns",
    "Reusable Decisions",
    "Known Pitfalls",
)

MEMORY_CATEGORY_ALIASES = {
    "fact": "Stable Project Facts",
    "facts": "Stable Project Facts",
    "preference": "User Preferences",
    "preferences": "User Preferences",
    "verify": "Verification Patterns",
    "verification": "Verification Patterns",
    "decision": "Reusable Decisions",
    "decisions": "Reusable Decisions",
    "pitfall": "Known Pitfalls",
    "pitfalls": "Known Pitfalls",
}

TEMPLATES: dict[str, str] = {
    "templates/loop.md": """---
loop_version: 1
status: draft
autonomy: supervised
---

# Objective

Describe the concrete outcome.

# Scope

In scope:

Out of scope:

# Inputs

- Task:
- Repository:
- Base commit:
- Project pack:

# Tools

- Skills:
- Commands:
- Adapters:

# Success Checks

- Objective checks:
- Subjective rubric:

# Limits

- Max attempts:
- Max wall time:
- Max output:
- Stop on stagnation after:

# Rollback Strategy

Describe how to return to the previous safe state.

# Ask Human When

- Success criteria are subjective.
- The next action would publish, delete, expose secrets, or spend money.
- Repeated attempts produce the same failure.

# Current Attempt

Record the current attempt and diagnostic.
""",
    "templates/memory.md": """---
memory_version: 1
scope: project
status: active
---

# Stable Project Facts

# User Preferences

# Verification Patterns

# Reusable Decisions

# Known Pitfalls

# Promotion Log

Record why each durable memory item was kept.
""",
    "templates/scratch.md": """---
scratch_version: 1
status: active
---

# Working Notes

# Attempt Log

# Temporary Findings

# Discard Candidates
""",
    "templates/exchange.json": """{
  "exchange_version": 1,
  "run_id": "",
  "producer": "",
  "consumer": "",
  "messages": [],
  "artifacts": [],
  "open_questions": []
}
""",
}


@dataclass(frozen=True)
class LearnResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    proposals: list[dict[str, Any]]
    promoted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    proposal_path: Path | None
    blockers: list[str]


def ensure_templates(project_dir: Path) -> None:
    from loopforge.engine import project_config_dir

    root = project_config_dir(project_dir)
    for relative_name, contents in TEMPLATES.items():
        destination = root / relative_name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
    for directory_name in ("packs", "skills"):
        (root / directory_name).mkdir(parents=True, exist_ok=True)


def read_project_template(project_dir: Path, relative_name: str) -> str:
    from loopforge.engine import project_config_dir

    template_path = project_config_dir(project_dir) / "templates" / relative_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    fallback = TEMPLATES.get(f"templates/{relative_name}")
    if fallback is None:
        raise KeyError(f"unknown template: {relative_name}")
    return fallback


def durable_memory_path(project_dir: Path) -> Path:
    from loopforge.engine import project_config_dir

    return project_config_dir(project_dir) / PROJECT_MEMORY_FILE


def ensure_project_memory(project_dir: Path) -> Path:
    path = durable_memory_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(read_project_template(project_dir, "memory.md"), encoding="utf-8")
    return path


def durable_memory_items(project_dir: Path) -> dict[str, list[str]]:
    from loopforge.engine.artifacts import bullet_items, markdown_sections, section_text

    path = durable_memory_path(project_dir)
    if not path.exists():
        return {section: [] for section in DURABLE_MEMORY_SECTIONS}
    sections = markdown_sections(path.read_text(encoding="utf-8"))
    return {
        section: bullet_items(section_text(sections, section))
        for section in DURABLE_MEMORY_SECTIONS
    }


def memory_item_count(items: dict[str, list[str]]) -> int:
    return sum(len(values) for values in items.values())


def render_run_memory_snapshot(project_dir: Path, run_id: str) -> str:
    from loopforge.engine import utc_now

    source = ensure_project_memory(project_dir)
    items = durable_memory_items(project_dir)
    lines = [
        "---",
        "memory_version: 1",
        "scope: run",
        "status: active",
        f"source: {source}",
        f"captured_at: {utc_now()}",
        "---",
        "",
        "# Durable Project Memory Snapshot",
        "",
        "Compact project memory loaded for this run. Promotion logs and old run",
        "transcripts are intentionally omitted.",
        "",
    ]
    for section in DURABLE_MEMORY_SECTIONS:
        lines.extend([f"# {section}", ""])
        values = items.get(section, [])
        if values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- None recorded.")
        lines.append("")
    lines.extend(
        [
            "# Run Memory Notes",
            "",
            "Use `scratch.md` for temporary context and `loopforge learn` to propose",
            "durable updates.",
            "",
        ]
    )
    return "\n".join(lines)


def memory_status_from_proposals(run_dir: Path) -> dict[str, int | str | None]:
    from loopforge.engine import memory_proposal_path, read_json

    path = memory_proposal_path(run_dir)
    if not path.exists():
        return {
            "proposal_path": None,
            "pending": 0,
            "promoted": 0,
            "rejected": 0,
        }
    try:
        data = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "proposal_path": str(path),
            "pending": 0,
            "promoted": 0,
            "rejected": 0,
        }
    proposals = data.get("proposals", [])
    if not isinstance(proposals, list):
        proposals = []
    normalized = [item for item in proposals if isinstance(item, dict)]
    return {
        "proposal_path": str(path),
        "pending": sum(1 for item in normalized if item.get("status") == "pending"),
        "promoted": sum(1 for item in normalized if item.get("status") == "promoted"),
        "rejected": sum(1 for item in normalized if item.get("status") == "rejected"),
    }


def memory_state(project_dir: Path, run_dir: Path | None) -> dict[str, Any]:
    memory_path = durable_memory_path(project_dir)
    memory_missing = not memory_path.exists()
    items = durable_memory_items(project_dir)
    state: dict[str, Any] = {
        "durable_path": str(memory_path),
        "durable_status": "missing" if memory_missing else "present",
        "durable_items": memory_item_count(items),
        "sections": {section: len(values) for section, values in items.items()},
        "run_snapshot": str(run_dir / "memory.md") if run_dir is not None else None,
        "proposal_path": None,
        "pending": 0,
        "promoted": 0,
        "rejected": 0,
    }
    if run_dir is not None:
        state.update(memory_status_from_proposals(run_dir))
    return state


def parse_memory_candidate_text(text: str, *, source: str) -> tuple[str, str] | None:
    candidate = " ".join(text.strip().split())
    if not candidate:
        return None
    explicit = source == "cli-note"
    lowered = candidate.lower()
    if lowered.startswith("memory:"):
        explicit = True
        candidate = candidate.split(":", 1)[1].strip()
    match = re.match(r"^([A-Za-z][A-Za-z -]{1,30})\s*:\s*(.+)$", candidate)
    category = "Stable Project Facts"
    if match:
        alias = match.group(1).strip().lower().replace(" ", "-")
        alias = alias.replace("-", "_")
        normalized_alias = alias.replace("_", " ")
        category = (
            MEMORY_CATEGORY_ALIASES.get(alias)
            or MEMORY_CATEGORY_ALIASES.get(normalized_alias)
            or category
        )
        if alias in MEMORY_CATEGORY_ALIASES or normalized_alias in MEMORY_CATEGORY_ALIASES:
            explicit = True
            candidate = match.group(2).strip()
    if not explicit:
        return None
    if not candidate:
        return None
    return category, candidate


def learn_run(
    project_dir: Path,
    *,
    approve: bool = False,
    notes: list[str] | None = None,
    confirmed: bool = False,
) -> LearnResult:
    from loopforge.engine import (
        DEFAULT_PACK,
        DEFAULT_PROFILE,
        current_status,
        exchange_memory_candidates,
        load_pack_memory_rules,
        memory_candidate,
        memory_proposal_markdown_path,
        memory_proposal_path,
        normalize_nonempty_strings,
        pack_rule_allows_promotion,
        persist_run_json,
        profile_transition_blockers,
        promote_memory_candidate,
        relative_to_run,
        render_memory_proposals_markdown,
        scratch_memory_candidates,
        unique_memory_candidates,
        utc_now,
        write_json_atomic,
    )

    status = current_status(project_dir)
    if not status.initialized:
        return LearnResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="Initialize LoopForge before learning.",
            proposals=[],
            promoted=[],
            rejected=[],
            proposal_path=None,
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return LearnResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            ok=False,
            message="Create a run before proposing memory updates.",
            proposals=[],
            promoted=[],
            rejected=[],
            proposal_path=None,
            blockers=[status.next_step],
        )

    raw_candidates: list[dict[str, Any]] = []
    for note in normalize_nonempty_strings(notes):
        candidate = memory_candidate(
            note,
            source="cli-note",
            source_path=None,
            trusted=True,
        )
        if candidate is not None:
            raw_candidates.append(candidate)
    raw_candidates.extend(scratch_memory_candidates(status.run_dir))
    raw_candidates.extend(exchange_memory_candidates(status.run_dir))
    proposals = unique_memory_candidates(raw_candidates)

    pack = str(status.run.get("pack") or DEFAULT_PACK)
    try:
        rules = load_pack_memory_rules(status.project_dir, pack)
    except ValueError as error:
        rules = {"source": None, "auto_promote": []}
        rule_error = str(error)
    else:
        rule_error = ""

    promotion_requested = approve or any(
        proposal.get("status") != "rejected" and pack_rule_allows_promotion(rules, proposal)
        for proposal in proposals
    )
    profile_blockers = (
        profile_transition_blockers(
            profile=status.run.get("profile", DEFAULT_PROFILE),
            action="memory_promotion",
            confirmed=confirmed,
            run=status.run,
            contract=status.loop_contract,
        )
        if promotion_requested
        else []
    )

    promoted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if profile_blockers:
        for proposal in proposals:
            if proposal["status"] == "rejected":
                rejected.append(proposal)
    else:
        for proposal in proposals:
            if proposal["status"] == "rejected":
                rejected.append(proposal)
                continue
            promotion_reason = ""
            if approve:
                promotion_reason = "human_approved"
            elif pack_rule_allows_promotion(rules, proposal):
                promotion_reason = f"pack_rule:{rules.get('source') or 'unknown'}"
            if not promotion_reason:
                continue
            changed = promote_memory_candidate(
                status.project_dir,
                proposal,
                reason=promotion_reason,
                run_id=str(status.run.get("run_id") or ""),
            )
            proposal["status"] = "promoted" if changed else "already_present"
            proposal["promotion_reason"] = promotion_reason
            if changed:
                promoted.append(proposal)

    created = utc_now()
    proposal_data = {
        "version": 1,
        "created_at": created,
        "run_id": status.run.get("run_id"),
        "approval": approve and not profile_blockers,
        "pack": pack,
        "pack_rule_source": rules.get("source"),
        "profile_blockers": profile_blockers,
        "proposals": proposals,
    }
    if rule_error:
        proposal_data["rule_error"] = rule_error
    proposal_path = memory_proposal_path(status.run_dir)
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(proposal_path, proposal_data)
    memory_proposal_markdown_path(status.run_dir).write_text(
        render_memory_proposals_markdown(proposal_data),
        encoding="utf-8",
    )

    updated_run = dict(status.run)
    updated_run["memory"] = {
        "durable_project_memory": str(durable_memory_path(status.project_dir)),
        "run_snapshot": str(status.run_dir / "memory.md"),
        "last_proposal": relative_to_run(status.run_dir, proposal_path),
        "pending_proposals": sum(
            1 for proposal in proposals if proposal.get("status") == "pending"
        ),
        "promoted": len(promoted),
        "rejected": len(rejected),
        "updated_at": created,
    }
    updated_run["updated_at"] = created
    if status.run_json_path is not None:
        persist_run_json(status.project_dir, status.run_json_path, updated_run)

    blockers = [rule_error] if rule_error else []
    blockers.extend(profile_blockers)
    message = "LoopForge memory proposals written."
    if promoted:
        message = "LoopForge memory updated."
    if profile_blockers:
        message = "LoopForge memory promotion refused by the autonomy profile."
    return LearnResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated_run,
        ok=not blockers,
        message=message,
        proposals=proposals,
        promoted=promoted,
        rejected=rejected,
        proposal_path=proposal_path,
        blockers=blockers,
    )
