"""Core helpers for LoopForge project initialization."""

from __future__ import annotations

import json
import os
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
DEFAULT_PROFILE = "supervised"
DEFAULT_PACK = "generic-code"
READY_FOR_VERIFICATION = "ready_for_verification"
ADAPTER_BLOCKED = "adapter_blocked"
LOOP_CONTRACT_DRAFT = "loop_contract_draft"
LOOP_CONTRACT_READY = "loop_contract_ready"
SYNTHETIC_LEGACY_BASE_COMMIT = "0" * 40

SUPPORTED_ADAPTERS = (
    "codex",
    "claude-code",
    "aider",
    "opencode",
    "mini-swe-agent",
    "local-adapter-fixture",
)

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


def read_project_template(project_dir: Path, relative_name: str) -> str:
    template_path = project_config_dir(project_dir) / "templates" / relative_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    fallback = TEMPLATES.get(f"templates/{relative_name}")
    if fallback is None:
        raise KeyError(f"unknown template: {relative_name}")
    return fallback


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def legacy_templates_dir() -> Path:
    return repository_root() / ".agent" / "templates"


def legacy_artifact_validator() -> Path:
    return repository_root() / ".agent" / "checks" / "validate_artifacts.py"


def local_implementation_adapter() -> Path:
    return repository_root() / ".agent" / "adapters" / "local_implementation_adapter.py"


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
        "subjective": subjective,
        "rubric": rubric,
        "limits": limits,
        "errors": errors,
    }


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


def new_config(
    project_dir: Path,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "project_name": project_name(project_dir),
        "profile": profile,
        "run_root": str(default_run_root(project_dir, home=home)),
        "current_run_id": None,
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
    if "project_name" not in config:
        config["project_name"] = project_name(project_dir)
    if "profile" not in config:
        config["profile"] = profile
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
        return "Review the run artifacts, then add verification in the next implementation phase."
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
        next_step=describe_next_step(run),
        blockers=blockers,
    )


def new_run_id() -> str:
    timestamp = utc_now().replace("-", "").replace(":", "").replace("Z", "Z")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def create_run(
    project_dir: Path,
    task: str,
    *,
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
    normalized_skills = normalize_nonempty_strings(selected_skills)
    normalized_allowed_tools = normalize_nonempty_strings(allowed_tools) or list(
        DEFAULT_ALLOWED_TOOLS
    )
    normalized_rubric = subjective_rubric.strip()
    subjective = task_looks_subjective(task)
    contract_status = loop_contract_status(
        success_checks=normalized_success_checks,
        profile=str(config["profile"]),
        subjective=subjective,
        subjective_rubric=normalized_rubric,
    )
    run_data: dict[str, Any] = {
        "run_id": run_id,
        "task_id": task_id,
        "task": task.strip(),
        "project_root": str(project_dir),
        "base_commit": base_commit,
        "profile": config["profile"],
        "pack": DEFAULT_PACK,
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
            "requires_rubric": str(config["profile"]) == "autonomous" and subjective,
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
            profile=str(config["profile"]),
            pack=DEFAULT_PACK,
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
        read_project_template(project_dir, "memory.md"),
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
        updated["blockers"] = [
            f"attempt {attempt['id']} with adapter {attempt['adapter']} "
            f"reported {attempt['status']}: {attempt['summary']}"
        ]
    write_json_atomic(run_json_path, updated)
    return updated


def continue_run(
    project_dir: Path,
    *,
    adapter: str | None = None,
    adapter_args: list[str] | None = None,
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
        return ContinueResult(
            project_dir=status.project_dir,
            run_dir=status.run_dir,
            run=status.run,
            contract=contract,
            ok=True,
            message=(
                "Loop contract accepted; Phase 4 adapter execution is available "
                "with `loopforge continue --adapter <adapter>`."
            ),
            blockers=[],
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
