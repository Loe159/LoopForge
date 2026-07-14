"""GitHub issue access behind an injectable LoopForge CLI facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loopforge.cli.models import GitHubIssueRef, IssueReadResult


class GitHubIssueClient:
    """Resolve, read, and validate GitHub issues through CLI dependencies."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def parse_remote(self, remote: str) -> tuple[str, str] | None:
        patterns = (
            r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
            r"^git@github\.com:(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
            r"^ssh://git@github\.com:(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
        )
        for pattern in patterns:
            match = self.api.re.match(pattern, remote.strip())
            if match:
                return match.group("owner"), match.group("repo")
        return None

    def repository_from_remote(self, project_dir: Path) -> tuple[str, str] | None:
        try:
            result = self.api.subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, self.api.subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return self.api.parse_github_remote(result.stdout.strip())

    def parse_issue_url(self, source: str) -> GitHubIssueRef | None:
        match = self.api.re.match(
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

    def resolve(self, project_dir: Path, source: str) -> tuple[GitHubIssueRef | None, str]:
        parsed = self.api.parse_github_issue_url(source)
        if parsed is not None:
            return parsed, ""
        if source.strip().isdigit():
            repo = self.api.github_repo_from_remote(project_dir)
            if repo is None:
                return None, (
                    "GitHub issue ID could not be resolved because the origin remote is "
                    "missing or not GitHub."
                )
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

    def view(self, ref: GitHubIssueRef) -> IssueReadResult:
        if self.api.shutil.which("gh") is None:
            return IssueReadResult(False, reason="GitHub CLI (`gh`) is not available.")
        try:
            result = self.api.subprocess.run(
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
        except (OSError, self.api.subprocess.SubprocessError) as error:
            return IssueReadResult(False, reason=f"GitHub issue read failed: {error}")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return IssueReadResult(False, reason=detail or "GitHub issue read failed.")
        try:
            issue = self.api.json.loads(result.stdout)
        except self.api.json.JSONDecodeError:
            return IssueReadResult(False, reason="GitHub returned unreadable issue data.")
        issue.setdefault("url", ref.url)
        issue.setdefault("number", ref.number)
        return IssueReadResult(True, issue=issue)

    def list_open(self, project_dir: Path) -> IssueReadResult:
        repo = self.api.github_repo_from_remote(project_dir)
        if repo is None:
            return IssueReadResult(False, reason="Open issues require a GitHub origin remote.")
        if self.api.shutil.which("gh") is None:
            return IssueReadResult(False, reason="GitHub CLI (`gh`) is not available.")
        owner, name = repo
        try:
            result = self.api.subprocess.run(
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
        except (OSError, self.api.subprocess.SubprocessError) as error:
            return IssueReadResult(False, reason=f"GitHub issue list failed: {error}")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return IssueReadResult(False, reason=detail or "GitHub issue list failed.")
        try:
            issues = self.api.json.loads(result.stdout)
        except self.api.json.JSONDecodeError:
            return IssueReadResult(False, reason="GitHub returned unreadable issue data.")
        return IssueReadResult(True, issue={"issues": issues})

    @staticmethod
    def task_summary(issue: dict[str, Any]) -> str:
        title = str(issue.get("title") or "").strip()
        number = issue.get("number")
        if number:
            return f"Resolve GitHub issue #{number}: {title}" if title else f"Resolve GitHub issue #{number}"
        return title or "Resolve GitHub issue"

    @staticmethod
    def source_metadata(
        ref: GitHubIssueRef,
        issue: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    @staticmethod
    def label_names(issue: dict[str, Any]) -> set[str]:
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            return set()
        names: set[str] = set()
        for label in labels:
            value: object = label
            if isinstance(label, dict):
                value = label.get("name") or label.get("label")
                if isinstance(value, dict):
                    value = value.get("name")
            if isinstance(value, str) and value.strip():
                names.add(value.strip().lower())
        return names

    def is_agent_approved(self, issue: dict[str, Any]) -> bool:
        return "agent:approved" in self.api.github_issue_label_names(issue)

    def require_agent_approved(self, ref: GitHubIssueRef, issue: dict[str, Any]) -> None:
        if self.api.github_issue_is_agent_approved(issue):
            return
        raise self.api.CliUsageError(
            "LF_GITHUB_APPROVAL_REQUIRED",
            "GitHub issue is not approved for agent work",
            f"{ref.url} must have the `agent:approved` label before LoopForge can create a run.",
            fix="Add the `agent:approved` label to the issue, then retry.",
        )
