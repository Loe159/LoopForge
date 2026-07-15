"""Guided run-intake service behind the LoopForge CLI compatibility facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loopforge.cli.models import GitHubIssueRef, RunIntake


class RunIntakeService:
    """Build manual and GitHub-backed run intake without owning terminal globals."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def pack_check_suggestions(
        self,
        project_dir: Path,
        pack: str | None,
    ) -> list[tuple[str, str]]:
        contract = self.api.detect_project_pack(project_dir) if pack is None else {"name": pack}
        pack_name = str(contract.get("name") or pack or "")
        try:
            checks = self.api.load_pack_checks(project_dir, pack_name).get("checks", [])
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

    def permission_suggestions(self) -> list[tuple[str, str]]:
        return [
            (
                tool,
                "Default LoopForge run permission; bounded by the run workspace and "
                "profile policy.",
            )
            for tool in self.api.DEFAULT_ALLOWED_TOOLS
        ]

    def confirm_or_edit_list(
        self,
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
        if self.api.prompt_yes_no("Use these", default=True):
            return values
        edited = self.api.prompt_text("Enter replacements separated by commas", required=False)
        return self.api.split_csv_prompt(edited) or values

    def build_manual(
        self,
        project_dir: Path,
        args: Any,
        *,
        default_task: str = "",
        source_metadata: dict[str, Any] | None = None,
        notes: list[str] | None = None,
    ) -> RunIntake:
        task = self.api.prompt_text("Title or goal", default=default_task)
        context = self.api.prompt_text("Bug context", required=False)
        proof = self.api.prompt_text("Proof of success")
        task_text = task if not context else f"{task}\n\nContext: {context}"
        checks = [proof, *list(args.success_check)]
        pack_checks = self.api.pack_check_suggestions(project_dir, args.pack)
        if args.success_check:
            print("Using checks from --success-check.")
        else:
            checks.extend(
                self.api.confirm_or_edit_list(
                    "Suggested checks",
                    pack_checks,
                    default_values=[value for value, _ in pack_checks],
                )
            )
        if args.allow_tool:
            allowed_tools = list(args.allow_tool)
            print("Using permissions from --allow-tool.")
        else:
            allowed_tools = self.api.confirm_or_edit_list(
                "Suggested permissions",
                self.api.permission_suggestions(),
            )
        profile = self.api.current_project_profile(project_dir)
        rubric = args.rubric
        if profile == "autonomous" and self.api.task_looks_subjective(task_text) and not rubric:
            rubric = self.api.prompt_text("Subjective quality rubric")
        approved = self.api.prompt_yes_no("Mark this manual task approved", default=False)
        return RunIntake(
            task=task_text,
            success_checks=checks,
            allowed_tools=allowed_tools,
            subjective_rubric=rubric,
            source_metadata=source_metadata,
            initial_approval={"approved": approved, "source": "local/manual"},
            notes=notes or [],
        )

    def build_issue(
        self,
        project_dir: Path,
        args: Any,
        ref: GitHubIssueRef,
        issue: dict[str, Any],
    ) -> RunIntake:
        self.api.require_agent_approved_issue(ref, issue)
        task = self.api.prompt_text("Run goal", default=self.api.issue_task_summary(issue))
        proof = self.api.prompt_text(
            "Proof of success",
            default=f"The behavior described in GitHub issue #{ref.number} is fixed or implemented.",
        )
        pack_checks = self.api.pack_check_suggestions(project_dir, args.pack)
        checks = [proof, *list(args.success_check)]
        if args.success_check:
            print("Using checks from --success-check.")
        else:
            checks.extend(self.api.confirm_or_edit_list("Suggested checks", pack_checks))
        if args.allow_tool:
            allowed_tools = list(args.allow_tool)
            print("Using permissions from --allow-tool.")
        else:
            allowed_tools = self.api.confirm_or_edit_list(
                "Suggested permissions",
                self.api.permission_suggestions(),
            )
        profile = self.api.current_project_profile(project_dir)
        rubric = args.rubric
        if profile == "autonomous" and self.api.task_looks_subjective(task) and not rubric:
            rubric = self.api.prompt_text("Subjective quality rubric")
        return RunIntake(
            task=task,
            success_checks=checks,
            allowed_tools=allowed_tools,
            subjective_rubric=rubric,
            source_metadata=self.api.issue_source_metadata(ref, issue),
            initial_approval={"approved": True, "source": "github"},
            notes=["Issue text is treated as untrusted input and was not promoted to durable memory."],
        )

    def build_noninteractive_issue(
        self,
        project_dir: Path,
        args: Any,
        ref: GitHubIssueRef,
        issue: dict[str, Any],
    ) -> RunIntake:
        del project_dir
        self.api.require_agent_approved_issue(ref, issue)
        task = args.task or self.api.issue_task_summary(issue)
        checks = list(args.success_check)
        if not checks:
            checks = [f"The behavior described in GitHub issue #{ref.number} is fixed or implemented."]
        return RunIntake(
            task=task,
            success_checks=checks,
            allowed_tools=list(args.allow_tool),
            subjective_rubric=args.rubric,
            source_metadata=self.api.issue_source_metadata(ref, issue),
            initial_approval={"approved": True, "source": "github"},
        )

    def choose_issue_from_list(
        self,
        project_dir: Path,
    ) -> tuple[GitHubIssueRef | None, dict[str, Any] | None, str]:
        listed = self.api.gh_issue_list(project_dir)
        if not listed.ok:
            return None, None, listed.reason
        issues = (listed.issue or {}).get("issues", [])
        if not isinstance(issues, list) or not issues:
            return None, None, "No open GitHub issues were returned."
        print("Open GitHub issues")
        for index, issue in enumerate(issues, start=1):
            print(f"{index}. #{issue.get('number')} {issue.get('title')}")
        choice = self.api.prompt_text("Select issue number from this list", required=False)
        if not choice.isdigit():
            return None, None, "No issue was selected."
        selected_index = int(choice)
        if selected_index < 1 or selected_index > len(issues):
            return None, None, "Issue selection was outside the displayed range."
        selected = issues[selected_index - 1]
        parsed = self.api.parse_github_issue_url(str(selected.get("url") or ""))
        if parsed is None:
            return None, None, "Selected issue did not include a supported GitHub URL."
        return parsed, selected, ""

    def interactive(self, project_dir: Path, args: Any) -> RunIntake:
        source = str(getattr(args, "issue_source", "") or "").strip()
        notes: list[str] = []
        if source:
            ref, reason = self.api.resolve_github_issue_ref(project_dir, source)
            if ref is not None:
                read = self.api.gh_issue_view(ref)
                if read.ok and read.issue is not None:
                    return self.api.build_issue_intake(project_dir, args, ref, read.issue)
                raise self.api.CliUsageError(
                    "LF_GITHUB_APPROVAL_UNAVAILABLE",
                    "GitHub issue approval could not be verified",
                    read.reason,
                    fix="Make the issue readable through `gh` and add `agent:approved`, then retry.",
                )
            notes.append(reason)
            print(reason)
            return self.api.build_manual_intake(project_dir, args, notes=notes)

        print("Create a run")
        print("1. Work from an existing GitHub issue")
        print("2. Report a new bug or task")
        choice = self.api.prompt_text("Choose", default="2")
        if choice == "1":
            entered = self.api.prompt_text(
                "GitHub issue URL or number, or leave blank to list open issues",
                required=False,
            )
            if entered:
                ref, reason = self.api.resolve_github_issue_ref(project_dir, entered)
                if ref is not None:
                    read = self.api.gh_issue_view(ref)
                    if read.ok and read.issue is not None:
                        return self.api.build_issue_intake(project_dir, args, ref, read.issue)
                    raise self.api.CliUsageError(
                        "LF_GITHUB_APPROVAL_UNAVAILABLE",
                        "GitHub issue approval could not be verified",
                        read.reason,
                        fix="Make the issue readable through `gh` and add `agent:approved`, then retry.",
                    )
                notes.append(reason)
                print(reason)
            else:
                ref, issue, reason = self.api.choose_issue_from_list(project_dir)
                if ref is not None and issue is not None:
                    return self.api.build_issue_intake(project_dir, args, ref, issue)
                if reason:
                    notes.append(reason)
                    print(reason)
        return self.api.build_manual_intake(project_dir, args, notes=notes)

    def noninteractive(self, project_dir: Path, args: Any) -> RunIntake:
        source = str(getattr(args, "issue_source", "") or "").strip()
        if source:
            ref, reason = self.api.resolve_github_issue_ref(project_dir, source)
            if ref is None:
                raise self.api.CliUsageError(
                    "LF_ISSUE_SOURCE_UNRESOLVED",
                    "Issue source could not be resolved",
                    reason,
                    fix='Pass a GitHub issue URL or use `--task "..."` without an issue source.',
                )
            read = self.api.gh_issue_view(ref)
            if not read.ok or read.issue is None:
                raise self.api.CliUsageError(
                    "LF_GITHUB_APPROVAL_UNAVAILABLE",
                    "GitHub issue approval could not be verified",
                    read.reason,
                    fix="Make the issue readable through `gh` and add `agent:approved`, then retry.",
                )
            return self.api.build_noninteractive_issue_intake(project_dir, args, ref, read.issue)
        task = str(args.task or "").strip()
        if not task:
            raise self.api.CliUsageError(
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
