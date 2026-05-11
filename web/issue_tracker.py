"""Abstract IssueTracker interface + GitHub implementation.

Swap GitHubIssueTracker for a JiraIssueTracker without touching route code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class IssueItem:
    id: int
    title: str
    url: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    pr_url: str | None = None


class IssueTracker(ABC):
    @abstractmethod
    def get_issues(self, labels: list[str] | None = None) -> list[IssueItem]:
        ...

    @abstractmethod
    def trigger_pipeline(self, issue_id: int) -> bool:
        ...


class GitHubIssueTracker(IssueTracker):
    def __init__(self, token: str, repo: str) -> None:
        from github import Github
        self._gh = Github(token)
        self._repo = self._gh.get_repo(repo)

    def get_issues(self, labels: list[str] | None = None) -> list[IssueItem]:
        # W6: query per-label with server-side filtering (not O(N) all-issues scan)
        target_labels = labels or ["ai-ready", "ai-in-progress"]
        seen: set[int] = set()
        result: list[IssueItem] = []
        for lbl in target_labels:
            for issue in self._repo.get_issues(state="open", labels=[lbl]):
                if issue.number in seen:
                    continue
                seen.add(issue.number)
                issue_labels = [l.name for l in issue.labels]
                pr_url = issue.pull_request.html_url if issue.pull_request else None
                result.append(IssueItem(
                    id=issue.number,
                    title=issue.title,
                    url=issue.html_url,
                    labels=issue_labels,
                    state=issue.state,
                    pr_url=pr_url,
                ))
        return result

    def trigger_pipeline(self, issue_id: int) -> bool:
        try:
            issue = self._repo.get_issue(issue_id)
            current = [lbl.name for lbl in issue.labels]
            if "ai-in-progress" not in current:
                issue.add_to_labels("ai-in-progress")
            return True
        except Exception:
            return False
