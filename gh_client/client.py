import logging
from github import Github, GithubException
from config.settings import GITHUB_TOKEN, GITHUB_REPO

logger = logging.getLogger(__name__)

_gh = Github(GITHUB_TOKEN)
_repo = _gh.get_repo(GITHUB_REPO)


def get_repo():
    return _repo


def get_ai_ready_issues():
    return list(_repo.get_issues(labels=["ai-ready"], state="open"))


def get_issue(issue_number: int):
    return _repo.get_issue(issue_number)


def add_label(issue, label_name: str):
    try:
        label = _repo.get_label(label_name)
    except GithubException:
        label = _repo.create_label(label_name, "0075ca")
    issue.add_to_labels(label)


def remove_label(issue, label_name: str):
    try:
        issue.remove_from_labels(label_name)
    except GithubException:
        pass


def add_comment(issue, body: str):
    return issue.create_comment(body)


def create_branch(branch_name: str, base: str = "main"):
    try:
        ref = _repo.get_git_ref(f"heads/{base}")
    except GithubException:
        ref = _repo.get_git_ref("heads/master")
    _repo.create_git_ref(f"refs/heads/{branch_name}", ref.object.sha)
    return branch_name


def create_pull_request(title: str, body: str, head: str, base: str = "main") -> object:
    try:
        pr = _repo.create_pull(title=title, body=body, head=head, base=base)
    except GithubException:
        pr = _repo.create_pull(title=title, body=body, head=head, base="master")
    return pr


def merge_pull_request(pr_number: int):
    pr = _repo.get_pull(pr_number)
    pr.merge(merge_method="squash")


def close_pull_request(pr_number: int):
    pr = _repo.get_pull(pr_number)
    pr.edit(state="closed")


def ensure_labels():
    required = [
        ("ai-ready", "0e8a16"),
        ("ai-in-progress", "fbca04"),
        ("ai-blocked", "e4e669"),
        ("ai-done", "0075ca"),
        ("risk-low", "c2e0c6"),
        ("risk-medium", "fef2c0"),
        ("risk-high", "e11d48"),
    ]
    existing = {lbl.name for lbl in _repo.get_labels()}
    for name, color in required:
        if name not in existing:
            _repo.create_label(name, color)
            logger.info("Created label: %s", name)


def get_project_item_status(issue_number: int) -> str | None:
    """Returns current kanban column name for the issue via GraphQL."""
    import requests
    query = """
    query($owner: String!, $repo: String!, $issue: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $issue) {
          projectItems(first: 5) {
            nodes {
              fieldValues(first: 10) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field { ... on ProjectV2SingleSelectField { name } }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    parts = GITHUB_REPO.split("/")
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": {"owner": parts[0], "repo": parts[1], "issue": issue_number}},
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
        timeout=15,
    )
    data = resp.json()
    try:
        items = data["data"]["repository"]["issue"]["projectItems"]["nodes"]
        for item in items:
            for fv in item["fieldValues"]["nodes"]:
                if fv and fv.get("field", {}).get("name") == "Status":
                    return fv["name"]
    except (KeyError, TypeError):
        pass
    return None
