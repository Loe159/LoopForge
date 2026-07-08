"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
import hashlib
import importlib.util
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

CONFIG_DIR = ".loopforge"
CONFIG_FILE = "config.json"
PROJECT_MEMORY_FILE = "memory.md"
DEFAULT_PROFILE = "supervised"
DEFAULT_PACK = "generic-code"
DEFAULT_ADAPTER = "codex"
READY_FOR_VERIFICATION = "ready_for_verification"
ADAPTER_BLOCKED = "adapter_blocked"
LOOP_CONTRACT_DRAFT = "loop_contract_draft"
LOOP_CONTRACT_READY = "loop_contract_ready"
VERIFIED = "verified"
VERIFICATION_FAILED = "verification_failed"
SYNTHETIC_LEGACY_BASE_COMMIT = "0" * 40
METRICS_RECORD_FILE = "record.json"

SUPPORTED_ADAPTERS = (
    "codex",
    "claude-code",
    "aider",
    "opencode",
    "mini-swe-agent",
    "local-adapter-fixture",
)

SUPPORTED_PROFILES = (
    "assist",
    "supervised",
    "autonomous",
    "strict",
)

PROFILE_POLICIES: dict[str, dict[str, Any]] = {
    "assist": {
        "summary": (
            "read-only assistance plus LoopForge bookkeeping; adapter execution, "
            "verification artifacts, and durable memory promotion are blocked"
        ),
        "mutation": "blocked for workspace-changing transitions",
        "attempts": "disabled",
        "memory": "proposals only; promotion blocked",
    },
    "supervised": {
        "summary": "bounded mutation is allowed; major transitions are surfaced for review",
        "mutation": "allowed for bounded attempts and verification",
        "attempts": "one bounded adapter attempt at a time",
        "memory": "promotion requires approval or a pack rule",
    },
    "autonomous": {
        "summary": (
            "bounded attempts may proceed only with objective checks and no stop-condition risk"
        ),
        "mutation": "allowed while checks are objective and stop conditions are absent",
        "attempts": "bounded by contract limits and stagnation checks",
        "memory": "promotion still requires approval or a pack rule",
    },
    "strict": {
        "summary": "explicit confirmation is required before mutation or memory promotion",
        "mutation": "requires --confirm for adapter execution and verification",
        "attempts": "requires explicit confirmation before each adapter attempt",
        "memory": "approval plus --confirm is required for promotion",
    },
}

AGENT_COMMANDS = {
    "codex": "codex",
    "claude-code": "claude",
    "aider": "aider",
    "opencode": "opencode",
    "mini-swe-agent": "mini-swe-agent",
}

CONFIG_KEYS = (
    "project_name",
    "profile",
    "run_root",
    "current_run_id",
    "default_adapter",
    "default_adapter_args",
    "created_at",
    "updated_at",
)

NATIVE_RUN_FILES = (
    "run.json",
    "task.md",
    "loop.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "memory.md",
    "scratch.md",
    "exchange.json",
)

NATIVE_RUN_DIRECTORIES = (
    "attempts",
    "artifacts",
    "metrics",
)

LEGACY_ARTIFACT_NAMES = (
    "task.md",
    "research.md",
    "plan.md",
    "progress.md",
    "verification.md",
    "review.md",
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

DEFAULT_ALLOWED_TOOLS = (
    "Read project files and LoopForge run artifacts.",
    "Write bounded changes inside the target workspace.",
    "Run local deterministic verification commands.",
)

SUBJECTIVE_TASK_MARKERS = (
    "better",
    "copy",
    "design",
    "draft",
    "evaluate",
    "improve",
    "polish",
    "rewrite",
    "review",
    "summarize",
    "ux",
)

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

SECRET_MARKERS = (
    "api key",
    "apikey",
    "authorization:",
    "bearer ",
    "client secret",
    "password",
    "private key",
    "secret",
    "ssh-rsa",
    "token",
)

UNTRUSTED_TEXT_MARKERS = (
    "raw issue",
    "issue body",
    "raw comment",
    "comment body",
    "untrusted body",
)

AUTONOMOUS_STOP_MARKERS: dict[str, tuple[str, ...]] = {
    "publication": (
        "deploy",
        "publish",
        "release",
        "send email",
        "open pull request",
        "create pull request",
        "push",
        "upload",
    ),
    "deletion": (
        "delete",
        "destroy",
        "drop database",
        "remove files",
        "rm -rf",
        "wipe",
    ),
    "secrets": (
        "api key",
        "credential",
        "expose secret",
        "password",
        "private key",
        "secret",
        "token",
    ),
    "money": (
        "billing",
        "buy",
        "charge",
        "pay ",
        "purchase",
        "spend money",
    ),
    "external side effects": (
        "call external",
        "cloud",
        "external api",
        "http://",
        "https://",
        "network",
        "production",
        "remote side effect",
        "webhook",
    ),
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
class InitResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any]
    created: bool
    repaired: bool


@dataclass(frozen=True)
class RunResult:
    project_dir: Path
    config_path: Path
    run_dir: Path
    run_json_path: Path
    config: dict[str, Any]
    run: dict[str, Any]


@dataclass(frozen=True)
class StatusResult:
    project_dir: Path
    config_path: Path
    initialized: bool
    config: dict[str, Any] | None
    run_dir: Path | None
    run_json_path: Path | None
    run: dict[str, Any] | None
    native_artifacts: dict[str, Any] | None
    legacy_artifacts: dict[str, Any] | None
    loop_contract: dict[str, Any] | None
    verification: dict[str, Any] | None
    memory: dict[str, Any] | None
    next_step: str
    blockers: list[str]


@dataclass(frozen=True)
class ContinueResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    contract: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]
    attempt: dict[str, Any] | None = None


@dataclass(frozen=True)
class VerifyResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]
    verification: dict[str, Any] | None = None


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


@dataclass(frozen=True)
class MetricsRecordResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    record_path: Path | None
    record: dict[str, Any] | None
    blockers: list[str]


@dataclass(frozen=True)
class MetricsSummaryResult:
    project_dir: Path
    run_root: Path | None
    ok: bool
    message: str
    records: list[dict[str, Any]]
    summary: dict[str, Any]
    blockers: list[str]


@dataclass(frozen=True)
class DashboardResult:
    project_dir: Path
    ok: bool
    snapshot: dict[str, Any]
    blockers: list[str]


@dataclass(frozen=True)
class RunListResult:
    project_dir: Path
    run_root: Path | None
    initialized: bool
    config: dict[str, Any] | None
    current_run_id: str | None
    runs: list[dict[str, Any]]
    blockers: list[str]


@dataclass(frozen=True)
class ResumeRunResult:
    project_dir: Path
    run_dir: Path | None
    run: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class CompactContextResult:
    project_dir: Path
    run_dir: Path | None
    path: Path | None
    ok: bool
    message: str
    summary: str
    blockers: list[str]


@dataclass(frozen=True)
class ConfigUpdateResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class GuidedAction:
    id: str
    label: str
    command: str
    risk: str
    requires_confirmation: bool
    why: str


@dataclass(frozen=True)
class GuidanceResult:
    project_dir: Path
    state: str
    summary: str
    priority: str
    diagnostics: list[str]
    recommended_actions: list[GuidedAction]
    blocked_reasons: list[str]
    evidence: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_config_dir(project_dir: Path) -> Path:
    return project_dir / CONFIG_DIR


def project_config_path(project_dir: Path) -> Path:
    return project_config_dir(project_dir) / CONFIG_FILE


def project_name(project_dir: Path) -> str:
    return project_dir.resolve().name or "project"


def loopforge_home(home: Path | None = None) -> Path:
    if home is not None:
        return home / "LoopForge"
    configured_home = os.environ.get("LOOPFORGE_HOME")
    if configured_home:
        return Path(configured_home).expanduser()
    return Path.home() / "LoopForge"


def default_run_root(project_dir: Path, home: Path | None = None) -> Path:
    return loopforge_home(home=home) / "runs" / project_name(project_dir)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()


def ensure_templates(project_dir: Path) -> None:
    root = project_config_dir(project_dir)
    for relative_name, contents in TEMPLATES.items():
        destination = root / relative_name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
    for directory_name in ("packs", "skills"):
        (root / directory_name).mkdir(parents=True, exist_ok=True)


def read_project_template(project_dir: Path, relative_name: str) -> str:
    template_path = project_config_dir(project_dir) / "templates" / relative_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    fallback = TEMPLATES.get(f"templates/{relative_name}")
    if fallback is None:
        raise KeyError(f"unknown template: {relative_name}")
    return fallback


def durable_memory_path(project_dir: Path) -> Path:
    return project_config_dir(project_dir) / PROJECT_MEMORY_FILE


def ensure_project_memory(project_dir: Path) -> Path:
    path = durable_memory_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(read_project_template(project_dir, "memory.md"), encoding="utf-8")
    return path


def durable_memory_items(project_dir: Path) -> dict[str, list[str]]:
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


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def legacy_templates_dir() -> Path:
    return repository_root() / ".agent" / "templates"


def legacy_artifact_validator() -> Path:
    return repository_root() / ".agent" / "checks" / "validate_artifacts.py"


def local_implementation_adapter() -> Path:
    return repository_root() / ".agent" / "adapters" / "local_implementation_adapter.py"


def imported_check(name: str) -> Path:
    return repository_root() / ".agent" / "checks" / name


def default_diff_policy() -> Path:
    return repository_root() / ".agent" / "policies" / "diff-policy.json"


def default_risk_policy() -> Path:
    return repository_root() / ".agent" / "policies" / "risk-rules.json"


def pack_roots(project_dir: Path) -> list[Path]:
    return [
        project_dir / CONFIG_DIR / "packs",
        repository_root() / CONFIG_DIR / "packs",
    ]


def pack_file_candidates(project_dir: Path, pack: str, file_name: str) -> list[Path]:
    return [
        project_dir / CONFIG_DIR / "packs" / pack / file_name,
        project_dir / CONFIG_DIR / "packs" / f"{pack}.{file_name}",
        repository_root() / CONFIG_DIR / "packs" / pack / file_name,
        repository_root() / CONFIG_DIR / "packs" / f"{pack}.{file_name}",
    ]


def normalize_unique_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalized.append(stripped)
    return normalized


def discover_pack_contracts(project_dir: Path) -> list[dict[str, Any]]:
    contracts_by_name: dict[str, dict[str, Any]] = {}
    for root in reversed(pack_roots(project_dir)):
        if not root.exists():
            continue
        for path in sorted(root.glob("*/pack.json")):
            try:
                contract = load_pack_contract_from_path(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            contracts_by_name[str(contract["name"])] = contract
    return sorted(contracts_by_name.values(), key=lambda item: str(item["name"]))


def load_pack_contract_from_path(path: Path) -> dict[str, Any]:
    data = read_json(path)
    name = str(data.get("name") or path.parent.name).strip()
    if not name:
        raise ValueError(f"{path} must define a pack name")
    version = data.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"{path} version must be a positive integer")
    detection = data.get("detection", {})
    if not isinstance(detection, dict):
        raise ValueError(f"{path} detection must be an object")
    skills = data.get("skills", [])
    if not isinstance(skills, list) or not all(isinstance(skill, str) for skill in skills):
        raise ValueError(f"{path} skills must be a list of strings")
    priority = data.get("priority", 0)
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise ValueError(f"{path} priority must be an integer")
    return {
        "name": name,
        "version": version,
        "description": str(data.get("description") or "").strip(),
        "priority": priority,
        "source": str(path),
        "root": str(path.parent),
        "detection": detection,
        "skills": normalize_unique_strings(skills),
        "skill_file": str(path.parent / str(data.get("skill_file") or "SKILL.md")),
        "checks_file": str(path.parent / str(data.get("checks_file") or "checks.json")),
        "protected_paths_file": str(
            path.parent / str(data.get("protected_paths_file") or "protected-paths.json")
        ),
        "memory_rules_file": str(
            path.parent / str(data.get("memory_rules_file") or "memory-rules.md")
        ),
        "memory": data.get("memory", {}) if isinstance(data.get("memory", {}), dict) else {},
    }


def load_pack_contract(project_dir: Path, pack: str) -> dict[str, Any]:
    for path in pack_file_candidates(project_dir, pack, "pack.json"):
        if path.exists():
            return load_pack_contract_from_path(path)
    raise ValueError(f"project pack not found: {pack}")


def detection_string_list(detection: dict[str, Any], key: str) -> list[str]:
    value = detection.get(key, [])
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def project_path_exists(project_dir: Path, relative_name: str) -> bool:
    candidate = project_dir / relative_name
    return candidate.exists()


def project_glob_matches(project_dir: Path, pattern: str) -> bool:
    if not any(character in pattern for character in "*?["):
        return project_path_exists(project_dir, pattern)
    try:
        return any(path.exists() for path in project_dir.glob(pattern))
    except ValueError:
        return False


def pack_detection_score(project_dir: Path, contract: dict[str, Any]) -> int:
    detection = contract.get("detection", {})
    if not isinstance(detection, dict):
        return 0
    all_files = detection_string_list(detection, "all_files")
    if all_files and not all(project_path_exists(project_dir, name) for name in all_files):
        return 0
    all_dirs = detection_string_list(detection, "all_dirs")
    if all_dirs and not all((project_dir / name).is_dir() for name in all_dirs):
        return 0

    score = 0
    files_any = detection_string_list(detection, "files_any")
    dirs_any = detection_string_list(detection, "dirs_any")
    paths_any = detection_string_list(detection, "paths_any")
    score += sum(20 for name in files_any if project_path_exists(project_dir, name))
    score += sum(20 for name in dirs_any if (project_dir / name).is_dir())
    score += sum(10 for pattern in paths_any if project_glob_matches(project_dir, pattern))
    if score <= 0:
        return 0
    score += int(contract.get("priority", 0))
    return score


def detect_project_pack(project_dir: Path) -> dict[str, Any]:
    contracts = discover_pack_contracts(project_dir)
    best: tuple[int, dict[str, Any]] | None = None
    for contract in contracts:
        if contract["name"] == DEFAULT_PACK:
            continue
        score = pack_detection_score(project_dir, contract)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, contract)
    if best is not None:
        detected = dict(best[1])
        detected["detection_score"] = best[0]
        detected["detected"] = True
        return detected
    try:
        fallback = load_pack_contract(project_dir, DEFAULT_PACK)
    except ValueError:
        fallback = {
            "name": DEFAULT_PACK,
            "version": 1,
            "description": "Fallback generic code pack.",
            "priority": 0,
            "source": None,
            "root": None,
            "detection": {},
            "skills": [],
            "skill_file": None,
            "checks_file": None,
            "protected_paths_file": None,
            "memory_rules_file": None,
            "memory": {},
        }
    fallback["detection_score"] = 0
    fallback["detected"] = True
    return fallback


def pack_skill_entries(contract: dict[str, Any]) -> list[str]:
    skills = contract.get("skills", [])
    values = skills if isinstance(skills, list) else []
    skill_file = contract.get("skill_file")
    if isinstance(skill_file, str) and Path(skill_file).exists():
        values = [*values, f"pack:{contract['name']}:SKILL.md"]
    return normalize_unique_strings([str(value) for value in values])


def isolated_process_module() -> Any:
    path = repository_root() / ".agent" / "checks" / "isolated_process.py"
    spec = importlib.util.spec_from_file_location("loopforge_imported_isolated_process", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load isolated process helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_windows_app_execution_alias(path: Path) -> bool:
    normalized = str(path).replace("/", "\\").upper()
    return "\\APPDATA\\LOCAL\\MICROSOFT\\WINDOWSAPPS\\" in normalized


def usable_python_executable() -> str:
    candidates: list[str | None] = [
        os.environ.get("LOOPFORGE_PYTHON"),
        getattr(sys, "_base_executable", None),
        sys.executable,
        shutil.which("python"),
        shutil.which("python3"),
        shutil.which("py"),
        str(
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "python"
            / "python.exe"
        ),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            resolved = shutil.which(candidate)
            if resolved is None:
                continue
            path = Path(resolved)
        if path.is_file() and not is_windows_app_execution_alias(path):
            return str(path)
    raise RuntimeError(
        "no usable Python executable found for isolated adapter execution; "
        "set LOOPFORGE_PYTHON to a real python.exe outside WindowsApps."
    )


def legacy_issue_for_task(task_id: str) -> int:
    digits = "".join(character for character in task_id if character.isdigit())
    if digits:
        return int(digits[:12])
    return 1


def render_legacy_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def legacy_template_text(name: str) -> str:
    path = legacy_templates_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"legacy artifact template not found: {path}")
    return path.read_text(encoding="utf-8")


def create_legacy_artifacts(
    legacy_dir: Path,
    *,
    task: str,
    issue: int,
    base_commit: str,
) -> None:
    legacy_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "issue": str(issue),
        "base_commit": base_commit,
        "risk": "low",
        "goal": task,
        "expected_behavior": "LoopForge records the task without requiring GitHub.",
        "acceptance_criteria": "The native run exists and the legacy artifacts validate.",
        "constraints": "Keep this artifact set for imported validator compatibility only.",
        "out_of_scope": "Publishing, GitHub issue ingestion, or adapter execution.",
        "scope": "Compatibility scaffold for the imported portable artifact contract.",
        "current_state": "No separate research is required for run initialization.",
        "evidence": "Native run metadata is stored in run.json.",
        "risks_and_unknowns": "The legacy issue value is a generated compatibility mapping.",
        "rejected_approaches": "Do not make GitHub issue IDs mandatory for native runs.",
        "suggested_verification": "Run the imported artifact validator against this directory.",
        "overview": "Create a product-native LoopForge run with a legacy validation mirror.",
        "preconditions": "LoopForge project configuration exists.",
        "implementation_steps": (
            "Create native run files, create directories, and write legacy artifacts."
        ),
        "files_in_scope": "The external run directory.",
        "verification": "Validate the legacy artifact directory with validate_artifacts.py.",
        "stop_conditions": "Stop before external side effects or destructive filesystem actions.",
        "completed": "The run has been initialized.",
        "remaining": "No adapter attempts have run yet.",
        "decisions": "Use task_id natively and generated numeric issue only for legacy tools.",
        "blockers": "None.",
        "next_step": "Inspect run.json and choose the next bounded action.",
        "candidate": "No implementation candidate exists yet.",
        "deterministic_checks": "Legacy artifact contract validation.",
        "policy_result": "Not evaluated yet.",
        "risk_classification": "Low for initialization scaffold.",
        "residual_risks": "Legacy artifacts are compatibility metadata, not publication authority.",
        "findings": "No review has run yet.",
        "plan_conformance": "No approved plan exists yet.",
        "test_coverage": "Initial CLI tests cover run creation.",
        "recommendation": "Continue with LoopForge-native planning.",
    }
    statuses = {
        "task.md": "approved",
        "research.md": "not_required",
        "plan.md": "awaiting_approval",
        "progress.md": "not_started",
        "verification.md": "pending",
        "review.md": "pending",
    }
    for name in LEGACY_ARTIFACT_NAMES:
        text = render_legacy_template(legacy_template_text(name), values)
        text = text.replace(
            {
                "task.md": "status: awaiting_approval",
                "research.md": "status: pending",
                "plan.md": "status: awaiting_approval",
                "progress.md": "status: not_started",
                "verification.md": "status: pending",
                "review.md": "status: pending",
            }[name],
            f"status: {statuses[name]}",
        )
        (legacy_dir / name).write_text(text, encoding="utf-8")


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
        if line.startswith("# "):
            current = line[2:].strip()
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


def autonomous_stop_reasons(run: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not contract.get("success_checks"):
        reasons.append("autonomous profile requires objective success checks.")
    if contract.get("subjective") and not contract.get("rubric"):
        reasons.append("autonomous profile requires a rubric for subjective work.")

    verification = verification_state(run)
    if isinstance(verification, dict) and verification.get("stagnated"):
        reasons.append("autonomous profile stops after repeated equivalent failure.")
    raw_blockers = run.get("blockers", [])
    blockers = raw_blockers if isinstance(raw_blockers, list) else []
    for blocker in blockers:
        if "stagnation:" in str(blocker).lower():
            append_unique(reasons, "autonomous profile stops after repeated equivalent failure.")

    scanned_text = "\n".join(
        [
            str(run.get("task") or ""),
            *[str(item) for item in contract.get("allowed_tools", []) if item],
        ]
    )
    for category, markers in AUTONOMOUS_STOP_MARKERS.items():
        if text_matches_any_marker(scanned_text, markers):
            reasons.append(
                f"autonomous profile stops before {category}; human review is required."
            )
    return reasons


def adapter_result_stop_reasons(result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if result.get("publication_requested"):
        reasons.append("adapter requested publication; human review is required.")
    if result.get("network_requested"):
        reasons.append("adapter requested network or external side effects; human review is required.")
    summary = str(result.get("summary") or "")
    for category, markers in AUTONOMOUS_STOP_MARKERS.items():
        if text_matches_any_marker(summary, markers):
            reasons.append(
                f"adapter result mentions {category}; human review is required."
            )
    return reasons


def profile_transition_blockers(
    *,
    profile: object,
    action: str,
    confirmed: bool = False,
    run: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    normalized = normalize_profile(profile)
    if normalized == "assist" and action in {
        "adapter_attempt",
        "verification",
        "memory_promotion",
    }:
        return [
            f"assist profile blocks {action.replace('_', ' ')}; switch profile or review manually."
        ]
    if normalized == "strict" and action in {
        "adapter_attempt",
        "verification",
        "memory_promotion",
    } and not confirmed:
        return [
            f"strict profile requires --confirm before {action.replace('_', ' ')}."
        ]
    if normalized == "autonomous" and run is not None and contract is not None:
        if action == "adapter_attempt":
            return autonomous_stop_reasons(run, contract)
        if action == "verification":
            verification = verification_state(run)
            if isinstance(verification, dict) and verification.get("stagnated"):
                return ["autonomous profile stops after repeated equivalent failure."]
    return []


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


def legacy_artifact_state(run: dict[str, Any]) -> dict[str, Any]:
    legacy = run.get("legacy", {})
    if not isinstance(legacy, dict):
        legacy = {}
    artifact_dir_text = legacy.get("artifact_dir")
    if not isinstance(artifact_dir_text, str) or not artifact_dir_text:
        return {
            "status": "missing",
            "artifact_dir": None,
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": ["run.json does not declare legacy.artifact_dir"],
        }

    artifact_dir = Path(artifact_dir_text).expanduser()
    missing = [name for name in LEGACY_ARTIFACT_NAMES if not (artifact_dir / name).is_file()]
    if missing:
        return {
            "status": "missing",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [f"missing legacy artifacts: {', '.join(missing)}"],
        }

    validator = legacy_artifact_validator()
    if not validator.exists():
        return {
            "status": "unchecked",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [f"validator not found: {validator}"],
        }

    try:
        result = subprocess.run(
            [sys.executable, str(validator), "--run", str(artifact_dir), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "status": "unchecked",
            "artifact_dir": str(artifact_dir),
            "issue": legacy.get("issue"),
            "base_commit": legacy.get("base_commit"),
            "errors": [str(error)],
        }

    try:
        validator_result = json.loads(result.stdout)
    except json.JSONDecodeError:
        validator_result = {"errors": [{"message": result.stderr.strip() or result.stdout.strip()}]}

    errors = validator_result.get("errors", [])
    return {
        "status": "valid" if result.returncode == 0 else "invalid",
        "artifact_dir": str(artifact_dir),
        "issue": legacy.get("issue"),
        "base_commit": legacy.get("base_commit"),
        "errors": errors if isinstance(errors, list) else [],
    }


def verification_state(run: dict[str, Any]) -> dict[str, Any] | None:
    verification = run.get("verification")
    return verification if isinstance(verification, dict) else None


def parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def duration_seconds(started_at: object, finished_at: object) -> int | None:
    started = parse_utc_timestamp(started_at)
    finished = parse_utc_timestamp(finished_at)
    if started is None or finished is None:
        return None
    seconds = int((finished - started).total_seconds())
    if seconds < 0:
        return None
    return seconds


def new_config(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> dict[str, Any]:
    now = utc_now()
    normalized_profile = normalize_profile(profile)
    return {
        "project_name": project_name(project_dir),
        "profile": normalized_profile,
        "run_root": str(default_run_root(project_dir, home=home)),
        "current_run_id": None,
        "default_adapter": DEFAULT_ADAPTER,
        "default_adapter_args": [],
        "created_at": now,
        "updated_at": now,
    }


def normalize_config(
    project_dir: Path,
    existing: dict[str, Any],
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    config = dict(existing)
    now = utc_now()
    if "created_at" not in config:
        config["created_at"] = now
    if "current_run_id" not in config:
        config["current_run_id"] = None
    if config.get("default_adapter") not in SUPPORTED_ADAPTERS:
        config["default_adapter"] = DEFAULT_ADAPTER
    if not isinstance(config.get("default_adapter_args"), list):
        config["default_adapter_args"] = []
    else:
        config["default_adapter_args"] = [
            str(value) for value in config["default_adapter_args"]
        ]
    if "project_name" not in config:
        config["project_name"] = project_name(project_dir)
    normalized_profile = normalize_profile(config.get("profile", profile))
    if config.get("profile") != normalized_profile:
        config["profile"] = normalized_profile
    if "run_root" not in config:
        config["run_root"] = str(default_run_root(project_dir, home=home))
    if "updated_at" not in config:
        config["updated_at"] = now

    repaired = any(config.get(key) != existing.get(key) for key in CONFIG_KEYS)
    if repaired:
        config["updated_at"] = now
    return config, repaired


def initialize_project(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> InitResult:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_templates(project_dir)
    ensure_project_memory(project_dir)

    if config_path.exists():
        config, repaired = normalize_config(
            project_dir,
            read_json(config_path),
            profile=profile,
            home=home,
        )
        if repaired:
            write_json_atomic(config_path, config)
        return InitResult(
            project_dir=project_dir,
            config_path=config_path,
            config=config,
            created=False,
            repaired=repaired,
        )

    config = new_config(project_dir, profile=profile, home=home)
    write_json_atomic(config_path, config)
    return InitResult(
        project_dir=project_dir,
        config_path=config_path,
        config=config,
        created=True,
        repaired=False,
    )


def update_project_config(project_dir: Path, updates: dict[str, Any]) -> ConfigUpdateResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge config update failed.",
            blockers=[status.next_step],
        )

    config = dict(status.config)
    for key, value in updates.items():
        config[key] = value
    config["updated_at"] = utc_now()
    normalized, _ = normalize_config(status.project_dir, config)
    write_json_atomic(status.config_path, normalized)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=normalized,
        ok=True,
        message=f"LoopForge config updated: {status.config_path}",
        blockers=[],
    )


def set_default_adapter(
    project_dir: Path,
    adapter: str,
    adapter_args: list[str] | None = None,
) -> ConfigUpdateResult:
    if adapter not in SUPPORTED_ADAPTERS:
        return ConfigUpdateResult(
            project_dir=project_dir.resolve(),
            config_path=project_config_path(project_dir.resolve()),
            config=None,
            ok=False,
            message="LoopForge adapter update failed.",
            blockers=[f"unsupported adapter: {adapter}"],
        )
    updates: dict[str, Any] = {"default_adapter": adapter}
    if adapter_args is not None:
        updates["default_adapter_args"] = [str(value) for value in adapter_args]
    return update_project_config(project_dir, updates)


def archive_current_run(project_dir: Path) -> ConfigUpdateResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    updated_run = dict(status.run)
    updated_run["archived"] = True
    updated_run["archived_at"] = utc_now()
    write_json_atomic(status.run_json_path or (status.run_dir / "run.json"), updated_run)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=status.config,
        ok=True,
        message=f"LoopForge archived run: {updated_run.get('run_id')}",
        blockers=[],
    )


def detect_git_base_commit(project_dir: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def task_looks_subjective(task: str) -> bool:
    lowered = task.lower()
    return any(marker in lowered for marker in SUBJECTIVE_TASK_MARKERS)


def normalize_nonempty_strings(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return [value.strip() for value in values if value.strip()]


def normalize_profile(profile: object) -> str:
    value = str(profile or "").strip().lower()
    if value in SUPPORTED_PROFILES:
        return value
    return DEFAULT_PROFILE


def profile_policy(profile: object) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    policy = dict(PROFILE_POLICIES[normalized])
    policy["name"] = normalized
    return policy


def profile_permission_lines(profile: object) -> list[str]:
    policy = profile_policy(profile)
    return [
        f"profile allows: {policy['summary']}",
        f"profile mutation: {policy['mutation']}",
        f"profile attempts: {policy['attempts']}",
        f"profile memory: {policy['memory']}",
    ]


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def loop_contract_status(
    *,
    success_checks: list[str],
    profile: str,
    subjective: bool,
    subjective_rubric: str,
) -> str:
    if not success_checks:
        return LOOP_CONTRACT_DRAFT
    if profile == "autonomous" and subjective and not subjective_rubric.strip():
        return LOOP_CONTRACT_DRAFT
    return LOOP_CONTRACT_READY


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


def memory_artifact_dir(run_dir: Path) -> Path:
    return run_dir / "artifacts" / "memory"


def memory_proposal_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.json"


def memory_proposal_markdown_path(run_dir: Path) -> Path:
    return memory_artifact_dir(run_dir) / "proposals.md"


def memory_status_from_proposals(run_dir: Path) -> dict[str, int | str | None]:
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
    ensure_project_memory(project_dir)
    items = durable_memory_items(project_dir)
    state: dict[str, Any] = {
        "durable_path": str(durable_memory_path(project_dir)),
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


def memory_rejection_reason(text: str, *, trusted: bool) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in SECRET_MARKERS):
        return "candidate appears to contain a secret or credential marker"
    if any(marker in lowered for marker in UNTRUSTED_TEXT_MARKERS):
        return "candidate appears to contain raw untrusted issue/comment/body text"
    if not trusted:
        return "candidate came from an untrusted exchange message"
    return None


def memory_candidate(
    text: str,
    *,
    source: str,
    source_path: Path | None,
    trusted: bool = True,
) -> dict[str, Any] | None:
    parsed = parse_memory_candidate_text(text, source=source)
    if parsed is None:
        return None
    category, value = parsed
    candidate_id = hashlib.sha256(
        json.dumps(
            {
                "category": category,
                "source": source,
                "text": value,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    reason = memory_rejection_reason(value, trusted=trusted)
    return {
        "id": candidate_id,
        "category": category,
        "text": value,
        "source": source,
        "source_path": str(source_path) if source_path is not None else None,
        "trusted": trusted,
        "status": "rejected" if reason else "pending",
        "rejection_reason": reason,
    }


def scratch_memory_candidates(run_dir: Path) -> list[dict[str, Any]]:
    scratch_path = run_dir / "scratch.md"
    if not scratch_path.exists():
        return []
    markdown = scratch_path.read_text(encoding="utf-8")
    sections = markdown_sections(markdown)
    candidates: list[dict[str, Any]] = []
    for section, lines in sections.items():
        if section == "Discard Candidates":
            continue
        for item in bullet_items("\n".join(lines)):
            candidate = memory_candidate(
                item,
                source=f"scratch:{section}",
                source_path=scratch_path,
                trusted=True,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def exchange_memory_candidates(run_dir: Path) -> list[dict[str, Any]]:
    exchange_path = run_dir / "exchange.json"
    if not exchange_path.exists():
        return []
    try:
        data = read_json(exchange_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        return []
    candidates: list[dict[str, Any]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            continue
        value = message.get("memory_candidate", message.get("promote_to_memory"))
        if not isinstance(value, str):
            continue
        candidate = memory_candidate(
            value,
            source="exchange:messages",
            source_path=exchange_path,
            trusted=message.get("trusted") is True,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def pack_memory_rule_paths(project_dir: Path, pack: str) -> list[Path]:
    return pack_file_candidates(project_dir, pack, "memory-rules.json")


def load_pack_memory_rules(project_dir: Path, pack: str) -> dict[str, Any]:
    for path in pack_memory_rule_paths(project_dir, pack):
        if not path.exists():
            continue
        data = read_json(path)
        rules = data.get("auto_promote", [])
        if not isinstance(rules, list):
            raise ValueError(f"{path} auto_promote must be a list")
        return {"source": str(path), "auto_promote": rules}
    try:
        contract = load_pack_contract(project_dir, pack)
    except ValueError:
        return {"source": None, "auto_promote": []}
    memory = contract.get("memory", {})
    if not isinstance(memory, dict):
        return {"source": None, "auto_promote": []}
    rules = memory.get("auto_promote", [])
    if not isinstance(rules, list):
        raise ValueError(f"{contract.get('source')} memory.auto_promote must be a list")
    return {"source": contract.get("source"), "auto_promote": rules}


def pack_rule_allows_promotion(rules: dict[str, Any], proposal: dict[str, Any]) -> bool:
    raw_rules = rules.get("auto_promote", [])
    if not isinstance(raw_rules, list):
        return False
    for rule in raw_rules:
        if isinstance(rule, str):
            pattern = rule
            category = None
        elif isinstance(rule, dict):
            pattern = rule.get("pattern")
            category = rule.get("category")
        else:
            continue
        if category is not None and str(category) != proposal["category"]:
            continue
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            if re.search(pattern, proposal["text"]):
                return True
        except re.error:
            if pattern in proposal["text"]:
                return True
    return False


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


def promote_memory_candidate(
    project_dir: Path,
    proposal: dict[str, Any],
    *,
    reason: str,
    run_id: str | None,
) -> bool:
    path = ensure_project_memory(project_dir)
    item = str(proposal["text"])
    category = str(proposal["category"])
    changed = append_markdown_bullet(path, category, item)
    if changed:
        source = proposal.get("source_path") or proposal.get("source") or "unknown"
        log_item = (
            f"{utc_now()} | {reason} | run={run_id or 'none'} | "
            f"{category}: {item} | source={source}"
        )
        append_markdown_bullet(path, "Promotion Log", log_item)
    return changed


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


def unique_memory_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["id"])
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        unique.append(candidate)
    return unique


def learn_run(
    project_dir: Path,
    *,
    approve: bool = False,
    notes: list[str] | None = None,
    confirmed: bool = False,
) -> LearnResult:
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
        write_json_atomic(status.run_json_path, updated_run)

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


def describe_next_step(run: dict[str, Any]) -> str:
    status = str(run.get("status", "unknown"))
    blockers = run.get("blockers", [])
    if isinstance(blockers, list) and blockers:
        return "Resolve the listed blockers before continuing the loop."
    if status == LOOP_CONTRACT_DRAFT:
        return "Complete the loop contract, especially success checks, before continuing."
    if status == LOOP_CONTRACT_READY:
        return "Run `loopforge continue --adapter <adapter>` to execute a bounded attempt."
    if status == ADAPTER_BLOCKED:
        return "Inspect the latest attempt artifacts, resolve blockers, then continue again."
    if status == READY_FOR_VERIFICATION:
        return "Run `loopforge verify` to generate the patch and run pack checks."
    if status == VERIFICATION_FAILED:
        return "Inspect verification.md, fix the diagnostic, then run `loopforge verify` again."
    if status == VERIFIED:
        return "Review the verified patch and decide whether to continue, commit, or hand off."
    return "Inspect the run artifacts and decide the next bounded action."


def current_status(project_dir: Path) -> StatusResult:
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=False,
            config=None,
            run_dir=None,
            run_json_path=None,
            run=None,
            native_artifacts=None,
            legacy_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=None,
            next_step="Initialize LoopForge with `loopforge init`.",
            blockers=[],
        )

    config = normalize_config(project_dir, read_json(config_path))[0]
    current_run_id = config.get("current_run_id")
    if not current_run_id:
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=True,
            config=config,
            run_dir=None,
            run_json_path=None,
            run=None,
            native_artifacts=None,
            legacy_artifacts=None,
            loop_contract=None,
            verification=None,
            memory=memory_state(project_dir, None),
            next_step='Create a run with `loopforge run --task "..."`.',
            blockers=[],
        )

    run_dir = Path(str(config["run_root"])).expanduser() / str(current_run_id)
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return StatusResult(
            project_dir=project_dir,
            config_path=config_path,
            initialized=True,
            config=config,
            run_dir=run_dir,
            run_json_path=run_json_path,
            run=None,
            native_artifacts=native_artifact_state(run_dir) if run_dir.exists() else None,
            legacy_artifacts=None,
            loop_contract=loop_contract_state(run_dir / "loop.md") if run_dir.exists() else None,
            verification=None,
            memory=memory_state(project_dir, run_dir) if run_dir.exists() else None,
            next_step="Restore the missing run artifacts or create a new run.",
            blockers=[f"current run metadata not found: {run_json_path}"],
        )

    run = read_json(run_json_path)
    raw_blockers = run.get("blockers", [])
    blockers = [str(blocker) for blocker in raw_blockers] if isinstance(raw_blockers, list) else []
    contract = loop_contract_state(run_dir / "loop.md")
    if contract["status"] != "valid":
        for error in contract["errors"]:
            append_unique(blockers, str(error))
    return StatusResult(
        project_dir=project_dir,
        config_path=config_path,
        initialized=True,
        config=config,
        run_dir=run_dir,
        run_json_path=run_json_path,
        run=run,
        native_artifacts=native_artifact_state(run_dir),
        legacy_artifacts=legacy_artifact_state(run),
        loop_contract=contract,
        verification=verification_state(run),
        memory=memory_state(project_dir, run_dir),
        next_step=describe_next_step(run),
        blockers=blockers,
    )


def guided_action(
    action_id: str,
    label: str,
    command: str,
    *,
    risk: str = "low",
    requires_confirmation: bool = False,
    why: str,
) -> GuidedAction:
    return GuidedAction(
        id=action_id,
        label=label,
        command=command,
        risk=risk,
        requires_confirmation=requires_confirmation,
        why=why,
    )


def current_guidance(project_dir: Path) -> GuidanceResult:
    status = current_status(project_dir)
    actions: list[GuidedAction] = []
    diagnostics: list[str] = []
    evidence: list[str] = [f"project: {status.project_dir}"]
    blocked_reasons = list(status.blockers)

    if not status.initialized:
        return GuidanceResult(
            project_dir=status.project_dir,
            state="not_initialized",
            summary="LoopForge is not initialized for this project yet.",
            priority="setup",
            diagnostics=[
                f"Expected config is missing: {status.config_path}",
                "Create project metadata before starting a run.",
            ],
            recommended_actions=[
                guided_action(
                    "init",
                    "Initialize LoopForge metadata",
                    "loopforge init",
                    why="The project needs .loopforge/config.json before runs can be created.",
                )
            ],
            blocked_reasons=[],
            evidence=evidence,
        )

    assert status.config is not None
    adapter = str(status.config.get("default_adapter") or DEFAULT_ADAPTER)
    adapter_args = status.config.get("default_adapter_args", [])
    if adapter not in SUPPORTED_ADAPTERS:
        diagnostics.append(f"default adapter is invalid: {adapter}")
        blocked_reasons.append(f"unsupported default adapter: {adapter}")
        actions.append(
            guided_action(
                "choose-adapter",
                "Choose a supported adapter",
                f"loopforge shell --command \"/adapter {DEFAULT_ADAPTER}\"",
                why="A valid adapter is required before LoopForge can execute an attempt.",
            )
        )
    else:
        evidence.append(f"default adapter: {adapter}")
        if isinstance(adapter_args, list) and adapter_args:
            evidence.append("default adapter args: " + " ".join(str(arg) for arg in adapter_args))

    if status.run is None:
        actions.append(
            guided_action(
                "create-run",
                "Create a run for the task",
                'loopforge run --task "Describe the task" --success-check "Describe the proof"',
                why="LoopForge needs a concrete task and objective success check to guide work.",
            )
        )
        return GuidanceResult(
            project_dir=status.project_dir,
            state="ready_for_run",
            summary="LoopForge is initialized, but there is no current run.",
            priority="next_task",
            diagnostics=diagnostics or ["No active run is selected."],
            recommended_actions=actions,
            blocked_reasons=blocked_reasons,
            evidence=evidence + [f"run root: {status.config.get('run_root')}"],
        )

    run = status.run
    run_status = str(run.get("status") or "unknown")
    profile = normalize_profile(run.get("profile", status.config.get("profile")))
    run_id = str(run.get("run_id") or "")
    task = str(run.get("task") or "")
    evidence.extend(
        [
            f"run: {run_id}",
            f"task: {task}",
            f"run status: {run_status}",
            f"run directory: {status.run_dir}",
        ]
    )
    if status.loop_contract is not None:
        evidence.append(f"loop contract: {status.loop_contract.get('status')}")
        diagnostics.append(
            f"success checks: {len(status.loop_contract.get('success_checks', []))}"
        )
        if profile == "autonomous":
            for reason in autonomous_stop_reasons(run, status.loop_contract):
                append_unique(blocked_reasons, reason)
    if status.memory is not None:
        pending = int(status.memory.get("pending", 0) or 0)
        if pending:
            diagnostics.append(f"memory proposals pending: {pending}")
            actions.append(
                guided_action(
                    "approve-memory",
                    "Review and approve safe memory proposals",
                    "loopforge learn --approve",
                    risk="memory",
                    requires_confirmation=True,
                    why="Durable memory changes should be explicitly reviewed before promotion.",
                )
            )

    if blocked_reasons:
        diagnostics.extend(blocked_reasons)

    if run_status == LOOP_CONTRACT_DRAFT:
        checks = status.loop_contract.get("success_checks", []) if status.loop_contract else []
        if not checks:
            blocked_reasons.append("the loop contract has no objective success checks")
            actions.append(
                guided_action(
                    "show-plan",
                    "Open the loop contract and add success checks",
                    "loopforge shell --command \"/plan\"",
                    why="Autonomous attempts need objective checks so progress can be verified.",
                )
            )
        actions.append(
            guided_action(
                "check-contract",
                "Re-check the loop contract",
                "loopforge continue",
                why="This validates whether the run is ready for an adapter attempt.",
            )
        )
        summary = "The current run needs a complete loop contract before execution."
        priority = "complete_contract"
    elif run_status == LOOP_CONTRACT_READY:
        if profile == "assist":
            actions.append(
                guided_action(
                    "review-contract",
                    "Review the ready loop contract",
                    "loopforge shell --command \"/plan\"",
                    why="Assist profile blocks workspace-changing adapter execution.",
                )
            )
        elif profile == "autonomous" and blocked_reasons:
            actions.append(
                guided_action(
                    "review-autonomy-stop",
                    "Review autonomy stop conditions",
                    "loopforge status",
                    why="Autonomous execution stops until a human resolves the listed condition.",
                )
            )
        else:
            actions.append(
                guided_action(
                    "continue",
                    f"Run a bounded attempt with {adapter}",
                    f"loopforge continue --adapter {adapter}",
                    risk="adapter-execution",
                    requires_confirmation=profile != "autonomous",
                    why=(
                        "The contract is ready and the autonomy profile allows a bounded "
                        "adapter attempt."
                    ),
                )
            )
        summary = "The run is ready for an adapter attempt."
        priority = "execute_attempt"
    elif run_status == ADAPTER_BLOCKED:
        actions.append(
            guided_action(
                "inspect-attempt",
                "Inspect the latest attempt stderr",
                "loopforge shell --command \"/raw latest stderr\"",
                why="The latest attempt artifact usually contains the actionable error.",
            )
        )
        actions.append(
            guided_action(
                "tasks",
                "Review recorded attempts",
                "loopforge shell --command \"/tasks\"",
                why="Attempt history shows what was tried and where it stopped.",
            )
        )
        summary = "The last adapter attempt is blocked and needs diagnosis."
        priority = "resolve_blocker"
    elif run_status == READY_FOR_VERIFICATION:
        actions.append(
            guided_action(
                "verify",
                "Generate patch and run verification",
                "loopforge verify",
                risk="verification",
                requires_confirmation=profile == "strict",
                why="The workspace changed; deterministic checks should verify the result.",
            )
        )
        summary = "The attempt completed; verification is the next step."
        priority = "verify_work"
    elif run_status == VERIFICATION_FAILED:
        actions.append(
            guided_action(
                "inspect-verification",
                "Inspect verification diagnostics",
                "loopforge shell --command \"/export plan\"",
                why="The verification report and blockers explain what must be fixed.",
            )
        )
        actions.append(
            guided_action(
                "retry-verify",
                "Run verification again after fixing blockers",
                "loopforge verify",
                why="Re-running verification confirms whether the diagnostic was resolved.",
            )
        )
        summary = "Verification failed; inspect diagnostics, fix the issue, then verify again."
        priority = "fix_verification"
    elif run_status == VERIFIED:
        actions.append(
            guided_action(
                "compact",
                "Write a compact handoff",
                "loopforge shell --command \"/compact\"",
                why="A compact handoff records the verified state for review or continuation.",
            )
        )
        actions.append(
            guided_action(
                "review",
                "Review verified patch and decide handoff",
                "loopforge shell --command \"/review\"",
                why=(
                    "Verification is evidence, not publication authority; "
                    "a human decision remains."
                ),
            )
        )
        summary = "The run is verified and ready for review or handoff."
        priority = "review_verified_work"
    else:
        actions.append(
            guided_action(
                "status",
                "Inspect current status",
                "loopforge status",
                why="The run is in an unfamiliar state, so status is the safest first check.",
            )
        )
        summary = "LoopForge found a run state that needs human inspection."
        priority = "inspect_state"

    if not diagnostics:
        diagnostics.append(status.next_step)
    return GuidanceResult(
        project_dir=status.project_dir,
        state=run_status,
        summary=summary,
        priority=priority,
        diagnostics=diagnostics,
        recommended_actions=actions,
        blocked_reasons=blocked_reasons,
        evidence=evidence,
    )


def run_summary_from_path(run_path: Path, *, current_run_id: str | None = None) -> dict[str, Any]:
    run_json_path = run_path / "run.json"
    summary: dict[str, Any] = {
        "run_id": run_path.name,
        "path": str(run_path),
        "current": run_path.name == current_run_id,
        "status": "missing",
        "task": "",
        "pack": "",
        "created_at": "",
        "updated_at": "",
    }
    if not run_json_path.exists():
        return summary
    try:
        run = read_json(run_json_path)
    except ValueError as error:
        summary.update({"status": "invalid", "error": str(error)})
        return summary
    summary.update(
        {
            "run_id": str(run.get("run_id") or run_path.name),
            "status": str(run.get("status") or "unknown"),
            "task": str(run.get("task") or ""),
            "pack": str(run.get("pack") or ""),
            "created_at": str(run.get("created_at") or ""),
            "updated_at": str(run.get("updated_at") or ""),
        }
    )
    return summary


def list_runs(project_dir: Path) -> RunListResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return RunListResult(
            project_dir=status.project_dir,
            run_root=None,
            initialized=False,
            config=None,
            current_run_id=None,
            runs=[],
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    current_run_id = status.config.get("current_run_id")
    runs: list[dict[str, Any]] = []
    if run_root.exists():
        for run_path in sorted(run_root.iterdir(), reverse=True):
            if run_path.is_dir():
                runs.append(
                    run_summary_from_path(
                        run_path,
                        current_run_id=str(current_run_id) if current_run_id else None,
                    )
                )
    return RunListResult(
        project_dir=status.project_dir,
        run_root=run_root,
        initialized=True,
        config=status.config,
        current_run_id=str(current_run_id) if current_run_id else None,
        runs=runs,
        blockers=[],
    )


def current_or_selected_run(
    project_dir: Path,
    run_id: str | None = None,
) -> tuple[StatusResult, Path | None, Path | None, dict[str, Any] | None, list[str]]:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return status, None, None, None, [status.next_step]
    if run_id is None:
        if status.run is None or status.run_dir is None:
            blockers = status.blockers or [status.next_step]
            return status, status.run_dir, status.run_json_path, None, blockers
        return status, status.run_dir, status.run_json_path, status.run, []

    selected = run_id.strip()
    if not selected:
        return status, None, None, None, ["run id must not be empty"]
    run_dir = Path(str(status.config["run_root"])).expanduser() / selected
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return status, run_dir, run_json_path, None, [f"run metadata not found: {run_json_path}"]
    return status, run_dir, run_json_path, read_json(run_json_path), []


def nonnegative_int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def first_nonnegative_int(*values: object) -> int | None:
    for value in values:
        parsed = nonnegative_int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def latest_attempt(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = attempt_records(run)
    return attempts[-1] if attempts else None


def read_attempt_protocol_result(run_dir: Path, attempt: dict[str, Any] | None) -> dict[str, Any]:
    if attempt is None:
        return {}
    raw_path = attempt.get("result_path")
    if not isinstance(raw_path, str) or not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = run_dir / path
    if not path.exists():
        return {}
    try:
        result = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return result


def model_from_command(command: object) -> str | None:
    if not isinstance(command, list):
        return None
    parts = [str(part) for part in command]
    for index, part in enumerate(parts):
        if part in {"-m", "--model"} and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith("--model="):
            return part.split("=", 1)[1] or None
    return None


def metrics_model(
    *,
    override: str | None,
    attempt: dict[str, Any] | None,
    protocol_result: dict[str, Any],
) -> dict[str, Any]:
    model: str | None = override.strip() if isinstance(override, str) and override.strip() else None
    if model is None:
        raw_model = protocol_result.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        elif isinstance(raw_model, dict):
            candidate = raw_model.get("id") or raw_model.get("name")
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
    if model is None:
        for key in ("model_id", "model_name"):
            candidate = protocol_result.get(key)
            if isinstance(candidate, str) and candidate.strip():
                model = candidate.strip()
                break
    if model is None and attempt is not None:
        model = model_from_command(attempt.get("command"))
    return {
        "status": "reported" if model is not None else "unavailable",
        "id": model,
    }


def metrics_tokens(
    *,
    protocol_result: dict[str, Any],
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
) -> dict[str, Any]:
    source = protocol_result.get("tokens")
    if not isinstance(source, dict):
        source = protocol_result.get("usage")
    if not isinstance(source, dict):
        source = {}
    measured_input = first_nonnegative_int(
        input_tokens,
        source.get("input_tokens"),
        source.get("prompt_tokens"),
    )
    measured_output = first_nonnegative_int(
        output_tokens,
        source.get("output_tokens"),
        source.get("completion_tokens"),
    )
    measured_total = first_nonnegative_int(total_tokens, source.get("total_tokens"))
    if measured_total is None and measured_input is not None and measured_output is not None:
        measured_total = measured_input + measured_output
    status = (
        "reported"
        if any(value is not None for value in (measured_input, measured_output, measured_total))
        else "unavailable"
    )
    return {
        "status": status,
        "input_tokens": measured_input,
        "output_tokens": measured_output,
        "total_tokens": measured_total,
    }


def metrics_cost(
    *,
    protocol_result: dict[str, Any],
    amount_microunits: int | None,
    currency: str | None,
) -> dict[str, Any]:
    source = protocol_result.get("cost")
    if not isinstance(source, dict):
        source = {}
    measured_amount = first_nonnegative_int(
        amount_microunits,
        source.get("amount_microunits"),
        source.get("total_microunits"),
    )
    measured_currency = (
        currency.strip().upper()
        if isinstance(currency, str) and currency.strip()
        else None
    )
    if measured_currency is None:
        raw_currency = source.get("currency")
        if isinstance(raw_currency, str) and raw_currency.strip():
            measured_currency = raw_currency.strip().upper()
    return {
        "status": "reported" if measured_amount is not None else "unavailable",
        "amount_microunits": measured_amount,
        "currency": measured_currency if measured_amount is not None else None,
    }


def metrics_patch(verification: dict[str, Any] | None) -> dict[str, Any]:
    if verification is None:
        return {
            "status": "unavailable",
            "path": None,
            "size_bytes": None,
            "sha256": None,
        }
    patch = verification.get("patch", {})
    if not isinstance(patch, dict):
        patch = {}
    size = nonnegative_int_or_none(patch.get("size_bytes"))
    generated = bool(patch.get("generated"))
    if generated or patch.get("status") == "generated":
        status = "measured"
    else:
        status = "not_generated"
    return {
        "status": status,
        "path": patch.get("path") if isinstance(patch.get("path"), str) else None,
        "size_bytes": size if size is not None else (0 if status == "not_generated" else None),
        "sha256": patch.get("sha256") if isinstance(patch.get("sha256"), str) else None,
    }


def inferred_final_disposition(run_status: object) -> str:
    status = str(run_status or "unknown")
    if status == VERIFIED:
        return "verified"
    if status == VERIFICATION_FAILED:
        return "failed"
    if status == ADAPTER_BLOCKED:
        return "blocked"
    if status == READY_FOR_VERIFICATION:
        return "pending_verification"
    if status in {LOOP_CONTRACT_DRAFT, LOOP_CONTRACT_READY}:
        return "pending"
    return status


def build_metrics_record(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> dict[str, Any]:
    attempt = latest_attempt(run)
    protocol_result = read_attempt_protocol_result(run_dir, attempt)
    verification = verification_state(run)
    finished_at = (
        verification.get("finished_at")
        if isinstance(verification, dict) and verification.get("finished_at")
        else (attempt or {}).get("finished_at")
    )
    if not finished_at:
        finished_at = run.get("updated_at") or run.get("created_at")
    measured_duration = duration_seconds(run.get("created_at"), finished_at)
    attempt_count = run.get("attempt_count")
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = len(attempt_records(run))
    adapter = attempt.get("adapter") if isinstance(attempt, dict) else None
    final = (
        final_disposition.strip()
        if isinstance(final_disposition, str) and final_disposition.strip()
        else inferred_final_disposition(run.get("status"))
    )
    corrections = nonnegative_int_or_none(human_corrections)
    if corrections is None:
        corrections = nonnegative_int_or_none(run.get("human_correction_count"))
    return {
        "metrics_version": 1,
        "recorded_at": utc_now(),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "task": run.get("task"),
        "project_root": str(project_dir),
        "profile": run.get("profile"),
        "pack": run.get("pack"),
        "timing": {
            "started_at": run.get("created_at"),
            "finished_at": finished_at,
            "duration_seconds": measured_duration,
            "status": "measured" if measured_duration is not None else "unavailable",
        },
        "adapter": {
            "status": "reported" if isinstance(adapter, str) and adapter else "unavailable",
            "id": adapter if isinstance(adapter, str) and adapter else None,
        },
        "model": metrics_model(
            override=model,
            attempt=attempt,
            protocol_result=protocol_result,
        ),
        "attempts": {
            "count": attempt_count,
            "statuses": [
                str(item.get("status") or "unknown")
                for item in attempt_records(run)
            ],
        },
        "tokens": metrics_tokens(
            protocol_result=protocol_result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        "cost": metrics_cost(
            protocol_result=protocol_result,
            amount_microunits=cost_microunits,
            currency=cost_currency,
        ),
        "patch": metrics_patch(verification),
        "verification": {
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "checks_passed": (
                verification.get("checks_passed") if isinstance(verification, dict) else None
            ),
            "checks_total": (
                verification.get("checks_total") if isinstance(verification, dict) else None
            ),
        },
        "human_corrections": {
            "status": "measured" if corrections is not None else "unavailable",
            "count": corrections,
        },
        "final_disposition": {
            "status": final,
            "source": "reported" if final_disposition else "run_status",
        },
    }


def record_run_metrics(
    project_dir: Path,
    *,
    run_id: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_microunits: int | None = None,
    cost_currency: str | None = None,
    human_corrections: int | None = None,
    final_disposition: str | None = None,
) -> MetricsRecordResult:
    status, run_dir, _run_json_path, run, blockers = current_or_selected_run(project_dir, run_id)
    if blockers or run is None or run_dir is None:
        return MetricsRecordResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge metrics record failed.",
            record_path=None,
            record=None,
            blockers=blockers,
        )
    record = build_metrics_record(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_microunits=cost_microunits,
        cost_currency=cost_currency,
        human_corrections=human_corrections,
        final_disposition=final_disposition,
    )
    record_path = run_dir / "metrics" / METRICS_RECORD_FILE
    write_json_atomic(record_path, record)
    return MetricsRecordResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        ok=True,
        message="LoopForge metrics recorded.",
        record_path=record_path,
        record=record,
        blockers=[],
    )


def metric_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return value
    return None


def summarize_number_series(records: list[dict[str, Any]], values: list[object]) -> dict[str, Any]:
    known = [number for number in (metric_number(value) for value in values) if number is not None]
    total = sum(known) if known else None
    return {
        "known_count": len(known),
        "unknown_count": len(records) - len(known),
        "min": min(known) if known else None,
        "max": max(known) if known else None,
        "sum": total,
        "average": (total / len(known)) if known else None,
    }


def count_values(values: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value) if value is not None else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def summarize_token_field(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    return summarize_number_series(
        records,
        [
            record.get("tokens", {}).get(field)
            if isinstance(record.get("tokens"), dict)
            else None
            for record in records
        ],
    )


def summarize_costs(records: list[dict[str, Any]]) -> dict[str, Any]:
    totals_by_currency: dict[str, int] = {}
    known = 0
    for record in records:
        cost = record.get("cost")
        if not isinstance(cost, dict):
            continue
        amount = nonnegative_int_or_none(cost.get("amount_microunits"))
        currency = cost.get("currency")
        if amount is None or not isinstance(currency, str) or not currency:
            continue
        known += 1
        totals_by_currency[currency] = totals_by_currency.get(currency, 0) + amount
    return {
        "known_count": known,
        "unknown_count": len(records) - known,
        "amount_microunits_by_currency": dict(sorted(totals_by_currency.items())),
    }


def build_metrics_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for record in records:
        timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
        patch = record.get("patch") if isinstance(record.get("patch"), dict) else {}
        verification = (
            record.get("verification") if isinstance(record.get("verification"), dict) else {}
        )
        final = (
            record.get("final_disposition")
            if isinstance(record.get("final_disposition"), dict)
            else {}
        )
        attempts = record.get("attempts") if isinstance(record.get("attempts"), dict) else {}
        rows.append(
            {
                "run_id": record.get("run_id"),
                "duration_seconds": timing.get("duration_seconds"),
                "attempt_count": attempts.get("count"),
                "patch_size_bytes": patch.get("size_bytes"),
                "verification": verification.get("status"),
                "final_disposition": final.get("status"),
            }
        )
    return {
        "metrics_version": 1,
        "record_count": len(records),
        "duration_seconds": summarize_number_series(
            records,
            [
                record.get("timing", {}).get("duration_seconds")
                if isinstance(record.get("timing"), dict)
                else None
                for record in records
            ],
        ),
        "attempt_count": summarize_number_series(
            records,
            [
                record.get("attempts", {}).get("count")
                if isinstance(record.get("attempts"), dict)
                else None
                for record in records
            ],
        ),
        "patch_size_bytes": summarize_number_series(
            records,
            [
                record.get("patch", {}).get("size_bytes")
                if isinstance(record.get("patch"), dict)
                else None
                for record in records
            ],
        ),
        "tokens": {
            "input_tokens": summarize_token_field(records, "input_tokens"),
            "output_tokens": summarize_token_field(records, "output_tokens"),
            "total_tokens": summarize_token_field(records, "total_tokens"),
        },
        "cost": summarize_costs(records),
        "verification_results": count_values(
            [
                record.get("verification", {}).get("status")
                if isinstance(record.get("verification"), dict)
                else None
                for record in records
            ]
        ),
        "final_dispositions": count_values(
            [
                record.get("final_disposition", {}).get("status")
                if isinstance(record.get("final_disposition"), dict)
                else None
                for record in records
            ]
        ),
        "runs": rows,
    }


def summarize_run_metrics(project_dir: Path) -> MetricsSummaryResult:
    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return MetricsSummaryResult(
            project_dir=status.project_dir,
            run_root=None,
            ok=False,
            message="LoopForge metrics summarize failed.",
            records=[],
            summary=build_metrics_summary([]),
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    if run_root.exists():
        for path in sorted(run_root.glob(f"*/metrics/{METRICS_RECORD_FILE}")):
            try:
                record = read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                blockers.append(f"could not read metrics record {path}: {error}")
                continue
            records.append(record)
    summary = build_metrics_summary(records)
    return MetricsSummaryResult(
        project_dir=status.project_dir,
        run_root=run_root,
        ok=not blockers,
        message=(
            "LoopForge metrics summary ready."
            if not blockers
            else "LoopForge metrics summary has warnings."
        ),
        records=records,
        summary=summary,
        blockers=blockers,
    )


def compact_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def dashboard_number_summary(records: list[dict[str, Any]], values: list[object]) -> dict[str, Any]:
    return summarize_number_series(records, values)


def dashboard_attempt_rows(run: dict[str, Any] | None) -> list[dict[str, Any]]:
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


def dashboard_snapshot(project_dir: Path) -> DashboardResult:
    status = current_status(project_dir)
    guidance = current_guidance(project_dir)
    run_list = list_runs(project_dir)
    metrics = summarize_run_metrics(project_dir)
    run = status.run
    contract = status.loop_contract or {}
    attempts = dashboard_attempt_rows(run)
    blockers = list(status.blockers)
    for source in (guidance.blocked_reasons, run_list.blockers, metrics.blockers):
        for blocker in source:
            append_unique(blockers, str(blocker))

    limits: dict[str, Any] = {"max_attempts": None, "timeout_seconds": None}
    if run is not None:
        limits["max_attempts"] = attempt_limit(run, contract)
        limits["timeout_seconds"] = attempt_timeout(run, contract)

    action = guidance.recommended_actions[0] if guidance.recommended_actions else None
    memory_rows = dashboard_memory_proposal_rows(status.memory)
    verification = status.verification or {}
    patch = verification.get("patch", {}) if isinstance(verification, dict) else {}
    diff_policy = verification.get("diff_policy", {}) if isinstance(verification, dict) else {}
    risk = verification.get("risk", {}) if isinstance(verification, dict) else {}

    snapshot = {
        "dashboard_version": 1,
        "project": {
            "path": str(status.project_dir),
            "name": status.project_dir.name,
            "initialized": status.initialized,
            "config_path": str(status.config_path),
            "profile": status.config.get("profile") if status.config else None,
            "run_root": status.config.get("run_root") if status.config else None,
            "current_run_id": status.config.get("current_run_id") if status.config else None,
            "default_adapter": status.config.get("default_adapter") if status.config else None,
        },
        "runs": {
            "run_root": str(run_list.run_root) if run_list.run_root is not None else None,
            "current_run_id": run_list.current_run_id,
            "total": len(run_list.runs),
            "items": run_list.runs,
        },
        "current_loop": {
            "available": run is not None,
            "run_id": run.get("run_id") if run else None,
            "task": run.get("task") if run else None,
            "status": run.get("status") if run else None,
            "profile": run.get("profile") if run else None,
            "pack": run.get("pack") if run else None,
            "run_dir": str(status.run_dir) if status.run_dir is not None else None,
            "loop_contract_status": contract.get("status") if contract else None,
            "success_checks": contract.get("success_checks", []) if contract else [],
            "allowed_tools": contract.get("allowed_tools", []) if contract else [],
            "subjective": bool(contract.get("subjective")) if contract else False,
            "rubric_present": bool(contract.get("rubric")) if contract else False,
            "attempts_count": len(attempts),
            "limits": limits,
            "next_step": status.next_step,
        },
        "attempts": {
            "count": len(attempts),
            "max_attempts": limits["max_attempts"],
            "remaining": (
                max(0, int(limits["max_attempts"]) - len(attempts))
                if isinstance(limits["max_attempts"], int)
                else None
            ),
            "items": attempts,
        },
        "verification": {
            "available": bool(verification),
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "patch_path": patch.get("path") if isinstance(patch, dict) else None,
            "patch_size_bytes": patch.get("size_bytes") if isinstance(patch, dict) else None,
            "diff_policy_allowed": (
                diff_policy.get("allowed") if isinstance(diff_policy, dict) else None
            ),
            "risk": risk.get("risk") if isinstance(risk, dict) else None,
            "checks_passed": (
                verification.get("checks_passed") if isinstance(verification, dict) else None
            ),
            "checks_total": (
                verification.get("checks_total") if isinstance(verification, dict) else None
            ),
            "stagnated": bool(verification.get("stagnated"))
            if isinstance(verification, dict)
            else False,
        },
        "memory": {
            "available": status.memory is not None,
            "durable_path": status.memory.get("durable_path") if status.memory else None,
            "durable_items": status.memory.get("durable_items") if status.memory else None,
            "run_snapshot": status.memory.get("run_snapshot") if status.memory else None,
            "proposal_path": status.memory.get("proposal_path") if status.memory else None,
            "pending": status.memory.get("pending", 0) if status.memory else 0,
            "promoted": status.memory.get("promoted", 0) if status.memory else 0,
            "rejected": status.memory.get("rejected", 0) if status.memory else 0,
            "proposal_rows": memory_rows,
            "pending_proposals": [
                proposal for proposal in memory_rows if proposal.get("status") == "pending"
            ],
        },
        "adapter_comparison": dashboard_adapter_comparison(metrics.records),
        "next_human_action": {
            "available": action is not None,
            "id": action.id if action else None,
            "label": action.label if action else None,
            "command": action.command if action else None,
            "do_command": f"loopforge shell --command \"/do {action.id}\"" if action else None,
            "risk": action.risk if action else None,
            "requires_confirmation": action.requires_confirmation if action else None,
            "why": action.why if action else None,
        },
        "blockers": blockers,
    }
    return DashboardResult(
        project_dir=status.project_dir,
        ok=not blockers and metrics.ok,
        snapshot=snapshot,
        blockers=blockers,
    )


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


def resume_run(project_dir: Path, run_id: str) -> ResumeRunResult:
    if not run_id.strip():
        return ResumeRunResult(
            project_dir=project_dir.resolve(),
            run_dir=None,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=["run id must not be empty"],
        )

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ResumeRunResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=[status.next_step],
        )

    run_root = Path(str(status.config["run_root"])).expanduser()
    run_dir = run_root / run_id.strip()
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return ResumeRunResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=None,
            ok=False,
            message="LoopForge resume failed.",
            blockers=[f"run metadata not found: {run_json_path}"],
        )

    run = read_json(run_json_path)
    config = dict(status.config)
    config["current_run_id"] = str(run.get("run_id") or run_id.strip())
    config["updated_at"] = utc_now()
    write_json_atomic(status.config_path, config)
    return ResumeRunResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=run,
        ok=True,
        message=f"LoopForge resumed run: {config['current_run_id']}",
        blockers=[],
    )


def directory_file_sizes(root: Path) -> list[tuple[str, int]]:
    if not root.exists():
        return []
    sizes: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                sizes.append((str(path.relative_to(root)), path.stat().st_size))
            except OSError:
                continue
    return sizes


def render_compact_context(status: StatusResult, *, focus: str = "") -> str:
    lines = [
        "# LoopForge Compact Context",
        "",
        f"- Generated: {utc_now()}",
        f"- Project: {status.project_dir}",
    ]
    if focus.strip():
        lines.append(f"- Focus: {focus.strip()}")
    if status.config is not None:
        lines.extend(
            [
                f"- Profile: {status.config.get('profile')}",
                f"- Run root: {status.config.get('run_root')}",
            ]
        )
    if status.run is None or status.run_dir is None:
        lines.extend(["", "## Current Run", "", "No current run is available."])
    else:
        run = status.run
        lines.extend(
            [
                "",
                "## Current Run",
                "",
                f"- Run ID: {run.get('run_id')}",
                f"- Task: {run.get('task')}",
                f"- Status: {run.get('status')}",
                f"- Pack: {run.get('pack')}",
                f"- Attempts: {run.get('attempt_count', len(run.get('attempts', [])))}",
                f"- Run directory: {status.run_dir}",
            ]
        )
        checks = run.get("success_checks", [])
        if isinstance(checks, list) and checks:
            lines.extend(["", "## Success Checks", ""])
            lines.extend(f"- {check}" for check in checks)
        if status.loop_contract is not None:
            lines.extend(
                [
                    "",
                    "## Loop Contract",
                    "",
                    f"- Status: {status.loop_contract.get('status')}",
                    f"- Subjective: {'yes' if status.loop_contract.get('subjective') else 'no'}",
                    f"- Rubric: {'present' if status.loop_contract.get('rubric') else 'missing'}",
                ]
            )
        if status.verification is not None:
            verification = status.verification
            checks_passed = verification.get("checks_passed", 0)
            checks_total = verification.get("checks_total", 0)
            lines.extend(
                [
                    "",
                    "## Verification",
                    "",
                    f"- Status: {verification.get('status')}",
                    f"- Checks: {checks_passed}/{checks_total}",
                ]
            )
            patch = verification.get("patch", {})
            if isinstance(patch, dict):
                lines.append(f"- Patch: {patch.get('path') or 'none'}")
        if status.memory is not None:
            memory = status.memory
            lines.extend(
                [
                    "",
                    "## Memory",
                    "",
                    f"- Durable items: {memory.get('durable_items', 0)}",
                    f"- Pending proposals: {memory.get('pending', 0)}",
                    f"- Run snapshot: {memory.get('run_snapshot') or 'none'}",
                ]
            )
        sizes = directory_file_sizes(status.run_dir)
        if sizes:
            lines.extend(["", "## Run Files", ""])
            for relative_name, size in sizes[:40]:
                lines.append(f"- {relative_name}: {size} bytes")
            if len(sizes) > 40:
                lines.append(f"- ... {len(sizes) - 40} more files")

    lines.extend(["", "## Blockers", ""])
    if status.blockers:
        lines.extend(f"- {blocker}" for blocker in status.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Next Step", "", status.next_step, ""])
    return "\n".join(lines)


def compact_current_context(project_dir: Path, *, focus: str = "") -> CompactContextResult:
    status = current_status(project_dir)
    summary = render_compact_context(status, focus=focus)
    if not status.initialized:
        return CompactContextResult(
            project_dir=status.project_dir,
            run_dir=None,
            path=None,
            ok=False,
            message="LoopForge compact failed.",
            summary=summary,
            blockers=[status.next_step],
        )
    if status.run_dir is None:
        return CompactContextResult(
            project_dir=status.project_dir,
            run_dir=None,
            path=None,
            ok=False,
            message="LoopForge compact failed.",
            summary=summary,
            blockers=[status.next_step],
        )
    target_dir = status.run_dir / "artifacts" / "context"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "compact.md"
    target_path.write_text(summary, encoding="utf-8")
    return CompactContextResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        path=target_path,
        ok=True,
        message=f"LoopForge compact context written: {target_path}",
        summary=summary,
        blockers=[],
    )


def new_run_id() -> str:
    timestamp = utc_now().replace("-", "").replace(":", "").replace("Z", "Z")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def create_run(
    project_dir: Path,
    task: str,
    *,
    pack: str | None = None,
    success_checks: list[str] | None = None,
    selected_skills: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    max_attempts: int = 3,
    timeout_seconds: int = 1800,
    subjective_rubric: str = "",
) -> RunResult:
    if not task.strip():
        raise ValueError("task must not be empty")
    if max_attempts < 1:
        raise ValueError("max attempts must be at least 1")
    if timeout_seconds < 1:
        raise ValueError("timeout must be at least 1 second")

    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} does not exist; run `loopforge init` first")

    config = normalize_config(project_dir, read_json(config_path))[0]
    project_memory = ensure_project_memory(project_dir)
    run_root = Path(str(config["run_root"])).expanduser()
    run_id = new_run_id()
    run_dir = run_root / run_id
    while run_dir.exists():
        run_id = new_run_id()
        run_dir = run_root / run_id

    attempts_dir = run_dir / "attempts"
    artifacts_dir = run_dir / "artifacts"
    metrics_dir = run_dir / "metrics"
    legacy_dir = artifacts_dir / "legacy-agent"
    for directory in (attempts_dir, artifacts_dir, metrics_dir):
        directory.mkdir(parents=True, exist_ok=False)

    now = utc_now()
    base_commit = detect_git_base_commit(project_dir)
    task_id = run_id
    legacy_issue = legacy_issue_for_task(task_id)
    legacy_base_commit = base_commit or SYNTHETIC_LEGACY_BASE_COMMIT
    normalized_success_checks = normalize_nonempty_strings(success_checks)
    if pack is None:
        pack_contract = detect_project_pack(project_dir)
        selected_pack = str(pack_contract["name"])
        pack_detection = "auto"
    else:
        selected_pack = pack.strip()
        if not selected_pack:
            raise ValueError("pack must not be empty")
        pack_contract = load_pack_contract(project_dir, selected_pack)
        pack_detection = "explicit"
    run_profile = normalize_profile(config["profile"])
    pack_skills = pack_skill_entries(pack_contract)
    normalized_skills = normalize_unique_strings(
        [*pack_skills, *normalize_nonempty_strings(selected_skills)]
    )
    normalized_allowed_tools = normalize_nonempty_strings(allowed_tools) or list(
        DEFAULT_ALLOWED_TOOLS
    )
    normalized_rubric = subjective_rubric.strip()
    subjective = task_looks_subjective(task)
    contract_status = loop_contract_status(
        success_checks=normalized_success_checks,
        profile=run_profile,
        subjective=subjective,
        subjective_rubric=normalized_rubric,
    )
    run_data: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "task": task.strip(),
        "project_root": str(project_dir),
        "base_commit": base_commit,
        "profile": run_profile,
        "profile_policy": profile_policy(run_profile),
        "pack": selected_pack,
        "pack_contract": {
            "name": selected_pack,
            "version": pack_contract.get("version"),
            "description": pack_contract.get("description"),
            "source": pack_contract.get("source"),
            "detection": pack_detection,
            "detection_score": pack_contract.get("detection_score", 0),
            "skills": pack_skills,
            "skill_file": pack_contract.get("skill_file"),
            "checks_file": pack_contract.get("checks_file"),
            "protected_paths_file": pack_contract.get("protected_paths_file"),
            "memory_rules_file": pack_contract.get("memory_rules_file"),
        },
        "status": contract_status,
        "created_at": now,
        "success_checks": normalized_success_checks,
        "limits": {
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
        },
        "attempt_count": 0,
        "attempts": [],
        "blockers": [],
        "loop_contract": {
            "path": str(run_dir / "loop.md"),
            "version": 1,
            "status": contract_status,
            "subjective": subjective,
            "requires_rubric": run_profile == "autonomous" and subjective,
        },
        "memory": {
            "durable_project_memory": str(project_memory),
            "run_snapshot": str(run_dir / "memory.md"),
            "pending_proposals": 0,
            "promoted": 0,
            "rejected": 0,
        },
        "artifacts": {
            "task": str(run_dir / "task.md"),
            "loop": str(run_dir / "loop.md"),
            "plan": str(run_dir / "plan.md"),
            "progress": str(run_dir / "progress.md"),
            "verification": str(run_dir / "verification.md"),
            "memory": str(run_dir / "memory.md"),
            "scratch": str(run_dir / "scratch.md"),
            "exchange": str(run_dir / "exchange.json"),
            "attempts": str(attempts_dir),
            "artifacts": str(artifacts_dir),
            "metrics": str(metrics_dir),
            "legacy_agent": str(legacy_dir),
        },
        "legacy": {
            "issue": legacy_issue,
            "issue_source": "generated_from_task_id",
            "base_commit": legacy_base_commit,
            "base_commit_source": "git" if base_commit else "synthetic_no_git_sentinel",
            "artifact_dir": str(legacy_dir),
            "validator": str(legacy_artifact_validator()),
        },
    }

    write_json_atomic(run_dir / "run.json", run_data)
    (run_dir / "task.md").write_text(f"# Task\n\n{task.strip()}\n", encoding="utf-8")
    (run_dir / "loop.md").write_text(
        render_loop_contract(
            task=task.strip(),
            task_id=task_id,
            project_dir=project_dir,
            base_commit=base_commit,
            profile=run_profile,
            pack=selected_pack,
            skills=normalized_skills,
            allowed_tools=normalized_allowed_tools,
            success_checks=normalized_success_checks,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            subjective=subjective,
            subjective_rubric=normalized_rubric,
        ),
        encoding="utf-8",
    )
    (run_dir / "plan.md").write_text("# Plan\n\nNo plan recorded yet.\n", encoding="utf-8")
    (run_dir / "progress.md").write_text(
        "# Progress\n\nNo attempts recorded yet.\n",
        encoding="utf-8",
    )
    (run_dir / "verification.md").write_text(
        "# Verification\n\nVerification has not run yet.\n",
        encoding="utf-8",
    )
    (run_dir / "memory.md").write_text(
        render_run_memory_snapshot(project_dir, run_id),
        encoding="utf-8",
    )
    (run_dir / "scratch.md").write_text(
        read_project_template(project_dir, "scratch.md"),
        encoding="utf-8",
    )
    write_json_atomic(
        run_dir / "exchange.json",
        {
            "exchange_version": 1,
            "run_id": run_id,
            "producer": "",
            "consumer": "",
            "messages": [],
            "artifacts": [],
            "open_questions": [],
        },
    )
    create_legacy_artifacts(
        legacy_dir,
        task=task.strip(),
        issue=legacy_issue,
        base_commit=legacy_base_commit,
    )

    updated_config = dict(config)
    updated_config["current_run_id"] = run_id
    updated_config["updated_at"] = now
    write_json_atomic(config_path, updated_config)

    return RunResult(
        project_dir=project_dir,
        config_path=config_path,
        run_dir=run_dir,
        run_json_path=run_dir / "run.json",
        config=updated_config,
        run=run_data,
    )


def attempt_limit(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 1


def attempt_timeout(run: dict[str, Any], contract: dict[str, Any]) -> int:
    run_limits = run.get("limits", {})
    if isinstance(run_limits, dict):
        value = run_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    contract_limits = contract.get("limits", {})
    if isinstance(contract_limits, dict):
        value = contract_limits.get("timeout_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return 540


def attempt_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attempts = run.get("attempts", [])
    if not isinstance(raw_attempts, list):
        return []
    return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]


def command_for_adapter(adapter: str, adapter_args: list[str]) -> list[str]:
    if adapter == "local-adapter-fixture":
        if not adapter_args:
            raise ValueError("local-adapter-fixture requires a command after --")
        return adapter_args
    command = AGENT_COMMANDS.get(adapter)
    if command is None:
        raise ValueError(f"unsupported adapter: {adapter}")
    return [command, *adapter_args]


def session_hash(seed: dict[str, Any], label: str) -> str:
    encoded = json.dumps({"label": label, **seed}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_session_for(run: dict[str, Any], adapter: str, project_dir: Path) -> dict[str, Any]:
    legacy = run.get("legacy", {})
    if not isinstance(legacy, dict):
        legacy = {}
    issue = legacy.get("issue")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        issue = legacy_issue_for_task(str(run.get("task_id") or run.get("run_id") or "1"))
    base_commit = legacy.get("base_commit")
    if not isinstance(base_commit, str) or len(base_commit) != 40:
        base_commit = run.get("base_commit") or SYNTHETIC_LEGACY_BASE_COMMIT
    seed = {
        "issue": issue,
        "base_commit": base_commit,
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "adapter": adapter,
        "workspace": str(project_dir.resolve()),
    }
    return {
        "issue": issue,
        "risk": "low",
        "base_commit": base_commit,
        "workspace": str(project_dir.resolve()),
        "runner_id": adapter,
        "preflight_sha256": session_hash(seed, "preflight"),
        "start_authorization_receipt_sha256": session_hash(seed, "start-authorization"),
    }


def decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return str(path)


def workspace_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in project_dir.rglob("*"):
        if ".git" in path.parts:
            continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(project_dir).as_posix()
        except ValueError:
            relative = str(path)
        snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def workspace_snapshot_changes(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changes: list[str] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            changes.append(f"A {name}")
        elif name not in after:
            changes.append(f"D {name}")
        elif before[name] != after[name]:
            changes.append(f"M {name}")
    return changes


def git_status_entries(project_dir: Path) -> list[str] | None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


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


def synthetic_adapter_result(
    *,
    session: dict[str, Any],
    status: str,
    summary: str,
    workspace_changed: bool,
) -> dict[str, Any]:
    return {
        "result_version": 1,
        "purpose": "implementation_session_result",
        "mode": "untrusted-runner-output",
        "status": status,
        **session,
        "summary": summary[:1000] or "Adapter execution did not produce a summary.",
        "workspace_changed": workspace_changed,
        "patch_generated": False,
        "deterministic_checks_run": False,
        "publication_requested": False,
        "network_requested": False,
        "next_action": "deterministic_patch_generation"
        if status == "completed"
        else "human_review",
    }


def run_with_isolated_process(command: list[str], cwd: Path, timeout_seconds: int) -> dict[str, Any]:
    isolated_process = isolated_process_module()
    policy = isolated_process.load_policy()
    bounded_timeout = min(float(timeout_seconds), float(policy["max_timeout_seconds"]))
    return isolated_process.run(
        command,
        cwd,
        os.environ,
        policy,
        timeout_seconds=bounded_timeout,
    )


def adapter_protocol_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    project_dir: Path,
) -> list[str]:
    adapter_path = local_implementation_adapter()
    if not adapter_path.exists():
        raise FileNotFoundError(f"local implementation adapter not found: {adapter_path}")
    return [
        usable_python_executable(),
        str(adapter_path),
        "--expected-session",
        str(expected_session_path),
        "--workspace",
        str(project_dir),
        "--",
        *command,
    ]


def execute_fixture_command(
    *,
    command: list[str],
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    resolved_command = list(command)
    executable = Path(resolved_command[0])
    if not executable.is_absolute():
        found = shutil.which(resolved_command[0])
        if found:
            resolved_command[0] = found
    child = run_with_isolated_process(resolved_command, project_dir, timeout_seconds)
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def execute_adapter_command(
    *,
    adapter: str,
    command: list[str],
    expected_session_path: Path,
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    protocol_command = adapter_protocol_command(
        adapter=adapter,
        command=command,
        expected_session_path=expected_session_path,
        project_dir=project_dir,
    )
    child = run_with_isolated_process(
        protocol_command,
        repository_root(),
        min(timeout_seconds + 5, 600),
    )
    stdout = child["stdout"] if isinstance(child.get("stdout"), bytes) else b""
    stderr = child["stderr"] if isinstance(child.get("stderr"), bytes) else b""
    return child, stdout, stderr


def parse_adapter_result(stdout: bytes) -> dict[str, Any] | None:
    if not stdout.strip():
        return None
    try:
        parsed = json.loads(decode_output(stdout))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def execute_attempt(
    *,
    project_dir: Path,
    run_dir: Path,
    run: dict[str, Any],
    contract: dict[str, Any],
    adapter: str,
    adapter_args: list[str],
) -> dict[str, Any]:
    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter}")
    command = command_for_adapter(adapter, adapter_args)
    attempts = attempt_records(run)
    number = len(attempts) + 1
    attempt_id = f"attempt-{number:03d}"
    attempt_dir = run_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)

    started = utc_now()
    session = expected_session_for(run, adapter, project_dir)
    expected_session_path = attempt_dir / "expected-session.json"
    write_json_atomic(expected_session_path, session)
    before_snapshot = workspace_snapshot(project_dir)
    before_git = git_status_entries(project_dir)
    timeout_seconds = attempt_timeout(run, contract)

    if adapter == "local-adapter-fixture":
        child, stdout, stderr = execute_fixture_command(
            command=command,
            project_dir=project_dir,
            timeout_seconds=timeout_seconds,
        )
        result = None
    else:
        child, stdout, stderr = execute_adapter_command(
            adapter=adapter,
            command=command,
            expected_session_path=expected_session_path,
            project_dir=project_dir,
            timeout_seconds=timeout_seconds,
        )
        result = parse_adapter_result(stdout)

    finished = utc_now()
    after_snapshot = workspace_snapshot(project_dir)
    after_git = git_status_entries(project_dir)
    workspace_changes = (
        after_git
        if after_git is not None
        else workspace_snapshot_changes(before_snapshot, after_snapshot)
    )
    snapshot_changed = before_snapshot != after_snapshot
    returncode = child.get("returncode")
    completed = bool(child.get("completed")) and returncode == 0
    timed_out = bool(child.get("timed_out"))
    output_limit_exceeded = bool(child.get("output_limit_exceeded"))

    if adapter == "local-adapter-fixture":
        status = "completed" if completed and snapshot_changed else "blocked"
        if timed_out:
            status = "failed"
            summary = "Fixture command timed out."
        elif output_limit_exceeded:
            status = "failed"
            summary = "Fixture command exceeded the output limit."
        elif not completed:
            status = "failed"
            summary = f"Fixture command failed with return code {returncode}."
        elif snapshot_changed:
            summary = "Fixture command completed and changed the workspace."
        else:
            summary = "Fixture command completed without workspace changes."
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=summary,
            workspace_changed=snapshot_changed,
        )
    elif result is None:
        status = "failed"
        stderr_text = decode_output(stderr).strip()
        stdout_text = decode_output(stdout).strip()
        detail = stderr_text or stdout_text or "adapter produced no protocol result"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=f"Adapter failed before producing a result: {detail}"[:1000],
            workspace_changed=snapshot_changed,
        )
    else:
        status = str(result.get("status", "failed"))
        if "workspace_changed" not in result:
            result["workspace_changed"] = snapshot_changed
        if "summary" not in result:
            result["summary"] = f"Adapter reported {status}."

    profile_stop_reasons: list[str] = []
    if normalize_profile(run.get("profile")) == "autonomous":
        profile_stop_reasons = adapter_result_stop_reasons(result)
        if profile_stop_reasons and status == "completed":
            status = "blocked"
            result["status"] = status
            result["summary"] = (
                str(result.get("summary", "")).rstrip()
                + " Autonomy profile stopped for human review."
            ).strip()

    stdout_path = attempt_dir / "adapter.stdout"
    stderr_path = attempt_dir / "adapter.stderr"
    result_path = attempt_dir / "result.json"
    write_bytes(stdout_path, stdout)
    write_bytes(stderr_path, stderr)
    write_json_atomic(result_path, result)

    attempt = {
        "id": attempt_id,
        "number": number,
        "adapter": adapter,
        "command": command,
        "started_at": started,
        "finished_at": finished,
        "status": status,
        "summary": str(result.get("summary", "")),
        "workspace_changed": bool(result.get("workspace_changed", snapshot_changed)),
        "workspace_changes": workspace_changes,
        "returncode": returncode,
        "timed_out": timed_out,
        "output_limit_exceeded": output_limit_exceeded,
        "profile_stop_reasons": profile_stop_reasons,
        "publication_requested": bool(result.get("publication_requested", False)),
        "network_requested": bool(result.get("network_requested", False)),
        "attempt_dir": str(attempt_dir),
        "expected_session_path": relative_to_run(run_dir, expected_session_path),
        "stdout_path": relative_to_run(run_dir, stdout_path),
        "stderr_path": relative_to_run(run_dir, stderr_path),
        "result_path": relative_to_run(run_dir, result_path),
        "before_git_status": before_git,
        "after_git_status": after_git,
    }
    write_json_atomic(attempt_dir / "attempt.json", attempt)
    append_progress(run_dir, attempt)
    return attempt


def update_run_after_attempt(
    *,
    run_json_path: Path,
    run: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(run)
    attempts = attempt_records(updated)
    attempts.append(attempt)
    updated["attempts"] = attempts
    updated["attempt_count"] = len(attempts)
    updated["last_attempt"] = attempt
    updated["updated_at"] = utc_now()
    if attempt["status"] == "completed":
        updated["status"] = READY_FOR_VERIFICATION
        updated["blockers"] = []
    else:
        updated["status"] = ADAPTER_BLOCKED
        blockers = [
            f"attempt {attempt['id']} with adapter {attempt['adapter']} "
            f"reported {attempt['status']}: {attempt['summary']}"
        ]
        for reason in attempt.get("profile_stop_reasons", []):
            blockers.append(str(reason))
        updated["blockers"] = blockers
    write_json_atomic(run_json_path, updated)
    return updated


def pack_check_paths(project_dir: Path, pack: str) -> list[Path]:
    return pack_file_candidates(project_dir, pack, "checks.json")


def load_pack_checks(project_dir: Path, pack: str) -> dict[str, Any]:
    for path in pack_check_paths(project_dir, pack):
        if not path.exists():
            continue
        data = read_json(path)
        checks = data.get("checks", [])
        if not isinstance(checks, list):
            raise ValueError(f"{path} must contain a checks list")
        normalized: list[dict[str, Any]] = []
        for index, check in enumerate(checks, start=1):
            if not isinstance(check, dict):
                raise ValueError(f"{path} check {index} must be an object")
            name = str(check.get("name") or f"check-{index}").strip()
            command = check.get("command")
            if not isinstance(command, list) or not command or not all(
                isinstance(part, str) and part for part in command
            ):
                raise ValueError(f"{path} check {name} must define a non-empty command list")
            env = check.get("env", {})
            if not isinstance(env, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in env.items()
            ):
                raise ValueError(f"{path} check {name} env must be an object of strings")
            timeout = check.get("timeout_seconds", 300)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
                raise ValueError(f"{path} check {name} timeout_seconds must be positive")
            normalized.append(
                {
                    "name": name,
                    "command": command,
                    "env": env,
                    "timeout_seconds": timeout,
                }
            )
        return {
            "source": str(path),
            "checks": normalized,
        }
    return {
        "source": None,
        "checks": [],
    }


def expand_check_value(
    value: str,
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> str:
    replacements = {
        "{python}": usable_python_executable(),
        "{repo}": str(project_dir),
        "{run_dir}": str(run_dir),
        "{patch}": str(patch_path or ""),
    }
    expanded = value
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    return expanded


def run_pack_check(
    check: dict[str, Any],
    *,
    project_dir: Path,
    run_dir: Path,
    patch_path: Path | None,
) -> dict[str, Any]:
    command = [
        expand_check_value(
            part,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
        for part in check["command"]
    ]
    env = os.environ.copy()
    for key, value in check.get("env", {}).items():
        env[key] = expand_check_value(
            value,
            project_dir=project_dir,
            run_dir=run_dir,
            patch_path=patch_path,
        )
    started = utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(check["timeout_seconds"]),
            check=False,
        )
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "timed_out",
            "returncode": None,
            "stdout": (error.stdout or "")[-4000:]
            if isinstance(error.stdout, str)
            else "",
            "stderr": (error.stderr or "")[-4000:]
            if isinstance(error.stderr, str)
            else "",
            "timed_out": True,
        }
    except OSError as error:
        return {
            "name": check["name"],
            "command": command,
            "started_at": started,
            "finished_at": utc_now(),
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "timed_out": False,
        }


def run_json_check(command: list[str], cwd: Path, timeout: int = 60) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": payload,
    }


def pack_protected_path_paths(project_dir: Path, pack: str) -> list[Path]:
    return pack_file_candidates(project_dir, pack, "protected-paths.json")


def load_pack_protected_paths(project_dir: Path, pack: str) -> dict[str, Any]:
    for path in pack_protected_path_paths(project_dir, pack):
        if not path.exists():
            continue
        data = read_json(path)
        high = data.get("high_path_patterns", [])
        medium = data.get("medium_path_patterns", [])
        for field_name, value in (
            ("high_path_patterns", high),
            ("medium_path_patterns", medium),
        ):
            if not isinstance(value, list) or not all(
                isinstance(pattern, str) for pattern in value
            ):
                raise ValueError(f"{path} {field_name} must be a list of strings")
        return {
            "source": str(path),
            "high_path_patterns": high,
            "medium_path_patterns": medium,
        }
    return {
        "source": None,
        "high_path_patterns": [],
        "medium_path_patterns": [],
    }


def merged_risk_policy_path(
    *,
    project_dir: Path,
    run_dir: Path,
    pack: str,
) -> tuple[Path, list[str]]:
    base = read_json(default_risk_policy())
    protected = load_pack_protected_paths(project_dir, pack)
    sources = [str(default_risk_policy())]
    if protected["source"]:
        sources.append(str(protected["source"]))
    high_patterns = normalize_unique_strings(
        [
            *[str(pattern) for pattern in base.get("high_path_patterns", [])],
            *[str(pattern) for pattern in protected.get("high_path_patterns", [])],
        ]
    )
    medium_patterns = normalize_unique_strings(
        [
            *[str(pattern) for pattern in base.get("medium_path_patterns", [])],
            *[str(pattern) for pattern in protected.get("medium_path_patterns", [])],
        ]
    )
    merged = dict(base)
    merged["high_path_patterns"] = high_patterns
    merged["medium_path_patterns"] = medium_patterns
    policy_path = run_dir / "artifacts" / "policies" / "risk-rules.merged.json"
    write_json_atomic(policy_path, merged)
    return policy_path, sources


def verification_failure_parts(verification: dict[str, Any]) -> list[Any]:
    parts: list[Any] = []
    patch = verification.get("patch", {})
    if isinstance(patch, dict) and patch.get("status") == "failed":
        parts.append({"patch_error": patch.get("error")})
    diff_policy = verification.get("diff_policy", {})
    if isinstance(diff_policy, dict) and diff_policy.get("allowed") is False:
        violations = diff_policy.get("violations", [])
        rules = []
        if isinstance(violations, list):
            for violation in violations:
                if isinstance(violation, dict):
                    rules.append(violation.get("rule"))
        parts.append({"policy_violations": sorted(str(rule) for rule in rules if rule)})
    checks = verification.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("status") != "passed":
                parts.append(
                    {
                        "check": check.get("name"),
                        "status": check.get("status"),
                        "returncode": check.get("returncode"),
                    }
                )
    return parts


def failure_signature(verification: dict[str, Any]) -> str | None:
    parts = verification_failure_parts(verification)
    if not parts:
        return None
    encoded = json.dumps(parts, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def verify_run(project_dir: Path, *, confirmed: bool = False) -> VerifyResult:
    status = current_status(project_dir)
    if not status.initialized:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            ok=False,
            message="Initialize LoopForge before verification.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            ok=False,
            message="No current run is ready for verification.",
            blockers=status.blockers or [status.next_step],
        )

    run = status.run
    run_dir = status.run_dir
    run_json_path = status.run_json_path or (run_dir / "run.json")
    profile_blockers = profile_transition_blockers(
        profile=run.get("profile", DEFAULT_PROFILE),
        action="verification",
        confirmed=confirmed,
        run=run,
        contract=status.loop_contract,
    )
    if profile_blockers:
        return VerifyResult(
            project_dir=status.project_dir,
            run_dir=run_dir,
            run=run,
            ok=False,
            message="LoopForge verification refused by the autonomy profile.",
            blockers=profile_blockers,
            verification=verification_state(run),
        )
    started = utc_now()
    patch_dir = run_dir / "artifacts" / "patches"
    patch_path = patch_dir / "complete.patch"
    blockers: list[str] = []
    patch_summary: dict[str, Any] = {
        "generated": False,
        "path": None,
        "size_bytes": 0,
        "sha256": None,
        "status": "not_run",
    }
    diff_summary: dict[str, Any] = {
        "allowed": None,
        "facts": {},
        "violations": [],
        "status": "not_run",
    }
    risk_summary: dict[str, Any] = {
        "risk": None,
        "route": None,
        "policy_allowed": None,
        "reasons": [],
        "facts": {},
        "status": "not_run",
    }
    checks: list[dict[str, Any]] = []
    pack_checks_source: str | None = None
    risk_policy_sources: list[str] = []
    risk_policy_path: Path | None = None

    base_commit = run.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        blockers.append("patch generation requires a Git base_commit recorded in run.json.")
    else:
        generator = imported_check("generate_complete_patch.py")
        generated = run_json_check(
            [
                usable_python_executable(),
                str(generator),
                "--repo",
                str(status.project_dir),
                "--base",
                base_commit,
                "--output",
                str(patch_path),
                "--policy",
                str(default_diff_policy()),
                "--force",
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if generated["returncode"] != 0 or generated["json"] is None:
            error = generated["stderr"].strip() or generated["stdout"].strip()
            patch_summary.update({"status": "failed", "error": error})
            blockers.append(f"patch generation failed: {error or 'unknown error'}")
        else:
            patch_result = generated["json"]
            artifact = patch_result.get("artifact", {})
            if not isinstance(artifact, dict):
                artifact = {}
            patch_summary.update(
                {
                    "generated": bool(artifact.get("retained", False)),
                    "path": relative_to_run(run_dir, patch_path) if artifact.get("retained") else None,
                    "size_bytes": artifact.get("size_bytes", 0),
                    "sha256": artifact.get("sha256"),
                    "status": "generated" if artifact.get("retained") else "not_retained",
                }
            )
            diff_summary.update(
                {
                    "allowed": bool(patch_result.get("allowed", False)),
                    "facts": patch_result.get("facts", {}),
                    "violations": patch_result.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                blockers.append("diff policy blocked the generated patch.")

    if patch_path.exists() and isinstance(base_commit, str) and base_commit:
        diff_result = run_json_check(
            [
                usable_python_executable(),
                str(imported_check("diff_policy.py")),
                "--patch",
                str(patch_path),
                "--policy",
                str(default_diff_policy()),
                "--repo",
                str(status.project_dir),
                "--base",
                str(base_commit),
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if diff_result["returncode"] == 0 and diff_result["json"] is not None:
            diff_payload = diff_result["json"]
            diff_summary.update(
                {
                    "allowed": bool(diff_payload.get("allowed", False)),
                    "facts": diff_payload.get("facts", {}),
                    "violations": diff_payload.get("violations", []),
                    "status": "completed",
                }
            )
            if not diff_summary["allowed"]:
                append_unique(blockers, "diff policy blocked the generated patch.")
        else:
            error = diff_result["stderr"].strip() or diff_result["stdout"].strip()
            diff_summary.update({"status": "failed", "error": error})
            blockers.append(f"diff policy failed: {error or 'unknown error'}")

        try:
            risk_policy_path, risk_policy_sources = merged_risk_policy_path(
                project_dir=status.project_dir,
                run_dir=run_dir,
                pack=str(run.get("pack") or DEFAULT_PACK),
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            risk_summary.update({"status": "failed", "error": str(error)})
            blockers.append(f"risk policy could not be loaded: {error}")

        risk_result = run_json_check(
            [
                usable_python_executable(),
                str(imported_check("classify_patch_risk.py")),
                "--patch",
                str(patch_path),
                "--diff-policy",
                str(default_diff_policy()),
                "--risk-policy",
                str(risk_policy_path or default_risk_policy()),
                "--repo",
                str(status.project_dir),
                "--base",
                str(base_commit),
                "--format",
                "json",
            ],
            cwd=repository_root(),
        )
        if risk_result["returncode"] == 0 and risk_result["json"] is not None:
            risk_payload = risk_result["json"]
            risk_summary.update(
                {
                    "risk": risk_payload.get("risk"),
                    "route": risk_payload.get("route"),
                    "policy_allowed": risk_payload.get("policy_allowed"),
                    "reasons": risk_payload.get("reasons", []),
                    "facts": risk_payload.get("facts", {}),
                    "human_gates": risk_payload.get("human_gates", {}),
                    "policy": (
                        relative_to_run(run_dir, risk_policy_path)
                        if risk_policy_path is not None
                        else str(default_risk_policy())
                    ),
                    "policy_sources": risk_policy_sources,
                    "status": "completed",
                }
            )
        else:
            error = risk_result["stderr"].strip() or risk_result["stdout"].strip()
            risk_summary.update({"status": "failed", "error": error})
            blockers.append(f"risk classification failed: {error or 'unknown error'}")

    try:
        pack_config = load_pack_checks(status.project_dir, str(run.get("pack") or DEFAULT_PACK))
        pack_checks_source = pack_config.get("source")
        for check in pack_config["checks"]:
            result = run_pack_check(
                check,
                project_dir=status.project_dir,
                run_dir=run_dir,
                patch_path=patch_path if patch_path.exists() else None,
            )
            checks.append(result)
            if result["status"] != "passed":
                blockers.append(f"pack check failed: {result['name']} ({result['status']}).")
    except ValueError as error:
        blockers.append(f"pack checks could not be loaded: {error}")

    finished = utc_now()
    checks_passed = sum(1 for check in checks if check.get("status") == "passed")
    verification: dict[str, Any] = {
        "version": 1,
        "started_at": started,
        "finished_at": finished,
        "status": "failed" if blockers else "passed",
        "patch": patch_summary,
        "diff_policy": diff_summary,
        "risk": risk_summary,
        "pack": run.get("pack") or DEFAULT_PACK,
        "pack_checks_source": pack_checks_source,
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": checks_passed,
        "blockers": blockers,
    }
    signature = failure_signature(verification)
    if signature:
        previous = verification_state(run)
        if (
            isinstance(previous, dict)
            and previous.get("failure_signature") == signature
            and previous.get("status") == "failed"
        ):
            verification["stagnated"] = True
            append_unique(blockers, "stagnation: repeated equivalent verification failure.")
        verification["failure_signature"] = signature
    verification["blockers"] = blockers
    if blockers:
        verification["status"] = "failed"

    (run_dir / "verification.md").write_text(
        render_verification_markdown(verification),
        encoding="utf-8",
    )
    update_loop_diagnostic(run_dir, verification)

    updated_run = dict(run)
    updated_run["verification"] = verification
    updated_run["updated_at"] = utc_now()
    updated_run["status"] = VERIFIED if not blockers else VERIFICATION_FAILED
    updated_run["blockers"] = [] if not blockers else blockers
    write_json_atomic(run_json_path, updated_run)

    return VerifyResult(
        project_dir=status.project_dir,
        run_dir=run_dir,
        run=updated_run,
        ok=not blockers,
        message="LoopForge verification passed." if not blockers else "LoopForge verification failed.",
        blockers=blockers,
        verification=verification,
    )


def continue_run(
    project_dir: Path,
    *,
    adapter: str | None = None,
    adapter_args: list[str] | None = None,
    confirmed: bool = False,
) -> ContinueResult:
    status = current_status(project_dir)
    if not status.initialized:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=None,
            run=None,
            contract=None,
            ok=False,
            message="Initialize LoopForge before continuing.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=None,
            contract=status.loop_contract,
            ok=False,
            message="No current run is ready to continue.",
            blockers=status.blockers or [status.next_step],
        )

    contract = status.loop_contract or loop_contract_state(status.run_dir / "loop.md")
    blockers = list(status.blockers)
    if contract["status"] != "valid":
        for error in contract.get("errors", []):
            append_unique(blockers, str(error))
    if not contract.get("success_checks"):
        append_unique(
            blockers,
            "loop contract has no success checks; add at least one under # Success Checks."
        )
    profile = str(status.run.get("profile", ""))
    if profile == "autonomous" and contract.get("subjective") and not contract.get("rubric"):
        append_unique(
            blockers,
            "subjective work needs a rubric before autonomous attempts; "
            "add it under # Subjective Rubric."
        )
    attempts = attempt_records(status.run)
    max_attempts = attempt_limit(status.run, contract)
    if len(attempts) >= max_attempts:
        append_unique(
            blockers,
            f"max attempts reached ({len(attempts)}/{max_attempts}); human review is required.",
        )
    if blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the loop contract.",
            blockers=blockers,
        )

    if adapter is None:
        profile_blockers = profile_transition_blockers(
            profile=status.run.get("profile", DEFAULT_PROFILE),
            action="adapter_attempt",
            confirmed=confirmed,
            run=status.run,
            contract=contract,
        )
        if profile_blockers:
            message = "Loop contract accepted; profile policy blocks adapter execution."
        else:
            message = (
                "Loop contract accepted; Phase 4 adapter execution is available "
                "with `loopforge continue --adapter <adapter>`."
            )
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=True,
            message=message,
            blockers=profile_blockers,
        )

    profile_blockers = profile_transition_blockers(
        profile=status.run.get("profile", DEFAULT_PROFILE),
        action="adapter_attempt",
        confirmed=confirmed,
        run=status.run,
        contract=contract,
    )
    if profile_blockers:
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=False,
            message="LoopForge continue refused by the autonomy profile.",
            blockers=profile_blockers,
        )

    try:
        attempt = execute_attempt(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            adapter=adapter,
            adapter_args=adapter_args or [],
        )
        updated_run = update_run_after_attempt(
            run_json_path=status.run_json_path or (status.run_dir / "run.json"),
            run=status.run,
            attempt=attempt,
        )
    except (OSError, RuntimeError, ValueError) as error:
        blocker = f"adapter execution could not start: {error}"
        updated_run = dict(status.run)
        updated_run["status"] = ADAPTER_BLOCKED
        updated_run["blockers"] = [blocker]
        if status.run_json_path is not None:
            write_json_atomic(status.run_json_path, updated_run)
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=False,
            message="LoopForge adapter execution is blocked.",
            blockers=[blocker],
        )

    if attempt["status"] == "completed":
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=updated_run,
            contract=contract,
            ok=True,
            message="LoopForge adapter attempt completed; run is ready for verification.",
            blockers=[],
            attempt=attempt,
        )

    return ContinueResult(
        project_dir=status.project_dir,
        run_dir=status.run_dir,
        run=updated_run,
        contract=contract,
        ok=False,
        message="LoopForge adapter attempt ended in a blocked state.",
        blockers=updated_run.get("blockers", []),
        attempt=attempt,
    )
