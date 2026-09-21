"""Non-interactive run-intake service behind the LoopForge CLI compatibility facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loopforge.cli.models import GitHubIssueRef, RunIntake


class RunIntakeService:
    """Build manual and GitHub-backed run intake without owning terminal globals."""

    def __init__(self, api: Any) -> None:
        self.api = api

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
                "`loopforge run` needs --task or an issue source. Use `loopforge` for the TUI.",
                fix='Run `loopforge run --task "Describe the task"`.',
            )
        return RunIntake(
            task=task,
            success_checks=list(args.success_check),
            allowed_tools=list(args.allow_tool),
            subjective_rubric=args.rubric,
        )
