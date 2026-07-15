"""Command line interface for LoopForge."""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Sequence

from loopforge import __version__
from loopforge.cli.errors import DOCS_URL, CliError, CliRuntimeError, CliUsageError
from loopforge.cli.github import GitHubIssueClient
from loopforge.cli.intake import RunIntakeService
from loopforge.cli.models import CliOptions, GitHubIssueRef, IssueReadResult, RunIntake
from loopforge.cli.parser import (
    CliParserBuilder,
    LoopForgeArgumentParser,
    add_format_args,
    add_table_args,
    non_negative_int,
)
from loopforge.engine import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_ADAPTER,
    DEFAULT_PROFILE,
    SUPPORTED_ADAPTERS,
    approve_plan,
    approve_review,
    continue_run,
    create_run,
    current_guidance,
    current_status,
    dashboard_snapshot,
    detect_project_pack,
    discover_pack_contracts,
    execute_readonly_stage,
    initialize_project,
    index_diagnostics,
    learn_run,
    list_registered_projects,
    list_runs,
    list_runs_all_projects,
    load_pack_checks,
    loopforge_home,
    next_readonly_stage,
    normalize_profile,
    open_project,
    prepare_draft_publication,
    platform_cache_home,
    profile_permission_lines,
    project_config_path,
    record_run_metrics,
    rebuild_indexes,
    repository_root,
    summarize_run_metrics,
    task_looks_subjective,
    verify_run,
)
from loopforge.cli.ui import (
    TerminalRenderer,
    compact_text,
    not_reported,
    render_blocked,
    render_dashboard,
    render_guidance,
    render_status,
    render_success,
    render_summary_table,
    yes_no,
)


GLOBAL_FLAGS = {
    "--no-color",
    "--plain",
    "--interactive-ui",
    "--no-input",
    "--quiet",
    "--debug",
    "--version",
    "-V",
    "--json",
}
TABLE_DEFAULT_COLUMNS = {
    "pack-list": ["current", "name", "skills", "agents", "stages", "kind"],
    "runs": ["current", "run_id", "status", "task", "pack", "updated_at"],
    "global-runs": ["project", "current", "run_id", "attention", "status", "task", "updated_at"],
    "projects": ["attention", "name", "branch", "run_count", "last_activity", "path"],
    "metrics-runs": ["run_id", "duration_seconds", "attempt_count", "patch_size_bytes", "verification", "final_disposition"],
}


def prompt_text(label: str, *, default: str = "", required: bool = True) -> str:
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    while True:
        value = input(prompt).strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""
        print("Please enter a value.")


def prompt_yes_no(label: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def split_csv_prompt(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def configured_adapter(config: dict[str, Any]) -> tuple[str, list[str]]:
    adapter = str(config.get("default_adapter") or DEFAULT_ADAPTER)
    if adapter not in SUPPORTED_ADAPTERS:
        adapter = DEFAULT_ADAPTER
    raw_args = config.get("default_adapter_args", [])
    adapter_args = [str(value) for value in raw_args] if isinstance(raw_args, list) else []
    return adapter, adapter_args


def adapter_continue_command(adapter: str, adapter_args: list[str] | None = None) -> str:
    command = f"loopforge continue --adapter {adapter}"
    if adapter_args:
        command += " -- " + subprocess.list2cmdline([str(arg) for arg in adapter_args])
    return command


def current_project_profile(project_dir: Path) -> str:
    try:
        config = json.loads(project_config_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PROFILE
    return normalize_profile(config.get("profile", DEFAULT_PROFILE))


def _github_client() -> GitHubIssueClient:
    return GitHubIssueClient(sys.modules[__name__])


def parse_github_remote(remote: str) -> tuple[str, str] | None:
    return _github_client().parse_remote(remote)


def github_repo_from_remote(project_dir: Path) -> tuple[str, str] | None:
    return _github_client().repository_from_remote(project_dir)


def parse_github_issue_url(source: str) -> GitHubIssueRef | None:
    return _github_client().parse_issue_url(source)


def resolve_github_issue_ref(project_dir: Path, source: str) -> tuple[GitHubIssueRef | None, str]:
    return _github_client().resolve(project_dir, source)


def gh_issue_view(ref: GitHubIssueRef) -> IssueReadResult:
    return _github_client().view(ref)


def gh_issue_list(project_dir: Path) -> IssueReadResult:
    return _github_client().list_open(project_dir)


def issue_task_summary(issue: dict[str, Any]) -> str:
    return GitHubIssueClient.task_summary(issue)


def issue_source_metadata(
    ref: GitHubIssueRef,
    issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return GitHubIssueClient.source_metadata(ref, issue)


def github_issue_label_names(issue: dict[str, Any]) -> set[str]:
    return GitHubIssueClient.label_names(issue)


def github_issue_is_agent_approved(issue: dict[str, Any]) -> bool:
    return _github_client().is_agent_approved(issue)


def require_agent_approved_issue(ref: GitHubIssueRef, issue: dict[str, Any]) -> None:
    _github_client().require_agent_approved(ref, issue)


def _intake_service() -> RunIntakeService:
    return RunIntakeService(sys.modules[__name__])


def pack_check_suggestions(project_dir: Path, pack: str | None) -> list[tuple[str, str]]:
    return _intake_service().pack_check_suggestions(project_dir, pack)


def permission_suggestions() -> list[tuple[str, str]]:
    return _intake_service().permission_suggestions()


def confirm_or_edit_list(
    title: str,
    suggestions: list[tuple[str, str]],
    *,
    default_values: list[str] | None = None,
) -> list[str]:
    return _intake_service().confirm_or_edit_list(
        title,
        suggestions,
        default_values=default_values,
    )


def build_manual_intake(
    project_dir: Path,
    args: argparse.Namespace,
    *,
    default_task: str = "",
    source_metadata: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> RunIntake:
    return _intake_service().build_manual(
        project_dir,
        args,
        default_task=default_task,
        source_metadata=source_metadata,
        notes=notes,
    )


def build_issue_intake(
    project_dir: Path,
    args: argparse.Namespace,
    ref: GitHubIssueRef,
    issue: dict[str, Any],
) -> RunIntake:
    return _intake_service().build_issue(project_dir, args, ref, issue)


def build_noninteractive_issue_intake(
    project_dir: Path,
    args: argparse.Namespace,
    ref: GitHubIssueRef,
    issue: dict[str, Any],
) -> RunIntake:
    return _intake_service().build_noninteractive_issue(project_dir, args, ref, issue)


def choose_issue_from_list(project_dir: Path) -> tuple[GitHubIssueRef | None, dict[str, Any] | None, str]:
    return _intake_service().choose_issue_from_list(project_dir)


def interactive_run_intake(project_dir: Path, args: argparse.Namespace) -> RunIntake:
    return _intake_service().interactive(project_dir, args)


def noninteractive_run_intake(project_dir: Path, args: argparse.Namespace) -> RunIntake:
    return _intake_service().noninteractive(project_dir, args)


def print_guidance(project_dir: Path, *, concise: bool = False) -> None:
    guidance = current_guidance(project_dir)
    print("guidance:")
    print(f"now: {guidance.summary}")
    if guidance.blocked_reasons:
        print("problem:")
        for reason in guidance.blocked_reasons:
            print(f"- {reason}")
    elif guidance.diagnostics and not concise:
        print("diagnostics:")
        for diagnostic in guidance.diagnostics:
            print(f"- {diagnostic}")
    if guidance.recommended_actions:
        first = guidance.recommended_actions[0]
        print(f"recommended next action: [{first.id}] {first.label}")
        print(f"command: {first.command}")
        print(f"why: {first.why}")
    if not concise and len(guidance.recommended_actions) > 1:
        print("useful commands:")
        for action in guidance.recommended_actions[1:]:
            print(f"- [{action.id}] {action.command} ({action.why})")


def print_native_artifacts(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"native artifacts: {state['status']} ({state['present']}/{state['total']})")
    missing_files = state.get("missing_files", [])
    missing_directories = state.get("missing_directories", [])
    if missing_files:
        print(f"native missing files: {', '.join(str(name) for name in missing_files)}")
    if missing_directories:
        print(f"native missing directories: {', '.join(str(name) for name in missing_directories)}")


def print_legacy_artifacts(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"legacy artifacts: {state['status']}")
    print(f"legacy issue: {state.get('issue') or 'none'}")
    print(f"legacy artifact directory: {state.get('artifact_dir') or 'none'}")
    errors = state.get("errors", [])
    if errors:
        print("legacy artifact notes:")
        for error in errors:
            if isinstance(error, dict):
                artifact = error.get("artifact", "*")
                rule = error.get("rule", "note")
                message = error.get("message", error)
                print(f"- {artifact} {rule}: {message}")
            else:
                print(f"- {error}")


def print_loop_contract(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"loop contract: {state['status']}")
    print(f"success checks: {len(state.get('success_checks', []))}")
    print(f"subjective: {'yes' if state.get('subjective') else 'no'}")
    if state.get("subjective"):
        print(f"rubric: {'present' if state.get('rubric') else 'missing'}")
    errors = state.get("errors", [])
    if errors:
        print("loop contract notes:")
        for error in errors:
            print(f"- {error}")


def print_verification(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"verification: {state.get('status', 'unknown')}")
    patch = state.get("patch", {})
    if isinstance(patch, dict):
        print(f"patch: {patch.get('path') or 'none'}")
        print(f"patch size bytes: {patch.get('size_bytes', 0)}")
    diff_policy = state.get("diff_policy", {})
    if isinstance(diff_policy, dict):
        print(f"diff policy allowed: {diff_policy.get('allowed')}")
    risk = state.get("risk", {})
    if isinstance(risk, dict):
        print(f"risk: {risk.get('risk') or 'unknown'}")
        if risk.get("policy"):
            print(f"risk policy: {risk['policy']}")
    print(f"pack checks: {state.get('checks_passed', 0)}/{state.get('checks_total', 0)}")
    if state.get("stagnated"):
        print("stagnation: yes")


def print_memory(state: dict[str, object] | None) -> None:
    if state is None:
        return
    print(f"durable memory: {state.get('durable_items', 0)} items")
    print(f"durable memory path: {state.get('durable_path') or 'none'}")
    print(f"run memory snapshot: {state.get('run_snapshot') or 'none'}")
    print(
        "memory proposals: "
        f"{state.get('pending', 0)} pending, "
        f"{state.get('promoted', 0)} promoted, "
        f"{state.get('rejected', 0)} rejected"
    )
    if state.get("proposal_path"):
        print(f"memory proposal path: {state['proposal_path']}")


def print_pack_contract(run: dict[str, object]) -> None:
    contract = run.get("pack_contract", {})
    if not isinstance(contract, dict):
        return
    if contract.get("source"):
        print(f"pack source: {contract['source']}")
    if contract.get("detection"):
        print(f"pack selection: {contract['detection']}")
    skills = contract.get("skills", [])
    if isinstance(skills, list):
        print(f"pack skills: {len(skills)}")
        for skill in skills:
            print(f"- {skill}")
    agents = contract.get("agents", [])
    if isinstance(agents, list):
        print(f"pack agents: {len(agents)}")
        for agent in agents:
            if isinstance(agent, dict):
                print(f"- {agent.get('id')}: {agent.get('mode')}")
    workflow = contract.get("workflow", [])
    if isinstance(workflow, list):
        print(f"pack workflow stages: {len(workflow)}")


def print_workspace(run: dict[str, object]) -> None:
    workspace = run.get("workspace", {})
    if not isinstance(workspace, dict) or not workspace:
        return
    print(f"workspace mode: {workspace.get('mode') or 'unknown'}")
    print(f"workspace: {workspace.get('path') or 'none'}")


def print_profile_policy(profile: object, *, file=None) -> None:
    if file is None:
        file = sys.stdout
    for line in profile_permission_lines(profile):
        print(line, file=file)


def print_json_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def preparse_global_options(argv: Sequence[str]) -> tuple[CliOptions, list[str]]:
    values = {
        "no_color": False,
        "plain": False,
        "no_input": False,
        "quiet": False,
        "debug": debug_enabled_from_env(),
        "version": False,
        "json": False,
        "interactive_ui": False,
    }
    cleaned: list[str] = []
    passthrough = False
    for item in argv:
        if passthrough:
            cleaned.append(item)
            continue
        if item == "--":
            passthrough = True
            cleaned.append(item)
            continue
        if item == "--no-color":
            values["no_color"] = True
            continue
        if item == "--plain":
            values["plain"] = True
            continue
        if item == "--interactive-ui":
            values["interactive_ui"] = True
            continue
        if item == "--no-input":
            values["no_input"] = True
            continue
        if item == "--quiet":
            values["quiet"] = True
            continue
        if item == "--debug":
            values["debug"] = True
            continue
        if item in {"--version", "-V"}:
            values["version"] = True
            continue
        if item == "--json":
            values["json"] = True
            continue
        cleaned.append(item)
    return CliOptions(**values), cleaned


def debug_enabled_from_env() -> bool:
    debug = os.environ.get("DEBUG", "")
    return os.environ.get("LOOPFORGE_DEBUG") == "1" or debug == "loopforge" or debug.startswith("loopforge")


def output_format(args: argparse.Namespace, options: CliOptions, *, default: str = "text") -> str:
    if options.json:
        return "json"
    return str(getattr(args, "format", default))


def set_format_from_json_alias(args: argparse.Namespace, options: CliOptions) -> None:
    if options.json:
        setattr(args, "format", "json")


def error_payload(error: CliError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "title": error.title,
            "detail": error.detail,
            "fix": error.fix,
            "url": error.url,
        },
    }


def render_cli_error(error: CliError, options: CliOptions) -> None:
    if options.json:
        print_json_payload(error_payload(error))
        return
    print(f"Error {error.code}: {error.title}", file=sys.stderr)
    if error.detail:
        print(error.detail, file=sys.stderr)
    if error.fix:
        print(f"Fix: {error.fix}", file=sys.stderr)
    if error.url:
        print(f"More: {error.url}", file=sys.stderr)


def write_debug_log(exc: BaseException) -> Path:
    log_dir = platform_cache_home()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "debug.log"
    if path.exists() and path.stat().st_size > 1_000_000:
        path.replace(log_dir / "debug.log.1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(traceback.format_exc())
        handle.write("\n")
    return path


def print_guidance_if_needed(project_dir: Path, options: CliOptions, *, concise: bool = False) -> None:
    if not options.quiet and not options.json:
        print_guidance(project_dir, concise=concise)


def print_profile_policy_if_needed(profile: object, options: CliOptions, *, file=None) -> None:
    if not options.quiet and not options.json:
        print_profile_policy(profile, file=file)


def confirmation_accepted(value: object, *, expected_name: str | None = None) -> bool:
    if expected_name is None:
        return bool(value)
    return str(value or "") == expected_name


def normalize_format(value: str, *, allowed: Sequence[str], command: str) -> str:
    if value not in allowed:
        raise CliUsageError(
            "LF_FORMAT_UNSUPPORTED",
            "Output format is not supported for this command",
            f"`{command}` supports: {', '.join(allowed)}.",
            fix=f"Run `{command} --format {allowed[0]}`.",
        )
    return value


def compact_cell(value: object, *, limit: int = 80, no_truncate: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if not no_truncate and len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def row_matches_filter(row: dict[str, object], needle: str | None) -> bool:
    if not needle:
        return True
    lowered = needle.lower()
    return any(lowered in str(value).lower() for value in row.values())


def apply_table_options(rows: list[dict[str, object]], args: argparse.Namespace, key: str) -> tuple[list[str], list[dict[str, object]]]:
    default_columns = TABLE_DEFAULT_COLUMNS[key]
    raw_columns = getattr(args, "columns", None)
    columns = [part.strip() for part in raw_columns.split(",") if part.strip()] if raw_columns else default_columns
    unknown = [column for column in columns if rows and column not in rows[0]]
    if unknown:
        raise CliUsageError(
            "LF_COLUMN_UNKNOWN",
            "Unknown table column",
            f"Unknown column(s): {', '.join(unknown)}.",
            fix=f"Use one of: {', '.join(rows[0].keys())}.",
        )
    filtered = [row for row in rows if row_matches_filter(row, getattr(args, "filter", None))]
    sort_key = getattr(args, "sort", None)
    if sort_key:
        if filtered and sort_key not in filtered[0]:
            raise CliUsageError(
                "LF_SORT_UNKNOWN",
                "Unknown sort column",
                f"`{sort_key}` is not a known column.",
                fix=f"Use one of: {', '.join(filtered[0].keys())}.",
            )
        filtered = sorted(filtered, key=lambda row: str(row.get(sort_key) or ""))
    return columns, filtered


def print_table_rows(
    rows: list[dict[str, object]],
    args: argparse.Namespace,
    *,
    key: str,
    title: str | None = None,
) -> None:
    columns, selected = apply_table_options(rows, args, key)
    fmt = str(getattr(args, "format", "text"))
    if fmt == "json":
        print_json_payload({"ok": True, "columns": columns, "rows": selected})
        return
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        if not getattr(args, "no_headers", False):
            writer.writeheader()
        for row in selected:
            writer.writerow(row)
        print(buffer.getvalue(), end="")
        return
    if title:
        print(title)
    no_truncate = bool(getattr(args, "no_truncate", False))
    if not getattr(args, "no_headers", False):
        print(" | ".join(columns))
    for row in selected:
        print(" | ".join(compact_cell(row.get(column), no_truncate=no_truncate) for column in columns))


def print_grouped_help() -> None:
    print("LoopForge")
    print("Portable agentic workflow loops.")
    print("`loopforge run` is the cockpit: it resumes the active run and advances one approved stage at a time.")
    print()
    groups = [
        ("Start", [("init", "Prepare this project"), ("run", "Create or resume a staged run")]),
        (
            "Work",
            [
                ("status", "See where you are"),
                ("continue", "Execute implementation after plan approval"),
                ("verify", "Generate patch and run deterministic checks"),
                ("learn", "Propose or approve memory"),
            ],
        ),
        (
            "Inspect",
            [
                ("guide", "Explain the next action"),
                ("dashboard", "Show operator health"),
                ("runs", "List known runs"),
            ],
        ),
        (
            "Configure",
            [
                ("pack", "List or detect packs"),
                ("metrics", "Record or summarize metrics"),
                ("version", "Show runtime details"),
            ],
        ),
        (
            "Automation",
            [
                ("shell", "Open the interactive shell"),
                ("completion", "Print shell completion script"),
            ],
        ),
    ]
    for title, commands in groups:
        print(title)
        for command, description in commands:
            print(f"  {command:<10} {description}")
        print()
    print('Examples')
    print('  loopforge init')
    print('  loopforge run --task "Describe the task"')
    print('  loopforge run')
    print('  loopforge status')
    print()
    print("Run `loopforge help <command>` or `loopforge --help` for full argparse help.")


def pack_kind(source: object, project_dir: Path) -> str:
    if not source:
        return "bundled"
    path = Path(str(source))
    try:
        resolved = path.resolve()
    except OSError:
        return "unknown"
    project_pack_root = (project_dir / ".loopforge" / "packs").resolve()
    bundled_pack_root = (repository_root() / ".loopforge" / "packs").resolve()
    try:
        resolved.relative_to(project_pack_root)
        return "local override"
    except ValueError:
        pass
    try:
        resolved.relative_to(bundled_pack_root)
        return "bundled"
    except ValueError:
        return "local"


def detection_reason(pack: dict[str, object], project_dir: Path) -> str:
    detection = pack.get("detection", {})
    if not isinstance(detection, dict):
        return "default pack"
    for key in ("files_any", "all_files"):
        values = detection.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and (project_dir / value).exists():
                    return f"{value} found"
    for key in ("dirs_any", "all_dirs"):
        values = detection.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and (project_dir / value).is_dir():
                    return f"{value} directory found"
    return "fallback default"


def next_command(project_dir: Path, fallback: str | None = None) -> str | None:
    guidance = current_guidance(project_dir)
    if guidance.recommended_actions:
        return guidance.recommended_actions[0].command
    return fallback


def print_runs_text(result: object, args: argparse.Namespace) -> None:
    rows = run_rows_from_result(result)
    current = getattr(result, "current_run_id", None) or "none"
    if not rows:
        print("No runs yet")
        print()
        print("Next")
        print('loopforge run --task "Describe the task"')
        return
    latest = rows[0]
    print("Runs")
    print(f"total    {len(rows)}")
    print(f"current  {current}")
    print(f"latest   {latest.get('status') or 'unknown'}")
    print()
    print_table_rows(rows, args, key="runs", title=None)


def render_continue_result(renderer: TerminalRenderer, result: object, *, details: bool = False) -> None:
    ok = bool(getattr(result, "ok", False))
    attempt = getattr(result, "attempt", None)
    contract = getattr(result, "contract", None)
    rows: list[tuple[str, object]] = []
    title = "Attempt completed" if ok else "Attempt blocked"
    if isinstance(attempt, dict):
        rows.extend(
            [
                ("attempt", attempt.get("id") or "none"),
                ("adapter", attempt.get("adapter") or "none"),
                ("changed", yes_no(attempt.get("workspace_changed"))),
                ("status", attempt.get("status") or "unknown"),
            ]
        )
    elif isinstance(contract, dict):
        title = "Contract validation" if ok else "Contract blocked"
        rows.extend(
            [
                ("contract", contract.get("status") or "unknown"),
                ("checks", len(contract.get("success_checks", []))),
                ("adapter", "not executed"),
            ]
        )
    else:
        rows.append(("status", "completed" if ok else "blocked"))
    blockers = list(getattr(result, "blockers", []) or [])
    if blockers:
        rows.append(("reason", compact_text(blockers[0], limit=90)))
    next_value = next_command(Path.cwd(), "loopforge verify" if ok else "loopforge status")
    if ok:
        render_success(renderer, title, rows, next_command=next_value)
    else:
        render_blocked(renderer, title, rows, blockers=blockers, next_command=next_value)
        print_latest_adapter_error(result, output=sys.stderr)
    if details and getattr(result, "run_dir", None) is not None:
        print(f"run directory: {getattr(result, 'run_dir')}")


def render_verify_result(renderer: TerminalRenderer, result: object, *, details: bool = False) -> None:
    ok = bool(getattr(result, "ok", False))
    verification = getattr(result, "verification", None)
    rows: list[tuple[str, object]] = [("status", "passed" if ok else "failed")]
    if isinstance(verification, dict):
        patch = verification.get("patch", {})
        risk = verification.get("risk", {})
        if isinstance(patch, dict):
            rows.append(("patch", patch.get("path") or "none"))
            if details:
                rows.append(("patch bytes", patch.get("size_bytes", 0)))
        if isinstance(risk, dict):
            rows.append(("risk", risk.get("risk") or "unknown"))
            if details and risk.get("policy"):
                rows.append(("risk policy", risk["policy"]))
        rows.append(
            (
                "checks",
                f"{verification.get('checks_passed', 0)}/{verification.get('checks_total', 0)} passed",
            )
        )
    blockers = list(getattr(result, "blockers", []) or [])
    if blockers:
        rows.append(("blocking check", compact_text(blockers[0], limit=90)))
    next_value = next_command(Path.cwd(), "loopforge learn" if ok else "loopforge verify")
    if ok:
        render_success(renderer, "Verified", rows, next_command=next_value)
    else:
        render_blocked(renderer, "Verification failed", rows, blockers=blockers, next_command=next_value)


def render_learn_result(renderer: TerminalRenderer, result: object, *, approved: bool) -> None:
    pending = sum(
        1
        for proposal in getattr(result, "proposals", []) or []
        if isinstance(proposal, dict) and proposal.get("status") == "pending"
    )
    rows = [
        ("pending", pending),
        ("promoted", len(getattr(result, "promoted", []) or [])),
        ("rejected", len(getattr(result, "rejected", []) or [])),
    ]
    proposal_path = getattr(result, "proposal_path", None)
    if proposal_path is not None:
        rows.append(("file", proposal_path))
    if not approved:
        rows.append(("promoted now", "0 (not approved)"))
    blockers = list(getattr(result, "blockers", []) or [])
    next_value = "loopforge learn --approve" if pending else next_command(Path.cwd(), "loopforge status")
    title = "Memory promoted" if approved and not blockers else "Memory proposals ready"
    if getattr(result, "ok", False):
        render_success(renderer, title, rows, next_command=next_value)
    else:
        render_blocked(renderer, "Memory blocked", rows, blockers=blockers, next_command=next_value)


def version_payload(project_dir: Path) -> dict[str, object]:
    config_path = project_config_path(project_dir)
    default_adapter: object = "unknown"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            default_adapter = config.get("default_adapter") or DEFAULT_ADAPTER
        except (OSError, json.JSONDecodeError):
            default_adapter = "unreadable"
    return {
        "loopforge_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "project_dir": str(project_dir),
        "config_path": str(config_path),
        "loopforge_home": str(loopforge_home()),
        "default_adapter": default_adapter,
        "git_commit": "unknown",
    }


def print_version(project_dir: Path, fmt: str) -> None:
    payload = version_payload(project_dir)
    if fmt == "json":
        print_json_payload({"ok": True, "version": payload})
        return
    print(f"LoopForge {payload['loopforge_version']}")
    print(f"python: {payload['python']}")
    print(f"platform: {payload['platform']}")
    print(f"executable: {payload['executable']}")
    print(f"project dir: {payload['project_dir']}")
    print(f"config path: {payload['config_path']}")
    print(f"LoopForge home: {payload['loopforge_home']}")
    print(f"default adapter: {payload['default_adapter']}")
    print(f"git commit: {payload['git_commit']}")


def parser_topics(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], argparse.ArgumentParser]:
    topics = getattr(parser, "_loopforge_topics", {})
    return topics if isinstance(topics, dict) else {}


def show_help(parser: argparse.ArgumentParser, topic: Sequence[str]) -> None:
    topics = parser_topics(parser)
    key = tuple(topic)
    selected = topics.get(key)
    if selected is not None:
        print(selected.format_help(), end="")
        return
    candidates = [" ".join(parts) for parts in topics if parts]
    requested = " ".join(topic)
    suggestion = difflib.get_close_matches(requested, candidates, n=1)
    fix = f"Run `loopforge help {suggestion[0]}`." if suggestion else "Run `loopforge help`."
    raise CliUsageError(
        "LF_HELP_TOPIC_UNKNOWN",
        "Help topic was not found",
        f"`{requested or 'root'}` is not a known LoopForge command.",
        fix=fix,
    )


def completion_script(shell: str) -> str:
    commands = " ".join(
        [
            "init",
            "run",
            "status",
            "guide",
            "dashboard",
            "pack",
            "metrics",
            "continue",
            "verify",
            "learn",
            "shell",
            "interactive",
            "projects",
            "open",
            "runs",
            "version",
            "help",
            "completion",
        ]
    )
    flags = "--no-color --no-input --quiet --debug --json --version -V --help"
    if shell == "bash":
        return (
            "_loopforge_complete() {\n"
            "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
            f"  COMPREPLY=( $(compgen -W \"{commands} {flags}\" -- \"$cur\") )\n"
            "}\n"
            "complete -F _loopforge_complete loopforge\n"
        )
    if shell == "zsh":
        words = " ".join(commands.split() + flags.split())
        return f"#compdef loopforge\n_arguments '*::arg:(({words}))'\n"
    if shell == "fish":
        lines = [f"complete -c loopforge -f -a '{commands}'"]
        for flag in flags.split():
            lines.append(f"complete -c loopforge -l {flag.removeprefix('--')} -f")
        return "\n".join(lines) + "\n"
    powershell_items = "', '".join(commands.split() + flags.split())
    return (
        "Register-ArgumentCompleter -Native -CommandName loopforge -ScriptBlock {\n"
        "  param($wordToComplete)\n"
        f"  @('{powershell_items}') |\n"
        "    Where-Object { $_ -like \"$wordToComplete*\" } |\n"
        "    ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }\n"
        "}\n"
    )


def guidance_payload(project_dir: Path) -> dict[str, object]:
    guidance = current_guidance(project_dir)
    return {
        "summary": guidance.summary,
        "priority": guidance.priority,
        "diagnostics": guidance.diagnostics,
        "blocked_reasons": guidance.blocked_reasons,
        "evidence": guidance.evidence,
        "recommended_actions": [
            {
                "id": action.id,
                "label": action.label,
                "command": action.command,
                "why": action.why,
                "requires_confirmation": action.requires_confirmation,
            }
            for action in guidance.recommended_actions
        ],
    }


def status_payload(project_dir: Path) -> dict[str, object]:
    result = current_status(project_dir)
    return {
        "project_dir": str(result.project_dir),
        "initialized": result.initialized,
        "config_path": str(result.config_path),
        "config": result.config,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "run": result.run,
        "next_step": result.next_step,
        "blockers": result.blockers,
        "native_artifacts": result.native_artifacts,
        "legacy_artifacts": result.legacy_artifacts,
        "loop_contract": result.loop_contract,
        "verification": result.verification,
        "memory": result.memory,
    }


def run_has_explicit_source(args: argparse.Namespace) -> bool:
    return bool(str(getattr(args, "task", "") or "").strip()) or bool(
        str(getattr(args, "issue_source", "") or "").strip()
    )


def render_run_cockpit(
    project_dir: Path,
    renderer: TerminalRenderer,
    *,
    fmt: str,
    quiet: bool,
) -> None:
    if fmt == "json":
        print_json_payload(
            {
                "ok": True,
                "action": "active_run",
                "status": status_payload(project_dir),
                "guidance": guidance_payload(project_dir),
            }
        )
        return
    if quiet:
        return
    result = current_status(project_dir)
    guidance = current_guidance(project_dir)
    print("Active run found; showing cockpit.")
    render_status(renderer, result, guidance, details=True)


def render_stage_result(
    renderer: TerminalRenderer,
    result: object,
) -> None:
    stage = getattr(result, "stage", None) or "stage"
    if getattr(result, "ok", False):
        render_success(
            renderer,
            f"{str(stage).title()} ready",
            [
                ("stage", stage),
                ("status", getattr(result, "message", "")),
                ("artifact", getattr(result, "artifact_path", None) or "none"),
            ],
            next_command="loopforge run",
        )
        return
    render_blocked(
        renderer,
        f"{str(stage).title()} blocked",
        [("status", getattr(result, "message", ""))],
        blockers=list(getattr(result, "blockers", []) or []),
        next_command="loopforge run",
    )


def render_plan_approval_result(
    renderer: TerminalRenderer,
    result: object,
) -> None:
    if getattr(result, "ok", False):
        render_success(
            renderer,
            "Plan approved",
            [
                ("status", getattr(result, "message", "")),
                ("artifact", getattr(result, "artifact_path", None) or "none"),
            ],
            next_command="loopforge continue",
        )
        return
    render_blocked(
        renderer,
        "Plan approval blocked",
        [("status", getattr(result, "message", ""))],
        blockers=list(getattr(result, "blockers", []) or []),
        next_command="loopforge run",
    )


def render_review_approval_result(
    renderer: TerminalRenderer,
    result: object,
) -> None:
    if getattr(result, "ok", False):
        render_success(
            renderer,
            "Review approved",
            [
                ("status", getattr(result, "message", "")),
                ("artifact", getattr(result, "artifact_path", None) or "none"),
            ],
            next_command="loopforge run",
        )
        return
    render_blocked(
        renderer,
        "Review approval blocked",
        [("status", getattr(result, "message", ""))],
        blockers=list(getattr(result, "blockers", []) or []),
        next_command="loopforge run",
    )


def render_publication_result(
    renderer: TerminalRenderer,
    result: object,
) -> None:
    if getattr(result, "ok", False):
        render_success(
            renderer,
            "Draft publication prepared",
            [
                ("status", getattr(result, "message", "")),
                ("artifact", getattr(result, "artifact_path", None) or "none"),
            ],
            next_command="loopforge run",
        )
        return
    render_blocked(
        renderer,
        "Draft publication blocked",
        [("status", getattr(result, "message", ""))],
        blockers=list(getattr(result, "blockers", []) or []),
        next_command="loopforge run",
    )


def maybe_run_readonly_stage_from_cockpit(
    project_dir: Path,
    renderer: TerminalRenderer,
    *,
    adapter: str,
    adapter_args: list[str],
    no_color: bool,
) -> int:
    status = current_status(project_dir)
    if status.run is None:
        return 0
    stage = next_readonly_stage(status.run)
    if stage is None:
        statuses = status.run.get("stage_statuses", {})
        if not isinstance(statuses, dict):
            return 0
        if statuses.get("plan") == "awaiting_approval":
            if not prompt_yes_no("Approve current plan for implementation", default=False):
                return 0
            result = approve_plan(project_dir, source="local")
            render_plan_approval_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=no_color),
                result,
            )
            return 0 if result.ok else 1
        if (
            statuses.get("verification") == "complete"
            and statuses.get("review") == "complete"
        ):
            if not prompt_yes_no("Approve completed review for draft preparation", default=False):
                return 0
            result = approve_review(project_dir, source="local")
            render_review_approval_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=no_color),
                result,
            )
            return 0 if result.ok else 1
        eligibility = status.run.get("publish_eligibility", {})
        if (
            statuses.get("publication") != "draft_prepared"
            and isinstance(eligibility, dict)
            and eligibility.get("eligible") is True
            and eligibility.get("mode") == "draft"
        ):
            if not prompt_yes_no("Prepare draft PR publication artifact", default=False):
                return 0
            result = prepare_draft_publication(project_dir)
            render_publication_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=no_color),
                result,
            )
            return 0 if result.ok else 1
        return 0
    if not prompt_yes_no(f"Run read-only {stage} with {adapter} now", default=False):
        return 0
    with renderer.loading(f"Running read-only {stage} with {adapter}..."):
        result = execute_readonly_stage(
            project_dir,
            stage=stage,
            adapter=adapter,
            adapter_args=adapter_args,
        )
    render_stage_result(
        renderer if result.ok else TerminalRenderer(sys.stderr, no_color=no_color),
        result,
    )
    return 0 if result.ok else 1


def run_rows_from_result(result: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    runs = getattr(result, "runs", [])
    current_run_id = getattr(result, "current_run_id", None)
    for run in runs:
        if not isinstance(run, dict):
            continue
        rows.append(
            {
                "current": "*" if run.get("run_id") == current_run_id or run.get("current") else "",
                "run_id": run.get("run_id") or "",
                "status": run.get("status") or "unknown",
                "task": run.get("task") or "",
                "pack": run.get("pack") or "",
                "attempts": run.get("attempt_count", ""),
                "verification": run.get("verification", ""),
                "created_at": run.get("created_at") or "",
                "updated_at": run.get("updated_at") or "",
            }
        )
    return rows


def global_run_rows_from_result(result: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in getattr(result, "runs", []):
        if not isinstance(run, dict):
            continue
        rows.append(
            {
                "project": run.get("project") or "",
                "project_id": run.get("project_id") or "",
                "project_path": run.get("project_path") or "",
                "current": "*" if run.get("current") else "",
                "run_id": run.get("run_id") or "",
                "attention": run.get("attention") or "ready",
                "status": run.get("status") or "unknown",
                "task": run.get("task") or "",
                "pack": run.get("pack") or "",
                "updated_at": run.get("updated_at") or "",
            }
        )
    return rows


def project_rows(result: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for project in getattr(result, "projects", []):
        if not isinstance(project, dict):
            continue
        rows.append(
            {
                "attention": project.get("attention") or "ready",
                "name": project.get("name") or "",
                "project_id": project.get("project_id") or "",
                "branch": project.get("branch") or "",
                "profile": project.get("profile") or "",
                "run_count": project.get("run_count") or 0,
                "last_activity": project.get("last_activity") or "",
                "path": project.get("path") or "",
            }
        )
    return rows


def metrics_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    rows = summary.get("runs", [])
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(
                {
                    "run_id": row.get("run_id") or "",
                    "duration_seconds": format_metric_value(row.get("duration_seconds")),
                    "attempt_count": format_metric_value(row.get("attempt_count")),
                    "patch_size_bytes": format_metric_value(row.get("patch_size_bytes")),
                    "verification": format_metric_value(row.get("verification")),
                    "final_disposition": format_metric_value(row.get("final_disposition")),
                }
            )
    return normalized


def print_latest_adapter_error(result: object, *, output) -> None:
    if getattr(result, "ok", True):
        return
    attempt = getattr(result, "attempt", None)
    run_dir = getattr(result, "run_dir", None)
    if not isinstance(attempt, dict) or run_dir is None:
        return
    stderr_path = attempt.get("stderr_path")
    if not stderr_path:
        return
    path = Path(str(run_dir)) / str(stderr_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return
    if not text:
        return
    print("", file=output)
    print("Adapter diagnostic", file=output)
    print(f"log      {path}", file=output)
    print(f"summary  {adapter_error_summary(text)}", file=output)
    useful_lines = useful_adapter_error_lines(text)
    if useful_lines:
        print("signals", file=output)
        for line in useful_lines:
            print(f"- {line}", file=output)
    print("raw      loopforge shell --command \"/raw latest stderr\"", file=output)


def adapter_error_summary(text: str) -> str:
    lowered = text.lower()
    if "sandbox" in lowered and "approval policy" in lowered:
        return "The adapter hit a sandbox boundary while approval escalation was disabled."
    if "sandbox" in lowered:
        return "The adapter hit a sandbox boundary."
    if "permission" in lowered or "access is denied" in lowered or "denied" in lowered:
        return "The adapter hit a filesystem permission boundary."
    if "could not" in lowered or "cannot" in lowered or "failed" in lowered:
        return "The adapter reported an execution failure."
    return "The adapter wrote diagnostics to stderr."


def useful_adapter_error_lines(text: str, *, limit: int = 4) -> list[str]:
    markers = (
        "access is denied",
        "approval",
        "blocked",
        "cannot",
        "could not",
        "denied",
        "error",
        "failed",
        "not allowed",
        "permission",
        "sandbox",
        "traceback",
    )
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().lstrip("> ").split())
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            lines.append(compact_text(line, limit=130))
    if not lines:
        for raw_line in text.splitlines()[-limit:]:
            line = " ".join(raw_line.strip().lstrip("> ").split())
            if line and "tokens used" not in line.lower():
                lines.append(compact_text(line, limit=130))
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
        if len(deduped) >= limit:
            break
    return deduped


def format_metric_value(value: object) -> str:
    return "unknown" if value is None else str(value)


def print_metrics_record(record: dict[str, object], record_path: Path) -> None:
    print(f"metrics record: {record_path}")
    print(f"run id: {record.get('run_id')}")
    timing = record.get("timing", {})
    if isinstance(timing, dict):
        print(f"duration seconds: {format_metric_value(timing.get('duration_seconds'))}")
    adapter = record.get("adapter", {})
    if isinstance(adapter, dict):
        print(f"adapter: {format_metric_value(adapter.get('id'))}")
    model = record.get("model", {})
    if isinstance(model, dict):
        print(f"model: {format_metric_value(model.get('id'))}")
    tokens = record.get("tokens", {})
    if isinstance(tokens, dict):
        print(f"tokens: {tokens.get('status', 'unknown')}")
    cost = record.get("cost", {})
    if isinstance(cost, dict):
        print(f"cost: {cost.get('status', 'unknown')}")
    patch = record.get("patch", {})
    if isinstance(patch, dict):
        print(f"patch size bytes: {format_metric_value(patch.get('size_bytes'))}")
    verification = record.get("verification", {})
    if isinstance(verification, dict):
        print(f"verification: {format_metric_value(verification.get('status'))}")
    final = record.get("final_disposition", {})
    if isinstance(final, dict):
        print(f"final disposition: {format_metric_value(final.get('status'))}")


def print_metric_series(name: str, series: object) -> None:
    if not isinstance(series, dict):
        return
    average = series.get("average")
    if average is None:
        average_text = "unknown"
    elif isinstance(average, float):
        average_text = f"{average:.2f}".rstrip("0").rstrip(".")
    else:
        average_text = str(average)
    print(
        f"{name}: average {average_text} "
        f"(known {series.get('known_count', 0)}, unknown {series.get('unknown_count', 0)})"
    )


def print_metrics_summary(summary: dict[str, object], *, details: bool = False) -> None:
    print("Metrics summary")
    print(f"records   {summary.get('record_count', 0)}")
    duration = summary.get("duration_seconds")
    if isinstance(duration, dict):
        print(
            "duration  "
            f"avg {not_reported(average_text_for_cli(duration))}, "
            f"{duration.get('unknown_count', 0)} unknown"
        )
    attempts = summary.get("attempt_count")
    if isinstance(attempts, dict):
        print(f"attempts  avg {not_reported(average_text_for_cli(attempts))}")
    cost = summary.get("cost", {})
    if isinstance(cost, dict):
        totals = cost.get("amount_microunits_by_currency", {})
        print(f"cost      {cost.get('known_count', 0)} known, {cost.get('unknown_count', 0)} unknown")
        if isinstance(totals, dict) and totals:
            for currency, amount in totals.items():
                print(f"cost {currency}: {amount} microunits")
    verification = summary.get("verification_results", {})
    if isinstance(verification, dict):
        print("verification results:")
        for name, count in verification.items():
            print(f"- {name}: {count}")
    final = summary.get("final_dispositions", {})
    if isinstance(final, dict):
        print("final dispositions:")
        for name, count in final.items():
            print(f"- {name}: {count}")
    if isinstance(cost, dict) and (cost.get("unknown_count", 0) or 0) > (cost.get("known_count", 0) or 0):
        print()
        print("Signal")
        print("Cost and token reporting are incomplete.")
    if not details:
        return
    runs = summary.get("runs", [])
    if isinstance(runs, list) and runs:
        print("runs:")
        for run in runs:
            if not isinstance(run, dict):
                continue
            print(
                "- "
                f"{run.get('run_id')}: "
                f"duration={format_metric_value(run.get('duration_seconds'))}, "
                f"attempts={format_metric_value(run.get('attempt_count'))}, "
                f"patch={format_metric_value(run.get('patch_size_bytes'))}, "
                f"verification={format_metric_value(run.get('verification'))}, "
                f"disposition={format_metric_value(run.get('final_disposition'))}"
            )


def average_text_for_cli(series: dict[str, object]) -> str:
    average = series.get("average")
    if average is None:
        return "unknown"
    if isinstance(average, float):
        return f"{average:.2f}".rstrip("0").rstrip(".")
    return str(average)


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser through the extracted parser builder."""

    return CliParserBuilder().build()


def main(argv: list[str] | None = None) -> int:
    from loopforge.cli.app import LoopForgeCli

    return LoopForgeCli(sys.modules[__name__]).run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
