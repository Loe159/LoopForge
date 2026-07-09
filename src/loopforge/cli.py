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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from loopforge import __version__
from loopforge.engine import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_ADAPTER,
    DEFAULT_PROFILE,
    SUPPORTED_ADAPTERS,
    continue_run,
    create_run,
    current_guidance,
    current_status,
    dashboard_snapshot,
    detect_project_pack,
    discover_pack_contracts,
    initialize_project,
    learn_run,
    list_runs,
    load_pack_checks,
    loopforge_home,
    normalize_profile,
    platform_cache_home,
    profile_permission_lines,
    project_config_path,
    record_run_metrics,
    repository_root,
    summarize_run_metrics,
    task_looks_subjective,
    verify_run,
)
from loopforge.ui import (
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


DOCS_URL = "https://github.com/loopforge/loopforge#readme"
GLOBAL_FLAGS = {
    "--no-color",
    "--no-input",
    "--quiet",
    "--debug",
    "--version",
    "-V",
    "--json",
}
TABLE_DEFAULT_COLUMNS = {
    "pack-list": ["current", "name", "description", "kind", "source"],
    "runs": ["current", "run_id", "status", "task", "pack", "updated_at"],
    "metrics-runs": ["run_id", "duration_seconds", "attempt_count", "patch_size_bytes", "verification", "final_disposition"],
}


@dataclass(frozen=True)
class CliOptions:
    no_color: bool = False
    no_input: bool = False
    quiet: bool = False
    debug: bool = False
    version: bool = False
    json: bool = False


@dataclass(frozen=True)
class GitHubIssueRef:
    owner: str
    repo: str
    number: int
    url: str


@dataclass
class RunIntake:
    task: str
    success_checks: list[str]
    allowed_tools: list[str]
    subjective_rubric: str = ""
    source_metadata: dict[str, Any] | None = None
    notes: list[str] | None = None


@dataclass
class IssueReadResult:
    ok: bool
    issue: dict[str, Any] | None = None
    reason: str = ""


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


def parse_github_remote(remote: str) -> tuple[str, str] | None:
    patterns = (
        r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
        r"^git@github\.com:(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.match(pattern, remote.strip())
        if match:
            return match.group("owner"), match.group("repo")
    return None


def github_repo_from_remote(project_dir: Path) -> tuple[str, str] | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_github_remote(result.stdout.strip())


def parse_github_issue_url(source: str) -> GitHubIssueRef | None:
    match = re.match(
        r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/(?P<number>\d+)(?:[/?#].*)?$",
        source.strip(),
    )
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    number = int(match.group("number"))
    return GitHubIssueRef(
        owner=owner,
        repo=repo,
        number=number,
        url=f"https://github.com/{owner}/{repo}/issues/{number}",
    )


def resolve_github_issue_ref(project_dir: Path, source: str) -> tuple[GitHubIssueRef | None, str]:
    parsed = parse_github_issue_url(source)
    if parsed is not None:
        return parsed, ""
    if source.strip().isdigit():
        repo = github_repo_from_remote(project_dir)
        if repo is None:
            return None, "GitHub issue ID could not be resolved because the origin remote is missing or not GitHub."
        owner, name = repo
        number = int(source.strip())
        return (
            GitHubIssueRef(
                owner=owner,
                repo=name,
                number=number,
                url=f"https://github.com/{owner}/{name}/issues/{number}",
            ),
            "",
        )
    return None, "Only GitHub issue URLs and numeric issue IDs are supported right now."


def gh_issue_view(ref: GitHubIssueRef) -> IssueReadResult:
    if shutil.which("gh") is None:
        return IssueReadResult(False, reason="GitHub CLI (`gh`) is not available.")
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(ref.number),
                "--repo",
                f"{ref.owner}/{ref.repo}",
                "--json",
                "number,title,body,url,labels",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return IssueReadResult(False, reason=f"GitHub issue read failed: {error}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return IssueReadResult(False, reason=detail or "GitHub issue read failed.")
    try:
        issue = json.loads(result.stdout)
    except json.JSONDecodeError:
        return IssueReadResult(False, reason="GitHub returned unreadable issue data.")
    issue.setdefault("url", ref.url)
    issue.setdefault("number", ref.number)
    return IssueReadResult(True, issue=issue)


def gh_issue_list(project_dir: Path) -> IssueReadResult:
    repo = github_repo_from_remote(project_dir)
    if repo is None:
        return IssueReadResult(False, reason="Open issues require a GitHub origin remote.")
    if shutil.which("gh") is None:
        return IssueReadResult(False, reason="GitHub CLI (`gh`) is not available.")
    owner, name = repo
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                f"{owner}/{name}",
                "--state",
                "open",
                "--limit",
                "20",
                "--json",
                "number,title,url,labels",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return IssueReadResult(False, reason=f"GitHub issue list failed: {error}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return IssueReadResult(False, reason=detail or "GitHub issue list failed.")
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return IssueReadResult(False, reason="GitHub returned unreadable issue data.")
    return IssueReadResult(True, issue={"issues": issues})


def issue_task_summary(issue: dict[str, Any]) -> str:
    title = str(issue.get("title") or "").strip()
    number = issue.get("number")
    if number:
        return f"Resolve GitHub issue #{number}: {title}" if title else f"Resolve GitHub issue #{number}"
    return title or "Resolve GitHub issue"


def issue_source_metadata(ref: GitHubIssueRef, issue: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str((issue or {}).get("title") or "").strip()
    return {
        "type": "github_issue",
        "provider": "github",
        "reference": f"{ref.owner}/{ref.repo}#{ref.number}",
        "url": ref.url,
        "title": title,
        "trust": "untrusted_provider_input",
        "memory": "not_promoted_to_durable_memory",
    }


def pack_check_suggestions(project_dir: Path, pack: str | None) -> list[tuple[str, str]]:
    contract = detect_project_pack(project_dir) if pack is None else {"name": pack}
    pack_name = str(contract.get("name") or pack or "")
    try:
        checks = load_pack_checks(project_dir, pack_name).get("checks", [])
    except ValueError:
        checks = []
    suggestions: list[tuple[str, str]] = []
    for check in checks[:3]:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name") or "pack check").strip()
        command = check.get("command", [])
        command_text = " ".join(str(part) for part in command) if isinstance(command, list) else ""
        suggestions.append(
            (
                f"Pack check `{name}` passes",
                f"Selected because the detected `{pack_name}` pack defines `{command_text}`.",
            )
        )
    if not suggestions:
        suggestions.append(
            (
                "Run the relevant local deterministic checks before verification",
                "Selected because no pack-specific check command is configured.",
            )
        )
    return suggestions


def permission_suggestions() -> list[tuple[str, str]]:
    return [
        (tool, "Default LoopForge run permission; bounded by the run workspace and profile policy.")
        for tool in DEFAULT_ALLOWED_TOOLS
    ]


def confirm_or_edit_list(
    title: str,
    suggestions: list[tuple[str, str]],
    *,
    default_values: list[str] | None = None,
) -> list[str]:
    print(title)
    for index, (value, reason) in enumerate(suggestions, start=1):
        print(f"{index}. {value}")
        print(f"   why: {reason}")
    values = default_values if default_values is not None else [value for value, _ in suggestions]
    if prompt_yes_no("Use these", default=True):
        return values
    edited = prompt_text("Enter replacements separated by commas", required=False)
    return split_csv_prompt(edited) or values


def build_manual_intake(
    project_dir: Path,
    args: argparse.Namespace,
    *,
    default_task: str = "",
    source_metadata: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> RunIntake:
    task = prompt_text("Title or goal", default=default_task)
    context = prompt_text("Bug context", required=False)
    proof = prompt_text("Proof of success")
    task_text = task if not context else f"{task}\n\nContext: {context}"
    checks = [proof, *list(args.success_check)]
    pack_checks = pack_check_suggestions(project_dir, args.pack)
    if args.success_check:
        print("Using checks from --success-check.")
    else:
        checks.extend(
            confirm_or_edit_list(
                "Suggested checks",
                pack_checks,
                default_values=[value for value, _ in pack_checks],
            )
        )
    if args.allow_tool:
        allowed_tools = list(args.allow_tool)
        print("Using permissions from --allow-tool.")
    else:
        allowed_tools = confirm_or_edit_list("Suggested permissions", permission_suggestions())
    profile = current_project_profile(project_dir)
    rubric = args.rubric
    if profile == "autonomous" and task_looks_subjective(task_text) and not rubric:
        rubric = prompt_text("Subjective quality rubric")
    return RunIntake(
        task=task_text,
        success_checks=checks,
        allowed_tools=allowed_tools,
        subjective_rubric=rubric,
        source_metadata=source_metadata,
        notes=notes or [],
    )


def build_issue_intake(
    project_dir: Path,
    args: argparse.Namespace,
    ref: GitHubIssueRef,
    issue: dict[str, Any],
) -> RunIntake:
    default_task = issue_task_summary(issue)
    task = prompt_text("Run goal", default=default_task)
    proof_default = f"The behavior described in GitHub issue #{ref.number} is fixed or implemented."
    proof = prompt_text("Proof of success", default=proof_default)
    pack_checks = pack_check_suggestions(project_dir, args.pack)
    checks = [proof, *list(args.success_check)]
    if args.success_check:
        print("Using checks from --success-check.")
    else:
        checks.extend(confirm_or_edit_list("Suggested checks", pack_checks))
    if args.allow_tool:
        allowed_tools = list(args.allow_tool)
        print("Using permissions from --allow-tool.")
    else:
        allowed_tools = confirm_or_edit_list("Suggested permissions", permission_suggestions())
    profile = current_project_profile(project_dir)
    rubric = args.rubric
    if profile == "autonomous" and task_looks_subjective(task) and not rubric:
        rubric = prompt_text("Subjective quality rubric")
    return RunIntake(
        task=task,
        success_checks=checks,
        allowed_tools=allowed_tools,
        subjective_rubric=rubric,
        source_metadata=issue_source_metadata(ref, issue),
        notes=["Issue text is treated as untrusted input and was not promoted to durable memory."],
    )


def build_noninteractive_issue_intake(
    project_dir: Path,
    args: argparse.Namespace,
    ref: GitHubIssueRef,
    issue: dict[str, Any],
) -> RunIntake:
    task = args.task or issue_task_summary(issue)
    checks = list(args.success_check)
    if not checks:
        checks = [f"The behavior described in GitHub issue #{ref.number} is fixed or implemented."]
    allowed_tools = list(args.allow_tool)
    return RunIntake(
        task=task,
        success_checks=checks,
        allowed_tools=allowed_tools,
        subjective_rubric=args.rubric,
        source_metadata=issue_source_metadata(ref, issue),
    )


def choose_issue_from_list(project_dir: Path) -> tuple[GitHubIssueRef | None, dict[str, Any] | None, str]:
    listed = gh_issue_list(project_dir)
    if not listed.ok:
        return None, None, listed.reason
    issues = (listed.issue or {}).get("issues", [])
    if not isinstance(issues, list) or not issues:
        return None, None, "No open GitHub issues were returned."
    print("Open GitHub issues")
    for index, issue in enumerate(issues, start=1):
        print(f"{index}. #{issue.get('number')} {issue.get('title')}")
    choice = prompt_text("Select issue number from this list", required=False)
    if not choice.isdigit():
        return None, None, "No issue was selected."
    selected_index = int(choice)
    if selected_index < 1 or selected_index > len(issues):
        return None, None, "Issue selection was outside the displayed range."
    selected = issues[selected_index - 1]
    parsed = parse_github_issue_url(str(selected.get("url") or ""))
    if parsed is None:
        return None, None, "Selected issue did not include a supported GitHub URL."
    return parsed, selected, ""


def interactive_run_intake(project_dir: Path, args: argparse.Namespace) -> RunIntake:
    source = str(getattr(args, "issue_source", "") or "").strip()
    notes: list[str] = []
    if source:
        ref, reason = resolve_github_issue_ref(project_dir, source)
        if ref is not None:
            read = gh_issue_view(ref)
            if read.ok and read.issue is not None:
                return build_issue_intake(project_dir, args, ref, read.issue)
            notes.append(f"GitHub issue could not be read: {read.reason}")
            print(notes[-1])
            return build_manual_intake(
                project_dir,
                args,
                default_task=f"Resolve GitHub issue {ref.url}",
                source_metadata=issue_source_metadata(ref),
                notes=notes,
            )
        notes.append(reason)
        print(reason)
        return build_manual_intake(project_dir, args, notes=notes)

    print("Create a run")
    print("1. Work from an existing GitHub issue")
    print("2. Report a new bug or task")
    choice = prompt_text("Choose", default="2")
    if choice == "1":
        entered = prompt_text("GitHub issue URL or number, or leave blank to list open issues", required=False)
        if entered:
            ref, reason = resolve_github_issue_ref(project_dir, entered)
            if ref is not None:
                read = gh_issue_view(ref)
                if read.ok and read.issue is not None:
                    return build_issue_intake(project_dir, args, ref, read.issue)
                notes.append(f"GitHub issue could not be read: {read.reason}")
                print(notes[-1])
                return build_manual_intake(
                    project_dir,
                    args,
                    default_task=f"Resolve GitHub issue {ref.url}",
                    source_metadata=issue_source_metadata(ref),
                    notes=notes,
                )
            notes.append(reason)
            print(reason)
            return build_manual_intake(project_dir, args, notes=notes)
        ref, issue, reason = choose_issue_from_list(project_dir)
        if ref is not None and issue is not None:
            return build_issue_intake(project_dir, args, ref, issue)
        notes.append(reason)
        print(f"Manual fallback: {reason}")
    return build_manual_intake(project_dir, args, notes=notes)


def noninteractive_run_intake(project_dir: Path, args: argparse.Namespace) -> RunIntake:
    source = str(getattr(args, "issue_source", "") or "").strip()
    if source:
        ref, reason = resolve_github_issue_ref(project_dir, source)
        if ref is None:
            if args.task:
                return RunIntake(
                    task=str(args.task).strip(),
                    success_checks=list(args.success_check),
                    allowed_tools=list(args.allow_tool),
                    subjective_rubric=args.rubric,
                    source_metadata={
                        "type": "manual",
                        "source": source,
                        "trust": "operator_supplied_input",
                        "note": reason,
                    },
                )
            raise CliUsageError(
                "LF_ISSUE_SOURCE_UNRESOLVED",
                "Issue source could not be resolved",
                reason,
                fix='Pass a full GitHub issue URL or use `loopforge run --task "..."`.',
            )
        read = gh_issue_view(ref)
        if not read.ok or read.issue is None:
            if args.task:
                return RunIntake(
                    task=str(args.task).strip(),
                    success_checks=list(args.success_check),
                    allowed_tools=list(args.allow_tool),
                    subjective_rubric=args.rubric,
                    source_metadata=issue_source_metadata(ref),
                    notes=[f"GitHub issue could not be read: {read.reason}"],
                )
            raise CliUsageError(
                "LF_ISSUE_SOURCE_UNAVAILABLE",
                "Issue source could not be read",
                read.reason,
                fix='Pass `--task "..."` with the issue summary or run interactively for manual fallback.',
            )
        return build_noninteractive_issue_intake(project_dir, args, ref, read.issue)
    task = str(args.task or "").strip()
    if not task:
        raise CliUsageError(
            "LF_INPUT_REQUIRED",
            "Task description is required",
            "`loopforge run` needs a task in non-interactive mode.",
            fix='Run `loopforge run --task "Describe the task"`.',
        )
    return RunIntake(
        task=task,
        success_checks=list(args.success_check),
        allowed_tools=list(args.allow_tool),
        subjective_rubric=args.rubric,
    )


class CliError(Exception):
    def __init__(
        self,
        code: str,
        title: str,
        detail: str = "",
        *,
        fix: str | None = None,
        exit_code: int = 1,
        url: str = DOCS_URL,
    ) -> None:
        super().__init__(detail or title)
        self.code = code
        self.title = title
        self.detail = detail
        self.fix = fix
        self.exit_code = exit_code
        self.url = url


class CliUsageError(CliError):
    def __init__(self, code: str, title: str, detail: str = "", *, fix: str | None = None) -> None:
        super().__init__(code, title, detail, fix=fix, exit_code=2)


class CliRuntimeError(CliError):
    pass


class LoopForgeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(
            "LF_USAGE",
            "Invalid command line",
            message,
            fix="Run `loopforge help` or `loopforge help <command>`.",
        )


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


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def print_json_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def preparse_global_options(argv: Sequence[str]) -> tuple[CliOptions, list[str]]:
    values = {
        "no_color": False,
        "no_input": False,
        "quiet": False,
        "debug": debug_enabled_from_env(),
        "version": False,
        "json": False,
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
    print()
    groups = [
        ("Start", [("init", "Prepare this project"), ("run", "Create a bounded run")]),
        (
            "Work",
            [
                ("status", "See where you are"),
                ("continue", "Execute or validate next attempt"),
                ("verify", "Generate patch and run checks"),
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


def add_format_args(parser: argparse.ArgumentParser, *, csv_format: bool = False) -> None:
    choices = ("text", "json", "csv") if csv_format else ("text", "json")
    parser.add_argument("--format", choices=choices, default="text", help="Output format.")


def add_table_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--columns", help="Comma-separated columns to show.")
    parser.add_argument("--sort", help="Sort rows by a column.")
    parser.add_argument("--filter", help="Only show rows containing this text.")
    parser.add_argument("--no-headers", action="store_true", help="Omit table or CSV headers.")
    parser.add_argument("--no-truncate", action="store_true", help="Do not truncate text columns.")


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
    parser = LoopForgeArgumentParser(
        prog="loopforge",
        description="LoopForge is a portable agentic workflow engine.",
        epilog=(
            "Workflow: loopforge init -> loopforge run --task \"...\" "
            "-> loopforge continue -> loopforge verify -> loopforge learn\n\n"
            "Global flags: --no-color --no-input --quiet --debug --json --version -V\n"
            "Examples:\n"
            "  loopforge init\n"
            "  loopforge run --task \"Add status output\" --success-check \"tests pass\"\n"
            "  loopforge continue --adapter codex -- -m gpt-5\n"
            "  loopforge status --format json\n"
            f"More: {DOCS_URL}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics: dict[tuple[str, ...], argparse.ArgumentParser] = {(): parser}
    subcommands = parser.add_subparsers(dest="command")

    init_parser = subcommands.add_parser(
        "init",
        help="Initialize LoopForge metadata for a project.",
        epilog="Example:\n  loopforge init --profile supervised",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("init",)] = init_parser
    init_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=("assist", "supervised", "autonomous", "strict"),
        help="Autonomy profile to store in .loopforge/config.json.",
    )
    add_format_args(init_parser)

    run_parser = subcommands.add_parser(
        "run",
        help="Create a LoopForge run for a task.",
        epilog=(
            "Examples:\n"
            "  loopforge run --task \"Improve the CLI help\"\n"
            "  loopforge run --task \"Refactor parser\" --success-check \"pytest passes\"\n"
            "  loopforge run --task \"Improve copy\" --rubric \"Clear and accurate\"\n"
            "  loopforge run --task \"Add checks\" --pack python --skill tests"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("run",)] = run_parser
    run_parser.add_argument(
        "issue_source",
        nargs="?",
        help="Optional GitHub issue URL or issue ID inferred from the current git remote.",
    )
    run_parser.add_argument(
        "--task",
        help="Task description for the run.",
    )
    run_parser.add_argument(
        "--pack",
        help="Project pack to use. Defaults to automatic project detection.",
    )
    run_parser.add_argument(
        "--success-check",
        action="append",
        default=[],
        help="Objective check required before an autonomous continuation.",
    )
    run_parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Selected LoopForge skill for this run. Can be passed more than once.",
    )
    run_parser.add_argument(
        "--allow-tool",
        action="append",
        default=[],
        help="Allowed tool or command family for this run. Can be passed more than once.",
    )
    run_parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum bounded attempts allowed by the loop contract.",
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Maximum wall-clock seconds allowed by the loop contract.",
    )
    run_parser.add_argument(
        "--rubric",
        default="",
        help="Subjective quality rubric required before autonomous subjective work.",
    )
    add_format_args(run_parser)

    status_parser = subcommands.add_parser(
        "status",
        help="Show the current LoopForge loop state.",
        epilog="Examples:\n  loopforge status\n  loopforge status --details\n  loopforge status --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("status",)] = status_parser
    status_parser.add_argument(
        "--details",
        action="store_true",
        help="Show detailed paths, profile policy, artifacts, and verification evidence.",
    )
    add_format_args(status_parser)
    guide_parser = subcommands.add_parser(
        "guide",
        help="Explain the current workflow state and recommended next actions.",
        epilog="Examples:\n  loopforge guide\n  loopforge guide --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("guide",)] = guide_parser
    add_format_args(guide_parser)
    dashboard_parser = subcommands.add_parser(
        "dashboard",
        help="Show a read-only local dashboard for LoopForge runs.",
        epilog="Examples:\n  loopforge dashboard\n  loopforge dashboard --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("dashboard",)] = dashboard_parser
    dashboard_parser.add_argument(
        "--details",
        action="store_true",
        help="Show attempt, proposal, and adapter comparison details.",
    )
    add_format_args(dashboard_parser)

    pack_parser = subcommands.add_parser(
        "pack",
        help="List or detect LoopForge project packs.",
        epilog="Examples:\n  loopforge pack list\n  loopforge pack detect --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("pack",)] = pack_parser
    pack_subcommands = pack_parser.add_subparsers(dest="pack_command", required=True)
    pack_list = pack_subcommands.add_parser("list", help="List available project packs.")
    topics[("pack", "list")] = pack_list
    add_format_args(pack_list, csv_format=True)
    add_table_args(pack_list)
    pack_detect = pack_subcommands.add_parser("detect", help="Show the pack selected for this project.")
    topics[("pack", "detect")] = pack_detect
    add_format_args(pack_detect)

    metrics_parser = subcommands.add_parser(
        "metrics",
        help="Record or summarize compact LoopForge run metrics.",
        epilog="Examples:\n  loopforge metrics record --final-disposition complete\n  loopforge metrics summarize --format csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("metrics",)] = metrics_parser
    metrics_subcommands = metrics_parser.add_subparsers(
        dest="metrics_command",
        required=True,
    )
    metrics_record = metrics_subcommands.add_parser(
        "record",
        help="Write a compact JSON metrics record for the current or selected run.",
    )
    topics[("metrics", "record")] = metrics_record
    metrics_record.add_argument("--run-id", help="Run id to record. Defaults to current run.")
    metrics_record.add_argument("--model", help="Model id when adapter output did not report one.")
    metrics_record.add_argument("--input-tokens", type=non_negative_int)
    metrics_record.add_argument("--output-tokens", type=non_negative_int)
    metrics_record.add_argument("--total-tokens", type=non_negative_int)
    metrics_record.add_argument("--cost-microunits", type=non_negative_int)
    metrics_record.add_argument("--cost-currency")
    metrics_record.add_argument("--human-corrections", type=non_negative_int)
    metrics_record.add_argument("--final-disposition")
    add_format_args(metrics_record)
    metrics_summarize = metrics_subcommands.add_parser(
        "summarize",
        help="Compare recorded metrics across runs.",
    )
    topics[("metrics", "summarize")] = metrics_summarize
    metrics_summarize.add_argument(
        "--details",
        action="store_true",
        help="Include the per-run table in text output.",
    )
    add_format_args(metrics_summarize, csv_format=True)
    add_table_args(metrics_summarize)

    continue_parser = subcommands.add_parser(
        "continue",
        help="Validate the current loop contract and optionally execute an adapter attempt.",
        epilog=(
            "Examples:\n"
            "  loopforge continue\n"
            "  loopforge continue --adapter codex -- -m gpt-5\n"
            "  loopforge continue --confirm --adapter local-adapter-fixture -- python -c \"print('ok')\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("continue",)] = continue_parser
    continue_parser.add_argument(
        "--adapter",
        choices=SUPPORTED_ADAPTERS,
        help="Adapter to use for a bounded Phase 4 attempt.",
    )
    continue_parser.add_argument(
        "--confirm",
        nargs="?",
        const="yes",
        help="Confirm a mutating transition when the strict profile requires it.",
    )
    continue_parser.add_argument(
        "--details",
        action="store_true",
        help="Show run directory and full adapter evidence.",
    )
    continue_parser.add_argument(
        "adapter_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to the adapter command after --.",
    )
    add_format_args(continue_parser)

    verify_parser = subcommands.add_parser(
        "verify",
        help="Generate a complete patch and run deterministic pack verification.",
        epilog="Examples:\n  loopforge verify\n  loopforge verify --confirm\n  loopforge verify --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("verify",)] = verify_parser
    verify_parser.add_argument(
        "--confirm",
        nargs="?",
        const="yes",
        help="Confirm verification artifact generation when the strict profile requires it.",
    )
    verify_parser.add_argument(
        "--details",
        action="store_true",
        help="Show detailed patch and risk evidence.",
    )
    add_format_args(verify_parser)

    learn_parser = subcommands.add_parser(
        "learn",
        help="Propose or approve durable project memory updates for the current run.",
        epilog="Examples:\n  loopforge learn\n  loopforge learn --note \"Fact: this repo uses unittest\"\n  loopforge learn --approve --confirm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("learn",)] = learn_parser
    learn_parser.add_argument(
        "--approve",
        action="store_true",
        help="Promote safe proposals to durable project memory with human approval.",
    )
    learn_parser.add_argument(
        "--confirm",
        nargs="?",
        const="yes",
        help="Confirm durable memory promotion when the strict profile requires it.",
    )
    learn_parser.add_argument(
        "--note",
        action="append",
        default=[],
        help=(
            "Explicit memory candidate, such as "
            "'Fact: this repo uses unittest'. Can be passed more than once."
        ),
    )
    learn_parser.add_argument(
        "--details",
        action="store_true",
        help="Show proposal details in addition to the operator summary.",
    )
    add_format_args(learn_parser)

    shell_parser = subcommands.add_parser(
        "shell",
        aliases=("interactive",),
        help="Start the LoopForge interactive shell.",
        epilog=(
            "Examples:\n"
            "  loopforge shell\n"
            "  loopforge shell --command \"/status\"\n"
            "  loopforge shell --script commands.loopforge"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("shell",)] = shell_parser
    topics[("interactive",)] = shell_parser
    shell_parser.add_argument(
        "--command",
        dest="shell_command",
        help="Run a single interactive command, such as '/status', then exit.",
    )
    shell_parser.add_argument(
        "--script",
        type=Path,
        help="Run interactive commands from a UTF-8 script file, then exit.",
    )

    runs_parser = subcommands.add_parser(
        "runs",
        help="List known LoopForge runs for this project.",
        epilog="Examples:\n  loopforge runs\n  loopforge runs --format json\n  loopforge runs --columns run_id,status,task --filter failed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("runs",)] = runs_parser
    add_format_args(runs_parser, csv_format=True)
    add_table_args(runs_parser)

    version_parser = subcommands.add_parser(
        "version",
        help="Show LoopForge version and runtime details.",
        epilog="Examples:\n  loopforge version\n  loopforge version --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("version",)] = version_parser
    add_format_args(version_parser)

    help_parser = subcommands.add_parser(
        "help",
        help="Show help for LoopForge or a command.",
        epilog="Examples:\n  loopforge help\n  loopforge help run\n  loopforge help pack list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("help",)] = help_parser
    help_parser.add_argument("topic", nargs="*", help="Command or subcommand to explain.")

    completion_parser = subcommands.add_parser(
        "completion",
        help="Print shell completion script.",
        epilog=(
            "Examples:\n"
            "  loopforge completion bash\n"
            "  loopforge completion powershell > loopforge-completion.ps1"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    topics[("completion",)] = completion_parser
    completion_parser.add_argument("shell", choices=("bash", "zsh", "fish", "powershell"))

    setattr(parser, "_loopforge_topics", topics)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    options, argv = preparse_global_options(raw_argv)
    parser = build_parser()
    renderer = TerminalRenderer(sys.stdout, no_color=options.no_color)
    try:
        if options.version and not argv:
            print_version(Path.cwd(), "json" if options.json else "text")
            return 0
        if not argv:
            if sys.stdin.isatty() and sys.stdout.isatty() and not options.no_input:
                from loopforge.interactive import run_interactive

                return run_interactive(Path.cwd())
            if options.no_input:
                raise CliUsageError(
                    "LF_INPUT_REQUIRED",
                    "No command was provided",
                    "`--no-input` prevents LoopForge from opening the interactive shell.",
                    fix="Run `loopforge help` or pass a command such as `loopforge status`.",
                )
            print(parser.format_help(), file=sys.stderr, end="")
            return 2
        if options.version:
            print_version(Path.cwd(), "json" if options.json else "text")
            return 0
        args = parser.parse_args(argv)
        set_format_from_json_alias(args, options)

        if args.command == "help":
            topic = getattr(args, "topic", [])
            if topic:
                show_help(parser, topic)
            else:
                print_grouped_help()
            return 0
        if args.command == "version":
            print_version(Path.cwd(), output_format(args, options))
            return 0
        if args.command == "completion":
            print(completion_script(args.shell), end="")
            return 0
        if args.command in {"shell", "interactive"}:
            from loopforge.interactive import run_interactive

            if args.shell_command is None and args.script is None:
                if options.no_input:
                    raise CliUsageError(
                        "LF_INPUT_REQUIRED",
                        "Interactive shell is disabled",
                        "`--no-input` prevents opening the interactive shell.",
                        fix="Use `loopforge shell --command \"/status\"` or remove `--no-input`.",
                    )
                if not sys.stdin.isatty() or not sys.stdout.isatty():
                    raise CliUsageError(
                        "LF_INPUT_REQUIRED",
                        "LoopForge shell requires an interactive terminal",
                        "Use --command or --script when running in a non-interactive environment.",
                        fix='Run `loopforge shell --command "/status"`.',
                    )
            return run_interactive(Path.cwd(), command=args.shell_command, script=args.script)
        if args.command == "init":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge init")
            result = initialize_project(Path.cwd(), profile=args.profile)
            if result.created:
                action = "initialized"
            elif result.repaired:
                action = "repaired"
            else:
                action = "already initialized"
            if fmt == "json":
                print_json_payload(
                    {
                        "ok": True,
                        "action": action,
                        "config_path": str(result.config_path),
                        "config": result.config,
                    }
                )
                return 0
            if options.quiet:
                return 0
            title = (
                "LoopForge project ready"
                if result.created
                else "Project repaired"
                if result.repaired
                else "Project already ready"
            )
            rows: list[tuple[str, object]] = [
                ("project", result.config["project_name"]),
                ("profile", result.config["profile"]),
                ("runs", result.config["run_root"]),
            ]
            if result.repaired:
                rows.append(("config", result.config_path))
            render_success(renderer, title, rows, next_command='loopforge run --task "Describe the task"')
            return 0
        if args.command == "run":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge run")
            init_result = initialize_project(Path.cwd())
            selected_adapter, selected_adapter_args = configured_adapter(init_result.config)
            selected_adapter_command = adapter_continue_command(
                selected_adapter,
                selected_adapter_args,
            )
            can_prompt = not options.no_input and fmt == "text" and sys.stdin.isatty()
            wizard_used = can_prompt and (not args.task or bool(args.issue_source))
            if wizard_used:
                intake = interactive_run_intake(Path.cwd(), args)
            else:
                intake = noninteractive_run_intake(Path.cwd(), args)
            try:
                with renderer.loading("Creating LoopForge run..."):
                    result = create_run(
                        Path.cwd(),
                        task=intake.task,
                        pack=args.pack,
                        success_checks=intake.success_checks,
                        selected_skills=args.skill,
                        allowed_tools=intake.allowed_tools,
                        max_attempts=args.max_attempts,
                        timeout_seconds=args.timeout,
                        subjective_rubric=intake.subjective_rubric,
                        source_metadata=intake.source_metadata,
                    )
            except (FileNotFoundError, ValueError) as error:
                raise CliRuntimeError(
                    "LF_RUN_FAILED",
                    "LoopForge run failed",
                    str(error),
                    fix="Run `loopforge init` first, then retry `loopforge run --task \"...\"`.",
                ) from error
            if fmt == "json":
                print_json_payload({"ok": True, "run_dir": str(result.run_dir), "run": result.run})
                return 0
            if options.quiet:
                return 0
            extra = []
            if init_result.created:
                extra.append("Project")
                extra.append("Initialized LoopForge metadata before creating the run.")
            elif init_result.repaired:
                extra.append("Project")
                extra.append("Repaired LoopForge metadata before creating the run.")
            if intake.notes:
                extra.append("Notes")
                extra.extend(str(note) for note in intake.notes)
            if not intake.success_checks:
                extra.append("Warning")
                extra.append("No success check was provided; autonomous attempts may pause for contract completion.")
            if result.run["loop_contract"]["subjective"] and not intake.subjective_rubric:
                extra.append("Rubric")
                extra.append("Subjective work needs a rubric before autonomous attempts.")
            if intake.success_checks:
                extra.append("Selected checks")
                extra.extend(f"- {check}" for check in intake.success_checks[:5])
            if intake.allowed_tools:
                extra.append("Selected permissions")
                extra.extend(f"- {tool}" for tool in intake.allowed_tools[:5])
            render_summary_table(
                renderer,
                "Run created",
                [
                    ("goal", compact_text(result.run["task"], limit=90)),
                    ("run", result.run["run_id"]),
                    ("pack", result.run["pack"]),
                    ("contract", result.run["loop_contract"]["status"]),
                ],
                extra_lines=extra,
                next_command=selected_adapter_command,
            )
            if wizard_used:
                if prompt_yes_no(f"Launch adapter {selected_adapter} now", default=False):
                    with renderer.loading(f"Launching adapter {selected_adapter}..."):
                        continue_result = continue_run(
                            Path.cwd(),
                            adapter=selected_adapter,
                            adapter_args=selected_adapter_args,
                            confirmed=True,
                        )
                    render_continue_result(
                        renderer if continue_result.ok else TerminalRenderer(sys.stderr, no_color=options.no_color),
                        continue_result,
                        details=False,
                    )
                    return 0 if continue_result.ok else 1
                print(f"Continue later with: {selected_adapter_command}")
            return 0
        if args.command == "pack":
            if args.pack_command == "list":
                detected = detect_project_pack(Path.cwd())
                rows = [
                    {
                        "current": "*" if pack.get("name") == detected.get("name") else "",
                        "name": pack.get("name") or "",
                        "description": pack.get("description") or "",
                        "kind": pack_kind(pack.get("source"), Path.cwd()),
                        "source": pack.get("source") or "none",
                    }
                    for pack in discover_pack_contracts(Path.cwd())
                ]
                if not rows and output_format(args, options) == "text":
                    print("No project packs found.")
                    return 0
                if options.quiet and output_format(args, options) == "text":
                    return 0
                print_table_rows(rows, args, key="pack-list", title="LoopForge packs")
                return 0
            if args.pack_command == "detect":
                fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge pack detect")
                pack = detect_project_pack(Path.cwd())
                if fmt == "json":
                    print_json_payload({"ok": True, "pack": pack})
                    return 0
                if options.quiet:
                    return 0
                render_success(
                    renderer,
                    "Detected pack",
                    [
                        ("pack", pack["name"]),
                        ("score", pack.get("detection_score", 0)),
                        ("why", detection_reason(pack, Path.cwd())),
                        ("source", pack.get("source") or "none"),
                    ],
                    next_command=f'loopforge run --pack {pack["name"]} --task "Describe the task"',
                )
                return 0
        if args.command == "runs":
            result = list_runs(Path.cwd())
            if result.blockers:
                raise CliRuntimeError(
                    "LF_CONFIG_MISSING",
                    "Project is not initialized",
                    "; ".join(result.blockers),
                    fix="Run `loopforge init` first.",
                )
            rows = run_rows_from_result(result)
            if options.quiet and output_format(args, options) == "text":
                return 0
            if output_format(args, options) == "text":
                print_runs_text(result, args)
            else:
                print_table_rows(rows, args, key="runs", title="LoopForge runs")
            return 0
        if args.command == "metrics":
            if args.metrics_command == "record":
                result = record_run_metrics(
                    Path.cwd(),
                    run_id=args.run_id,
                    model=args.model,
                    input_tokens=args.input_tokens,
                    output_tokens=args.output_tokens,
                    total_tokens=args.total_tokens,
                    cost_microunits=args.cost_microunits,
                    cost_currency=args.cost_currency,
                    human_corrections=args.human_corrections,
                    final_disposition=args.final_disposition,
                )
                output = sys.stdout if result.ok else sys.stderr
                if output_format(args, options) == "json":
                    print_json_payload(
                        {
                            "ok": result.ok,
                            "message": result.message,
                            "record_path": str(result.record_path) if result.record_path else None,
                            "record": result.record,
                            "blockers": result.blockers,
                        }
                    )
                else:
                    if options.quiet and result.ok:
                        return 0
                    if result.record is not None and result.record_path is not None:
                        record = result.record
                        timing = record.get("timing", {}) if isinstance(record.get("timing"), dict) else {}
                        tokens = record.get("tokens", {}) if isinstance(record.get("tokens"), dict) else {}
                        cost = record.get("cost", {}) if isinstance(record.get("cost"), dict) else {}
                        render_success(
                            renderer,
                            "Metrics recorded",
                            [
                                ("run", record.get("run_id") or "none"),
                                ("duration", not_reported(timing.get("duration_seconds"))),
                                ("tokens", not_reported(tokens.get("total_tokens") or tokens.get("total"))),
                                ("cost", not_reported(cost.get("amount_microunits"))),
                                ("file", result.record_path),
                            ],
                        )
                    if result.blockers:
                        render_blocked(
                            renderer,
                            "Metrics blocked",
                            [("status", result.message)],
                            blockers=result.blockers,
                            next_command='loopforge run --task "Describe the task"',
                        )
                return 0 if result.ok else 1
            if args.metrics_command == "summarize":
                result = summarize_run_metrics(Path.cwd())
                if output_format(args, options) == "json":
                    print_json_payload(
                        {
                            "ok": result.ok,
                            "message": result.message,
                            "run_root": str(result.run_root) if result.run_root else None,
                            "summary": result.summary,
                            "blockers": result.blockers,
                        }
                    )
                    return 0 if result.ok else 1
                if output_format(args, options) == "csv":
                    print_table_rows(metrics_rows(result.summary), args, key="metrics-runs")
                    return 0 if result.ok else 1
                output = sys.stdout if result.ok else sys.stderr
                if options.quiet and result.ok:
                    return 0
                print_metrics_summary(result.summary, details=args.details)
                if result.blockers:
                    print("blockers:", file=output)
                    for blocker in result.blockers:
                        print(f"- {blocker}", file=output)
                return 0 if result.ok else 1
        if args.command == "status":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge status")
            if fmt == "json":
                print_json_payload({"ok": True, "status": status_payload(Path.cwd()), "guidance": guidance_payload(Path.cwd())})
                return 0
            if options.quiet:
                return 0
            result = current_status(Path.cwd())
            guidance = current_guidance(Path.cwd())
            render_status(renderer, result, guidance, details=args.details)
            return 0
        if args.command == "guide":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge guide")
            if fmt == "json":
                print_json_payload({"ok": True, "guidance": guidance_payload(Path.cwd())})
            else:
                if options.quiet:
                    return 0
                render_guidance(renderer, current_guidance(Path.cwd()), include_also=not options.quiet)
            return 0
        if args.command == "dashboard":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge dashboard")
            result = dashboard_snapshot(Path.cwd())
            if fmt == "json":
                print_json_payload({"ok": result.ok, "blockers": result.blockers, "dashboard": result.snapshot})
            else:
                if options.quiet and result.ok:
                    return 0
                render_dashboard(renderer, result.snapshot, details=args.details)
            return 0
        if args.command == "continue":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge continue")
            adapter_args = args.adapter_args
            if adapter_args and adapter_args[0] == "--":
                adapter_args = adapter_args[1:]
            with renderer.loading("Continuing LoopForge run..."):
                result = continue_run(
                    Path.cwd(),
                    adapter=args.adapter,
                    adapter_args=adapter_args,
                    confirmed=confirmation_accepted(args.confirm),
                )
            if fmt == "json":
                print_json_payload(
                    {
                        "ok": result.ok,
                        "message": result.message,
                        "run_dir": str(result.run_dir) if result.run_dir else None,
                        "contract": result.contract,
                        "run": result.run,
                        "attempt": result.attempt,
                        "blockers": result.blockers,
                    }
                )
                return 0 if result.ok else 1
            if options.quiet and result.ok:
                return 0
            render_continue_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=options.no_color),
                result,
                details=args.details,
            )
            return 0 if result.ok else 1
        if args.command == "verify":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge verify")
            with renderer.loading("Generating patch and running verification..."):
                result = verify_run(Path.cwd(), confirmed=confirmation_accepted(args.confirm))
            if fmt == "json":
                print_json_payload(
                    {
                        "ok": result.ok,
                        "message": result.message,
                        "run_dir": str(result.run_dir) if result.run_dir else None,
                        "run": result.run,
                        "verification": result.verification,
                        "blockers": result.blockers,
                    }
                )
                return 0 if result.ok else 1
            if options.quiet and result.ok:
                return 0
            render_verify_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=options.no_color),
                result,
                details=args.details,
            )
            return 0 if result.ok else 1
        if args.command == "learn":
            fmt = normalize_format(output_format(args, options), allowed=("text", "json"), command="loopforge learn")
            with renderer.loading("Updating LoopForge memory proposals..."):
                result = learn_run(
                    Path.cwd(),
                    approve=args.approve,
                    notes=args.note,
                    confirmed=confirmation_accepted(args.confirm),
                )
            if fmt == "json":
                print_json_payload(
                    {
                        "ok": result.ok,
                        "message": result.message,
                        "run_dir": str(result.run_dir) if result.run_dir else None,
                        "run": result.run,
                        "proposal_path": str(result.proposal_path) if result.proposal_path else None,
                        "proposals": result.proposals,
                        "promoted": result.promoted,
                        "rejected": result.rejected,
                        "blockers": result.blockers,
                    }
                )
                return 0 if result.ok else 1
            if options.quiet and result.ok:
                return 0
            render_learn_result(
                renderer if result.ok else TerminalRenderer(sys.stderr, no_color=options.no_color),
                result,
                approved=args.approve,
            )
            if args.details:
                for proposal in result.proposals[:10]:
                    if isinstance(proposal, dict):
                        print(
                            "- "
                            f"{proposal.get('id')}: {proposal.get('status')} "
                            f"{compact_text(proposal.get('text'), limit=100)}"
                        )
            return 0 if result.ok else 1
        raise CliUsageError("LF_USAGE", "Unknown command", str(args.command), fix="Run `loopforge help`.")
    except KeyboardInterrupt:
        error = CliRuntimeError(
            "LF_INTERRUPTED",
            "Interrupted",
            "Interrupted. Run `loopforge status` to inspect state.",
            fix="Run `loopforge status`.",
            exit_code=130,
        )
        render_cli_error(error, options)
        return 130
    except CliError as error:
        render_cli_error(error, options)
        return error.exit_code
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    except Exception as error:  # pragma: no cover - defensive top-level guard.
        cli_error = CliRuntimeError(
            "LF_INTERNAL",
            "Unexpected LoopForge failure",
            str(error),
            fix="Re-run with `--debug` and report the debug log.",
        )
        if options.debug:
            path = write_debug_log(error)
            traceback.print_exc(file=sys.stderr)
            print(f"debug log: {path}", file=sys.stderr)
        render_cli_error(cli_error, options)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
