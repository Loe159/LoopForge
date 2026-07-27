"""Native run artifact inspection and markdown parsing helpers."""

from __future__ import annotations

import re
from typing import Any


NATIVE_RUN_FILES = (
    "run.json",
    "task.md",
    "loop.md",
    "research.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "review.md",
    "memory.md",
    "scratch.md",
    "exchange.json",
)

NATIVE_RUN_DIRECTORIES = (
    "attempts",
    "artifacts",
    "metrics",
)

REQUIRED_LOOP_SECTIONS = (
    "Objective",
    "Scope",
    "Inputs",
    "Selected Project Pack",
    "Selected Skills",
    "Allowed Tools",
    "Success Checks",
    "Limits",
    "Stagnation Rule",
    "Rollback Strategy",
    "Human Review Conditions",
)


def native_artifact_state(run_dir: Path) -> dict[str, Any]:
    missing_files = [name for name in NATIVE_RUN_FILES if not (run_dir / name).is_file()]
    missing_directories = [
        name for name in NATIVE_RUN_DIRECTORIES if not (run_dir / name).is_dir()
    ]
    total = len(NATIVE_RUN_FILES) + len(NATIVE_RUN_DIRECTORIES)
    present = total - len(missing_files) - len(missing_directories)
    return {
        "status": "complete" if present == total else "incomplete",
        "present": present,
        "total": total,
        "missing_files": missing_files,
        "missing_directories": missing_directories,
    }


def parse_frontmatter(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        heading = re.match(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", line)
        if heading:
            current = heading.group(1).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def section_text(sections: dict[str, list[str]], name: str) -> str:
    return "\n".join(sections.get(name, [])).strip()


def bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if item and not item.lower().startswith("none recorded"):
            items.append(item)
    return items


def loop_contract_state(loop_path: Path) -> dict[str, Any]:
    if not loop_path.exists():
        return {
            "status": "missing",
            "path": str(loop_path),
            "missing_fields": list(REQUIRED_LOOP_SECTIONS),
            "success_checks": [],
            "allowed_tools": [],
            "subjective": False,
            "rubric": "",
            "errors": [f"loop contract not found: {loop_path}"],
        }

    markdown = loop_path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(markdown)
    sections = markdown_sections(markdown)
    missing_fields = [
        name for name in REQUIRED_LOOP_SECTIONS if not section_text(sections, name)
    ]
    success_checks = bullet_items(section_text(sections, "Success Checks"))
    allowed_tools = bullet_items(section_text(sections, "Allowed Tools"))
    rubric = section_text(sections, "Subjective Rubric")
    if rubric.lower().startswith("none recorded"):
        rubric = ""
    limits = parse_loop_limits(section_text(sections, "Limits"))
    subjective = frontmatter.get("subjective", "false").lower() == "true"
    status = "valid"
    errors: list[str] = []
    if missing_fields:
        status = "invalid"
        errors.append(f"missing required contract fields: {', '.join(missing_fields)}")
    return {
        "status": status,
        "path": str(loop_path),
        "missing_fields": missing_fields,
        "success_checks": success_checks,
        "allowed_tools": allowed_tools,
        "subjective": subjective,
        "rubric": rubric,
        "limits": limits,
        "errors": errors,
    }


def text_matches_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def parse_loop_limits(text: str) -> dict[str, int | None]:
    limits: dict[str, int | None] = {
        "max_attempts": None,
        "timeout_seconds": None,
    }
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("- max attempts:"):
            limits["max_attempts"] = positive_int_after_colon(stripped)
        elif lowered.startswith("- timeout seconds:"):
            limits["timeout_seconds"] = positive_int_after_colon(stripped)
    return limits


def positive_int_after_colon(text: str) -> int | None:
    _, _, value = text.partition(":")
    value = value.strip()
    if not value.isdigit():
        return None
    parsed = int(value)
    if parsed < 1:
        return None
    return parsed
