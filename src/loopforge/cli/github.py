"""GitHub issue access behind an injectable LoopForge CLI facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loopforge.cli.models import GitHubIssueRef, IssueReadResult, ReportIssueResult


# This is deliberately not inferred from the repository being operated on.
# Reports are product feedback for LoopForge itself, not issues for a user's project.
LOOPFORGE_GITHUB_REPOSITORY = "Loe159/LoopForge"

_SECRET_PATTERNS = (
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{36,})",
    r"(?:AKIA|ASIA)[A-Z0-9]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"(?i)\b(?:api[_ -]?key|authorization|bearer|client[_ -]?secret|password|token)\b\s*[:=]\s*[^\s`]+",
)


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

    def build_project_report(
        self,
        project_dir: Path,
        *,
        kind: str,
        title: str,
        description: str,
        expected: str = "",
        actual: str = "",
        include_context: bool = False,
        screen: str = "cli",
    ) -> ReportIssueResult:
        """Build a deterministic, sanitized report matching the issue template."""

        redactions = 0

        def redact(value: str) -> str:
            nonlocal redactions
            cleaned = value
            try:
                resolved = str(project_dir.resolve())
            except OSError:
                resolved = str(project_dir)
            for sensitive_value in (resolved, str(project_dir), project_dir.name):
                if sensitive_value:
                    cleaned, count = self.api.re.subn(
                        self.api.re.escape(sensitive_value),
                        "[redacted project]",
                        cleaned,
                        flags=self.api.re.IGNORECASE,
                    )
                    redactions += count
            for pattern in _SECRET_PATTERNS:
                cleaned, count = self.api.re.subn(pattern, "[redacted sensitive value]", cleaned)
                redactions += count
            return cleaned.strip()

        safe_kind = {"bug": "Bug", "feature": "Feature", "optimization": "Optimization"}.get(
            kind,
            "Report",
        )
        safe_title = redact(title)
        safe_description = redact(description)
        safe_expected = redact(expected) if expected else "Not provided."
        safe_actual = redact(actual) if actual else safe_description
        body_lines = [
            "## Report kind",
            safe_kind,
            "",
            "## Version",
            f"LoopForge {self.api.__version__}",
            "",
            "## Command",
            "```text",
            "loopforge report",
            "```",
            "",
            "## Stdout",
            "```text",
            "Not collected. Adapter output is never attached to product reports.",
            "```",
            "",
            "## Stderr",
            "```text",
            "Not collected. Adapter output is never attached to product reports.",
            "```",
            "",
            "## Expected behavior",
            safe_expected,
            "",
            "## Actual behavior",
            safe_actual,
        ]
        if include_context:
            status = self.api.current_status(project_dir)
            run = status.run if isinstance(status.run, dict) else {}
            # Keep this deliberately small: state is useful, project/task/output data is not.
            body_lines.extend(
                [
                    "",
                    "## LoopForge context (sanitized)",
                    f"- screen: {screen}",
                    f"- initialized: {'yes' if status.initialized else 'no'}",
                    f"- workflow state: {run.get('status') or 'no active run'}",
                    f"- workflow stage: {run.get('current_stage') or 'not available'}",
                    "- omitted: project name and path, task text, run identifiers, adapter messages, artifacts, and environment data.",
                ]
            )
        return ReportIssueResult(
            ok=True,
            repository=LOOPFORGE_GITHUB_REPOSITORY,
            title=f"[{safe_kind}] {safe_title}",
            body="\n".join(body_lines) + "\n",
            redactions=redactions,
        )

    def create_project_report(self, preview: ReportIssueResult) -> ReportIssueResult:
        """Create an issue only after the caller explicitly requests submission."""

        if self.api.shutil.which("gh") is None:
            return ReportIssueResult(
                ok=False,
                repository=LOOPFORGE_GITHUB_REPOSITORY,
                title=preview.title,
                body=preview.body,
                redactions=preview.redactions,
                reason="GitHub CLI (`gh`) is not available.",
            )
        try:
            result = self.api.subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    LOOPFORGE_GITHUB_REPOSITORY,
                    "--title",
                    preview.title,
                    "--body",
                    preview.body,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, self.api.subprocess.SubprocessError) as error:
            return ReportIssueResult(
                ok=False,
                repository=LOOPFORGE_GITHUB_REPOSITORY,
                title=preview.title,
                body=preview.body,
                redactions=preview.redactions,
                reason=f"GitHub issue creation failed: {error}",
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return ReportIssueResult(
                ok=False,
                repository=LOOPFORGE_GITHUB_REPOSITORY,
                title=preview.title,
                body=preview.body,
                redactions=preview.redactions,
                reason=detail or "GitHub issue creation failed.",
            )
        return ReportIssueResult(
            ok=True,
            repository=LOOPFORGE_GITHUB_REPOSITORY,
            title=preview.title,
            body=preview.body,
            submitted=True,
            url=result.stdout.strip(),
            redactions=preview.redactions,
        )

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
            "issue": ref.number,
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
