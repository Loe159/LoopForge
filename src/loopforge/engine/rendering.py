"""Rendering and prompt assembly domain for LoopForge runs.

Owns the pure string producers that turn run/verification/dashboard data into
markdown artifacts and adapter/stage prompts: the loop contract, embedded run
artifacts, adapter and stage prompts, draft publication bodies, progress
appends, verification markdown, loop diagnostics, memory proposal markdown,
and the dashboard summary helpers.

Extracted from ``engine/__init__.py``. These functions mostly take data as
input and produce strings, with minimal cross-domain dependencies. The
markdown bullet helper is pulled from the leaf ``artifacts`` submodule at the
top level; lifecycle primitives remain safe top-level imports. Cross-domain
helpers and constants still owned by ``engine/__init__.py`` are pulled in via
lazy imports to avoid an import cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopforge.engine.artifacts import bullet_items


def compact_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def remove_placeholder_item(lines: list[str], start: int, end: int) -> list[str]:
    cleaned = list(lines)
    for index in range(end - 1, start, -1):
        if cleaned[index].strip().lower() == "- none recorded.":
            del cleaned[index]
    return cleaned


def append_markdown_bullet(path: Path, section: str, item: str) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    header = f"# {section}"
    try:
        header_index = next(index for index, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, "", f"- {item}", ""])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return True

    next_header = len(lines)
    for index in range(header_index + 1, len(lines)):
        if lines[index].startswith("# "):
            next_header = index
            break
    existing = bullet_items("\n".join(lines[header_index + 1 : next_header]))
    if item in existing:
        return False
    lines = remove_placeholder_item(lines, header_index + 1, next_header)
    next_header = len(lines)
    for index in range(header_index + 1, len(lines)):
        if lines[index].startswith("# "):
            next_header = index
            break
    insert_at = next_header
    while insert_at > header_index + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"- {item}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def render_memory_proposals_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Memory Proposals",
        "",
        f"- Created: {data['created_at']}",
        f"- Approved: {'yes' if data['approval'] else 'no'}",
        f"- Pack rule source: {data.get('pack_rule_source') or 'none'}",
        "",
    ]
    proposals = data.get("proposals", [])
    if not proposals:
        lines.append("No memory proposals found.")
        lines.append("")
        return "\n".join(lines)
    for proposal in proposals:
        lines.extend(
            [
                f"## {proposal['id']}",
                "",
                f"- Status: {proposal['status']}",
                f"- Category: {proposal['category']}",
                f"- Source: {proposal.get('source_path') or proposal['source']}",
                f"- Text: {proposal['text']}",
            ]
        )
        if proposal.get("rejection_reason"):
            lines.append(f"- Rejection: {proposal['rejection_reason']}")
        if proposal.get("promotion_reason"):
            lines.append(f"- Promotion: {proposal['promotion_reason']}")
        lines.append("")
    return "\n".join(lines)


def render_loop_contract(
    *,
    task: str,
    task_id: str,
    project_dir: Path,
    base_commit: str | None,
    profile: str,
    pack: str,
    skills: list[str],
    allowed_tools: list[str],
    success_checks: list[str],
    max_attempts: int,
    timeout_seconds: int,
    subjective: bool,
    subjective_rubric: str,
) -> str:
    from loopforge.engine import loop_contract_status

    status = loop_contract_status(
        success_checks=success_checks,
        profile=profile,
        subjective=subjective,
        subjective_rubric=subjective_rubric,
    )

    def list_block(items: list[str], empty: str = "None recorded.") -> str:
        if not items:
            return empty
        return "\n".join(f"- {item}" for item in items)

    review_conditions = [
        "Success checks are missing or no longer match the task.",
        (
            "The next action would publish, delete, expose secrets, spend money, "
            "or use hidden network access."
        ),
        "Two attempts produce the same failure without new evidence.",
    ]
    if subjective:
        review_conditions.append(
            "Subjective quality is involved and the rubric is missing or disputed."
        )

    return f"""---
loop_version: 1
status: {status}
autonomy: {profile}
subjective: {str(subjective).lower()}
---

# Objective

{task}

# Scope

In scope:

- Complete the task described in `task.md`.
- Keep changes bounded to the target project and the external LoopForge run artifacts.

Out of scope:

- Publishing, remote side effects, destructive cleanup, or memory promotion
  without a later explicit phase.
- Treating receipts, validation, or metrics as publication authority.

# Inputs

- Task ID: {task_id}
- Task: {task}
- Repository: {project_dir}
- Base commit: {base_commit or "none"}

# Selected Project Pack

{pack}

# Selected Skills

{list_block(skills)}

# Allowed Tools

{list_block(allowed_tools)}

# Success Checks

{list_block(success_checks)}

# Subjective Rubric

{subjective_rubric.strip() or "None recorded."}

# Limits

- Max attempts: {max_attempts}
- Timeout seconds: {timeout_seconds}
- Max output: adapter default

# Stagnation Rule

Stop after two attempts produce the same failure, the same blocker, or no new evidence.

# Rollback Strategy

Use Git or explicit patch review to inspect and undo LoopForge changes. Preserve
unrelated working-tree changes.

# Human Review Conditions

{list_block(review_conditions)}

# Current Attempt

No autonomous attempt has run yet.
"""


def render_embedded_run_artifacts(run_dir: Path, artifact_names: tuple[str, ...]) -> list[str]:
    """Return bounded prompt context without granting a sandbox write access to the run."""

    from loopforge.engine import EMBEDDED_RUN_ARTIFACT_LIMIT

    lines = [
        "## Embedded Run Inputs",
        "",
        "The adapter sandbox may not access the external run directory. "
        "The approved input artifacts are embedded below; treat them as the source of truth.",
    ]
    for name in artifact_names:
        path = run_dir / name
        try:
            content = path.read_text(encoding="utf-8") if path.is_file() else ""
        except (OSError, UnicodeError):
            content = ""
        if len(content) > EMBEDDED_RUN_ARTIFACT_LIMIT:
            content = (
                content[:EMBEDDED_RUN_ARTIFACT_LIMIT]
                + "\n\n[LoopForge truncated this artifact for the adapter prompt.]\n"
            )
        lines.extend(
            [
                "",
                f"### {name}",
                "",
                "```text",
                content or "[No content recorded.]",
                "```",
            ]
        )
    return lines


def render_adapter_prompt(
    *,
    run: dict[str, Any],
    contract: dict[str, Any],
    run_dir: Path,
    workspace_dir: Path,
    adapter: str,
    attempt_id: str,
) -> str:
    from loopforge.engine import (
        IMPLEMENTATION_INPUT_ARTIFACTS,
        pack_agent_for_stage,
        pack_agent_prompt,
        pack_permission_for_agent,
    )

    success_checks = contract.get("success_checks") or run.get("success_checks") or []
    if not isinstance(success_checks, list):
        success_checks = []
    allowed_tools = contract.get("allowed_tools")
    if not isinstance(allowed_tools, list):
        allowed_tools = []
    pack_contract = run.get("pack_contract", {})
    skills = []
    if isinstance(pack_contract, dict) and isinstance(pack_contract.get("skills"), list):
        skills = [str(skill) for skill in pack_contract["skills"]]
    limits = run.get("limits", {}) if isinstance(run.get("limits"), dict) else {}
    agent = pack_agent_for_stage(run, "implementation")
    permission = pack_permission_for_agent(run, agent)
    lines = [
        "# LoopForge Adapter Attempt",
        "",
        "You are executing one bounded LoopForge implementation attempt.",
        "Do not stop at analysis: make the requested code changes when feasible.",
        "",
        "## Paths",
        "",
        f"- Run directory: {run_dir}",
        f"- Workspace directory: {workspace_dir}",
        f"- Project control checkout: {run.get('project_root')}",
        f"- Attempt: {attempt_id}",
        f"- Adapter: {adapter}",
        f"- Agent: {agent.get('id') if agent else 'developer'}",
        f"- Permission set: {agent.get('permission_set') if agent else 'workspace-write'}",
        "",
        "Make code changes only in the workspace directory unless the run contract says otherwise.",
        "Preserve unrelated working-tree changes.",
        "Do not publish, push, deploy, delete unrelated files, expose secrets, "
        "or use hidden network effects.",
        "",
        "## Objective",
        "",
        str(run.get("task") or "").strip(),
        "",
        "## Success Checks",
        "",
    ]
    if success_checks:
        lines.extend(f"- {check}" for check in success_checks)
    else:
        lines.append("- None recorded.")
    lines.extend([""])
    lines.extend(render_embedded_run_artifacts(run_dir, IMPLEMENTATION_INPUT_ARTIFACTS))
    lines.extend(["", "## Allowed Tools", ""])
    if allowed_tools:
        lines.extend(f"- {tool}" for tool in allowed_tools)
    else:
        lines.append("- Use only local deterministic project tools.")
    lines.extend(["", "## Pack Skills", ""])
    lines.extend(f"- {skill}" for skill in skills) if skills else lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Limits",
            "",
            f"- Max attempts: {limits.get('max_attempts', 'unknown')}",
            f"- Timeout seconds: {limits.get('timeout_seconds', 'unknown')}",
            "",
            "## Required Finish",
            "",
            "Run the relevant deterministic checks from the success checks when possible.",
            "Leave the workspace with the implementation changes present for `loopforge verify`.",
            "Summarize what changed and any checks run.",
            "",
        ]
    )
    if permission is not None:
        lines.extend(
            [
                "",
                "## Permission Boundary",
                "",
                json.dumps(permission, indent=2, sort_keys=True),
            ]
        )
    agent_prompt = pack_agent_prompt(agent)
    if agent_prompt:
        lines.extend(["", "## Pack Agent Instructions", "", agent_prompt.strip()])
    return "\n".join(lines)


def render_stage_prompt(
    *,
    stage: str,
    run: dict[str, Any],
    run_dir: Path,
    workspace_dir: Path,
    adapter: str,
    artifact_output_path: Path | None = None,
) -> str:
    from loopforge.engine import (
        READONLY_STAGE_INPUT_ARTIFACTS,
        READONLY_STAGE_SUCCESS,
        REQUIRED_READONLY_STAGE_SECTIONS,
        pack_agent_for_stage,
        pack_agent_prompt,
        pack_permission_for_agent,
    )

    artifact = f"{stage}.md"
    sections = REQUIRED_READONLY_STAGE_SECTIONS.get(stage, ())
    input_artifacts = READONLY_STAGE_INPUT_ARTIFACTS.get(stage, ())
    agent = pack_agent_for_stage(run, stage)
    permission = pack_permission_for_agent(run, agent)
    rendered_permission = permission
    if artifact_output_path is not None and isinstance(permission, dict):
        rendered_permission = dict(permission)
        filesystem = permission.get("filesystem")
        if isinstance(filesystem, dict):
            rendered_permission["filesystem"] = {
                **filesystem,
                "write": [str(artifact_output_path)],
            }
    if artifact_output_path is None:
        output_instructions = [
            "Produce exactly one complete portable Markdown artifact on stdout.",
            "Start directly with YAML frontmatter. Do not use a fence, preface, or postscript.",
            "Keep every required heading even when its only bounded conclusion is unknown.",
            "Do not modify the workspace. Read project files and run artifacts only.",
        ]
    else:
        output_instructions = [
            "Produce exactly one complete portable Markdown artifact in this UTF-8 file:",
            str(artifact_output_path),
            (
                "Start the file directly with YAML frontmatter. Do not add a fence, "
                "preface, or postscript."
            ),
            "Keep every required heading even when its only bounded conclusion is unknown.",
            "Do not only print the artifact in the terminal.",
            (
                "Do not modify, stage, or commit any other workspace file. The artifact "
                "path above is the only permitted write."
            ),
        ]
    lines = [
        f"# LoopForge {stage.title()} Stage",
        "",
        *output_instructions,
        "",
        "## Paths",
        "",
        f"- Run directory: {run_dir}",
        f"- Workspace directory: {workspace_dir}",
        f"- Artifact: {artifact}",
        f"- Adapter: {adapter}",
        f"- Agent: {agent.get('id') if agent else stage}",
        f"- Permission set: {agent.get('permission_set') if agent else 'read-only'}",
        "",
        "## Objective",
        "",
        str(run.get("task") or "").strip(),
        "",
        "## Required Inputs",
        "",
        "## Required Artifact",
        "",
        "- YAML frontmatter with artifact_version, artifact, issue, base_commit, and status.",
        f"- artifact: {stage}",
        f"- status: {READONLY_STAGE_SUCCESS[stage][0]}",
        "",
        "## Required Sections",
        "",
    ]
    lines.extend(render_embedded_run_artifacts(run_dir, input_artifacts))
    lines.append("")
    lines.extend(f"- {section}" for section in sections)
    lines.append("")
    if rendered_permission is not None:
        lines.extend(
            [
                "## Permission Boundary",
                "",
                json.dumps(rendered_permission, indent=2, sort_keys=True),
                "",
            ]
        )
    agent_prompt = pack_agent_prompt(agent)
    if agent_prompt:
        lines.extend(["## Pack Agent Instructions", "", agent_prompt.strip(), ""])
    if artifact_output_path is not None:
        lines.extend(
            [
                "## Interactive Harness Output Override",
                "",
                (
                    "For this interactive session, any instruction to return the artifact "
                    "on stdout means: write it to the artifact path above."
                ),
                (
                    "The read-only boundary still applies to every other workspace path; "
                    "only the controlled artifact file may be written."
                ),
                "",
            ]
        )
    return "\n".join(lines)


def draft_publication_body(run: dict[str, Any], verification: dict[str, Any]) -> str:
    patch = verification.get("patch", {}) if isinstance(verification.get("patch"), dict) else {}
    checks_passed = verification.get("checks_passed", 0)
    checks_total = verification.get("checks_total", 0)
    lines = [
        f"# {run.get('task') or 'LoopForge run'}",
        "",
        "Draft PR prepared by LoopForge after explicit review approval.",
        "",
        "## Verification",
        "",
        f"- Status: {verification.get('status') or 'unknown'}",
        f"- Checks: {checks_passed}/{checks_total}",
        f"- Patch: {patch.get('path') or 'none'}",
        f"- Patch SHA-256: {patch.get('sha256') or 'none'}",
    ]
    criterion_results = verification.get("criterion_results", [])
    if isinstance(criterion_results, list) and criterion_results:
        lines.extend(["", "## Acceptance Criteria", ""])
        for item in criterion_results:
            if isinstance(item, dict):
                lines.append(
                    f"- {compact_text(item.get('criterion'))}: "
                    f"{compact_text(item.get('status')) or 'unknown'}"
                )
    lines.extend(["", "## Publication", "", "- Draft: true", "- Network: not performed"])
    return "\n".join(lines) + "\n"


def append_progress(run_dir: Path, attempt: dict[str, Any]) -> None:
    progress_path = run_dir / "progress.md"
    lines = [
        "",
        f"## Attempt {attempt['number']}: {attempt['adapter']}",
        "",
        f"- Started: {attempt['started_at']}",
        f"- Finished: {attempt['finished_at']}",
        f"- Status: {attempt['status']}",
        f"- Summary: {attempt['summary']}",
        f"- Workspace changed: {'yes' if attempt['workspace_changed'] else 'no'}",
        f"- Workspace: {attempt.get('workspace') or 'unknown'}",
        f"- Prompt: {attempt.get('prompt_path') or 'none'}",
        f"- Stdout: {attempt['stdout_path']}",
        f"- Stderr: {attempt['stderr_path']}",
        f"- Result: {attempt['result_path']}",
    ]
    changes = attempt.get("workspace_changes", [])
    if changes:
        lines.append("- Workspace changes:")
        for change in changes[:20]:
            lines.append(f"  - {change}")
    if len(changes) > 20:
        lines.append(f"  - ... {len(changes) - 20} more")
    lines.append("")
    progress_path.write_text(
        progress_path.read_text(encoding="utf-8") + "\n".join(lines),
        encoding="utf-8",
    )


def render_verification_markdown(verification: dict[str, Any]) -> str:
    lines = [
        "# Verification",
        "",
        f"- Started: {verification['started_at']}",
        f"- Finished: {verification['finished_at']}",
        f"- Status: {verification['status']}",
        f"- Patch generated: {'yes' if verification['patch'].get('generated') else 'no'}",
        f"- Patch: {verification['patch'].get('path') or 'none'}",
        f"- Patch size bytes: {verification['patch'].get('size_bytes', 0)}",
        f"- Diff policy allowed: {str(verification['diff_policy'].get('allowed')).lower()}",
        f"- Risk: {verification['risk'].get('risk') or 'unknown'}",
        f"- Risk policy: {verification['risk'].get('policy') or 'none'}",
        f"- Pack checks: {verification['checks_passed']}/{verification['checks_total']}",
        "",
        "## Diff Policy",
        "",
    ]
    violations = verification["diff_policy"].get("violations", [])
    if violations:
        for violation in violations:
            if isinstance(violation, dict):
                lines.append(
                    f"- {violation.get('rule', 'violation')}: "
                    f"{violation.get('message', '')}"
                )
            else:
                lines.append(f"- {violation}")
    else:
        lines.append("- No deterministic policy violations recorded.")
    lines.extend(["", "## Risk", ""])
    reasons = verification["risk"].get("reasons", [])
    if reasons:
        for reason in reasons:
            if isinstance(reason, dict):
                lines.append(
                    f"- {reason.get('level', 'unknown')} {reason.get('rule', 'reason')}: "
                    f"{reason.get('message', '')}"
                )
    else:
        lines.append("- No risk elevation reasons recorded.")
    sources = verification["risk"].get("policy_sources", [])
    if sources:
        lines.extend(["", "## Risk Policy Sources", ""])
        for source in sources:
            lines.append(f"- {source}")
    criterion_results = verification.get("criterion_results", [])
    if criterion_results:
        lines.extend(["", "## Acceptance Criteria", ""])
        for cr in criterion_results:
            if not isinstance(cr, dict):
                continue
            criterion_text = cr.get("criterion", "")
            status = cr.get("status", "unknown")
            lines.extend(
                [
                    f"### Criterion: {criterion_text}",
                    f"- Status: {status}",
                    "",
                ]
            )
            for check in cr.get("checks", []):
                if not isinstance(check, dict):
                    continue
                lines.append(
                    f"- {check.get('name', 'unnamed')}: {check.get('status', 'unknown')} "
                    f"(returncode: {check.get('returncode')})"
                )
            lines.append("")

    lines.extend(["", "## Pack Checks", ""])
    if verification["pack_checks_source"]:
        lines.append(f"- Source: {verification['pack_checks_source']}")
    else:
        lines.append("- Source: none")
    if verification["checks"]:
        for check in verification["checks"]:
            lines.append(
                f"- {check['name']}: {check['status']} "
                f"(returncode: {check['returncode']})"
            )
    else:
        lines.append("- No pack checks configured.")
    if verification["blockers"]:
        lines.extend(["", "## Diagnostics", ""])
        for blocker in verification["blockers"]:
            lines.append(f"- {blocker}")
    lines.append("")
    return "\n".join(lines)


def update_loop_diagnostic(run_dir: Path, verification: dict[str, Any]) -> None:
    loop_path = run_dir / "loop.md"
    if not loop_path.exists():
        return
    text = loop_path.read_text(encoding="utf-8")
    marker = "# Current Attempt"
    diagnostic = (
        "# Current Attempt\n\n"
        f"Verification status: {verification['status']}.\n"
        f"Patch: {verification['patch'].get('path') or 'none'}.\n"
        f"Risk: {verification['risk'].get('risk') or 'unknown'}.\n"
    )
    if verification["blockers"]:
        diagnostic += (
            "Blockers:\n"
            + "\n".join(f"- {item}" for item in verification["blockers"])
            + "\n"
        )
    if marker not in text:
        loop_path.write_text(text.rstrip() + "\n\n" + diagnostic, encoding="utf-8")
        return
    before = text.split(marker, 1)[0].rstrip()
    loop_path.write_text(before + "\n\n" + diagnostic, encoding="utf-8")


def dashboard_number_summary(records: list[dict[str, Any]], values: list[object]) -> dict[str, Any]:
    from loopforge.engine import summarize_number_series

    return summarize_number_series(records, values)


def dashboard_attempt_rows(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    from loopforge.engine import attempt_records

    if run is None:
        return []
    rows: list[dict[str, Any]] = []
    for attempt in attempt_records(run):
        rows.append(
            {
                "id": compact_text(attempt.get("id")),
                "adapter": compact_text(attempt.get("adapter") or "unknown"),
                "status": compact_text(attempt.get("status") or "unknown"),
                "summary": compact_text(attempt.get("summary"), limit=160),
                "started_at": compact_text(attempt.get("started_at")),
                "finished_at": compact_text(attempt.get("finished_at")),
                "stdout_path": compact_text(attempt.get("stdout_path")),
                "stderr_path": compact_text(attempt.get("stderr_path")),
            }
        )
    return rows


def dashboard_memory_proposal_rows(memory: dict[str, Any] | None) -> list[dict[str, Any]]:
    from loopforge.engine import read_json

    if memory is None:
        return []
    proposal_path = memory.get("proposal_path")
    if not isinstance(proposal_path, str) or not proposal_path:
        return []
    path = Path(proposal_path)
    if not path.exists():
        return []
    try:
        data = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    proposals = data.get("proposals", [])
    if not isinstance(proposals, list):
        return []
    rows: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        rows.append(
            {
                "id": compact_text(proposal.get("id")),
                "status": compact_text(proposal.get("status") or "unknown"),
                "category": compact_text(proposal.get("category")),
                "source": compact_text(
                    proposal.get("source_path") or proposal.get("source"),
                    limit=160,
                ),
                "text": compact_text(proposal.get("text"), limit=200),
                "rejection_reason": compact_text(proposal.get("rejection_reason"), limit=160),
                "promotion_reason": compact_text(proposal.get("promotion_reason"), limit=160),
            }
        )
    return rows


def dashboard_adapter_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    from loopforge.engine import count_values, summarize_costs

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        adapter = record.get("adapter") if isinstance(record.get("adapter"), dict) else {}
        adapter_id = adapter.get("id") if isinstance(adapter, dict) else None
        key = adapter_id if isinstance(adapter_id, str) and adapter_id else "unknown"
        grouped.setdefault(key, []).append(record)

    groups: list[dict[str, Any]] = []
    for adapter_id in sorted(grouped):
        adapter_records = grouped[adapter_id]
        groups.append(
            {
                "adapter": adapter_id,
                "record_count": len(adapter_records),
                "duration_seconds": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("timing", {}).get("duration_seconds")
                        if isinstance(record.get("timing"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "attempt_count": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("attempts", {}).get("count")
                        if isinstance(record.get("attempts"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "total_tokens": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("tokens", {}).get("total_tokens")
                        if isinstance(record.get("tokens"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "patch_size_bytes": dashboard_number_summary(
                    adapter_records,
                    [
                        record.get("patch", {}).get("size_bytes")
                        if isinstance(record.get("patch"), dict)
                        else None
                        for record in adapter_records
                    ],
                ),
                "cost": summarize_costs(adapter_records),
                "verification_results": count_values(
                    [
                        record.get("verification", {}).get("status")
                        if isinstance(record.get("verification"), dict)
                        else None
                        for record in adapter_records
                    ]
                ),
                "final_dispositions": count_values(
                    [
                        record.get("final_disposition", {}).get("status")
                        if isinstance(record.get("final_disposition"), dict)
                        else None
                        for record in adapter_records
                    ]
                ),
            }
        )
    return {"record_count": len(records), "groups": groups}


def dashboard_average_text(series: object) -> str:
    if not isinstance(series, dict):
        return "unknown"
    average = series.get("average")
    if average is None:
        return "unknown"
    if isinstance(average, float):
        return f"{average:.2f}".rstrip("0").rstrip(".")
    return str(average)


def dashboard_text_lines(snapshot: dict[str, Any]) -> list[str]:
    lines = ["LoopForge dashboard"]
    project = snapshot.get("project", {}) if isinstance(snapshot.get("project"), dict) else {}
    lines.extend(
        [
            f"project: {project.get('name') or 'unknown'}",
            f"initialized: {project.get('initialized')}",
            f"profile: {project.get('profile') or 'none'}",
            "",
            "Run list",
        ]
    )
    runs = snapshot.get("runs", {}) if isinstance(snapshot.get("runs"), dict) else {}
    run_items = runs.get("items", []) if isinstance(runs.get("items"), list) else []
    lines.append(f"run root: {runs.get('run_root') or 'none'}")
    lines.append(f"runs: {runs.get('total', len(run_items))}")
    if run_items:
        for run in run_items[:10]:
            if not isinstance(run, dict):
                continue
            marker = "*" if run.get("current") else "-"
            task = compact_text(run.get("task"), limit=80)
            lines.append(f"{marker} {run.get('run_id')} [{run.get('status')}] {task}")
    else:
        lines.append("- none")

    current = (
        snapshot.get("current_loop", {})
        if isinstance(snapshot.get("current_loop"), dict)
        else {}
    )
    limits = current.get("limits", {}) if isinstance(current.get("limits"), dict) else {}
    lines.extend(
        [
            "",
            "Current loop",
            f"run id: {current.get('run_id') or 'none'}",
            f"task: {compact_text(current.get('task'), limit=120) or 'none'}",
            f"status: {current.get('status') or 'none'}",
            f"pack: {current.get('pack') or 'none'}",
            f"loop contract: {current.get('loop_contract_status') or 'none'}",
            f"success checks: {len(current.get('success_checks') or [])}",
            (
                "limits: "
                f"max_attempts={limits.get('max_attempts')}, "
                f"timeout_seconds={limits.get('timeout_seconds')}"
            ),
            f"next step: {current.get('next_step') or 'none'}",
            "",
            "Attempts",
        ]
    )
    attempts = snapshot.get("attempts", {}) if isinstance(snapshot.get("attempts"), dict) else {}
    attempt_items = attempts.get("items", []) if isinstance(attempts.get("items"), list) else []
    lines.append(
        f"attempts: {attempts.get('count', 0)}/"
        f"{attempts.get('max_attempts') or 'unknown'}"
    )
    if attempt_items:
        for attempt in attempt_items[:10]:
            if isinstance(attempt, dict):
                lines.append(
                    "- "
                    f"{attempt.get('id')}: {attempt.get('adapter')} "
                    f"[{attempt.get('status')}] {attempt.get('summary')}"
                )
    else:
        lines.append("- none")

    verification = (
        snapshot.get("verification", {})
        if isinstance(snapshot.get("verification"), dict)
        else {}
    )
    lines.extend(
        [
            "",
            "Verification",
            f"status: {verification.get('status') or 'not run'}",
            f"risk: {verification.get('risk') or 'unknown'}",
            (
                "checks: "
                f"{verification.get('checks_passed') or 0}/"
                f"{verification.get('checks_total') or 0}"
            ),
            f"patch size bytes: {verification.get('patch_size_bytes') or 'unknown'}",
            "",
            "Memory proposals",
        ]
    )
    memory = snapshot.get("memory", {}) if isinstance(snapshot.get("memory"), dict) else {}
    proposals = (
        memory.get("proposal_rows", []) if isinstance(memory.get("proposal_rows"), list) else []
    )
    lines.append(f"durable items: {memory.get('durable_items') or 0}")
    lines.append(
        "proposals: "
        f"{memory.get('pending', 0)} pending, "
        f"{memory.get('promoted', 0)} promoted, "
        f"{memory.get('rejected', 0)} rejected"
    )
    if proposals:
        for proposal in proposals[:10]:
            if isinstance(proposal, dict):
                lines.append(
                    "- "
                    f"{proposal.get('id')}: {proposal.get('status')} "
                    f"{proposal.get('category')} - {proposal.get('text')}"
                )
    else:
        lines.append("- none")

    comparison = (
        snapshot.get("adapter_comparison", {})
        if isinstance(snapshot.get("adapter_comparison"), dict)
        else {}
    )
    groups = comparison.get("groups", []) if isinstance(comparison.get("groups"), list) else []
    lines.extend(["", "Adapter comparison", f"records: {comparison.get('record_count', 0)}"])
    if groups:
        for group in groups:
            if not isinstance(group, dict):
                continue
            cost = group.get("cost", {}) if isinstance(group.get("cost"), dict) else {}
            lines.append(
                "- "
                f"{group.get('adapter')}: records={group.get('record_count')}, "
                f"duration_avg={dashboard_average_text(group.get('duration_seconds'))}, "
                f"attempts_avg={dashboard_average_text(group.get('attempt_count'))}, "
                f"tokens_avg={dashboard_average_text(group.get('total_tokens'))}, "
                f"patch_avg={dashboard_average_text(group.get('patch_size_bytes'))}, "
                f"cost_known={cost.get('known_count', 0)}"
            )
    else:
        lines.append("- none")

    action = (
        snapshot.get("next_human_action", {})
        if isinstance(snapshot.get("next_human_action"), dict)
        else {}
    )
    lines.extend(["", "Next human action"])
    if action.get("available"):
        lines.extend(
            [
                f"id: {action.get('id')}",
                f"label: {action.get('label')}",
                f"command: {action.get('command')}",
                f"do command: {action.get('do_command')}",
                f"requires confirmation: {action.get('requires_confirmation')}",
                f"why: {action.get('why')}",
            ]
        )
    else:
        lines.append("- none")

    blockers = snapshot.get("blockers", [])
    lines.extend(["", "Blockers"])
    if isinstance(blockers, list) and blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")
    return lines
