"""GitHub Projects V2 kanban management via GraphQL."""
import logging
import requests
from config.settings import GITHUB_TOKEN, GITHUB_REPO

logger = logging.getLogger(__name__)

HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"}
GQL_URL = "https://api.github.com/graphql"

COLUMNS = [
    "Backlog", "Triage", "Needs Clarification", "Technical Spec",
    "Awaiting Spec Approval",
    "Ready for Dev", "In Development", "Tests Running", "AI Review",
    "Human Approval", "Ready to Merge", "Released", "Docs Updated",
]

_project_id: str | None = None
_field_id: str | None = None
_option_ids: dict[str, str] = {}
_item_ids: dict[int, str] = {}


def _gql(query: str, variables: dict) -> dict:
    resp = requests.post(GQL_URL, json={"query": query, "variables": variables},
                         headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data and not data.get("data"):
        raise RuntimeError(data["errors"][0]["message"])
    return data


def _get_owner_id(login: str) -> str:
    q = "query($login: String!) { user(login: $login) { id } }"
    return _gql(q, {"login": login})["data"]["user"]["id"]


def _get_or_create_project() -> tuple[str, str, dict[str, str]]:
    global _project_id, _field_id, _option_ids
    if _project_id:
        return _project_id, _field_id, _option_ids

    owner = GITHUB_REPO.split("/")[0]

    find_q = """
    query($login: String!) {
      user(login: $login) {
        projectsV2(first: 20) {
          nodes { id title }
        }
      }
    }
    """
    data = _gql(find_q, {"login": owner})
    projects = data["data"]["user"]["projectsV2"]["nodes"]
    repo_name = GITHUB_REPO.split("/")[1]
    project_title = f"AI-SDLC — {repo_name}"
    project = next((p for p in projects if p["title"] == project_title), None)

    if not project:
        project = _create_project(owner, project_title)

    _project_id = project["id"]
    _field_id, _option_ids = _get_status_field(_project_id)
    return _project_id, _field_id, _option_ids


def _create_project(owner_login: str, title: str) -> dict:
    owner_id = _get_owner_id(owner_login)
    q = """
    mutation($ownerId: ID!, $title: String!) {
      createProjectV2(input: {ownerId: $ownerId, title: $title}) {
        projectV2 { id title }
      }
    }
    """
    result = _gql(q, {"ownerId": owner_id, "title": title})
    project = result["data"]["createProjectV2"]["projectV2"]
    logger.info("Created project '%s': %s", title, project["id"])
    _link_project_to_repo(project["id"])
    return project


def _link_project_to_repo(project_id: str) -> None:
    owner, repo_name = GITHUB_REPO.split("/")
    q = """query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) { id }
    }"""
    repo_id = _gql(q, {"owner": owner, "name": repo_name})["data"]["repository"]["id"]
    m = """mutation($projectId: ID!, $repositoryId: ID!) {
      linkProjectV2ToRepository(input: {projectId: $projectId, repositoryId: $repositoryId}) {
        repository { name }
      }
    }"""
    _gql(m, {"projectId": project_id, "repositoryId": repo_id})
    logger.info("Linked project to repo %s", GITHUB_REPO)


def _get_status_field(project_id: str) -> tuple[str, dict[str, str]]:
    fields_q = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 20) {
            nodes {
              ... on ProjectV2SingleSelectField {
                id name
                options { id name }
              }
            }
          }
        }
      }
    }
    """
    data = _gql(fields_q, {"projectId": project_id})
    fields = data["data"]["node"]["fields"]["nodes"]

    # Look for our custom pipeline field (has Backlog option)
    # Find our custom pipeline field (has "Backlog" option)
    pipeline_field = next(
        (f for f in fields
         if f.get("name") == "Pipeline Status" and f.get("options")),
        None,
    )
    if not pipeline_field:
        # Fallback: any single-select field with Backlog option
        pipeline_field = next(
            (f for f in fields
             if f.get("options") and any(o["name"] == "Backlog" for o in f["options"])),
            None,
        )

    if not pipeline_field:
        pipeline_field = _create_status_field(project_id)

    option_ids = {opt["name"]: opt["id"] for opt in pipeline_field.get("options", [])}
    logger.info("Pipeline field '%s' options: %s", pipeline_field.get("name"), list(option_ids.keys()))
    return pipeline_field["id"], option_ids


def _create_status_field(project_id: str) -> dict:
    q = """
    mutation($projectId: ID!, $name: String!, $dataType: ProjectV2CustomFieldType!, $singleSelectOptions: [ProjectV2SingleSelectFieldOptionInput!]) {
      createProjectV2Field(input: {
        projectId: $projectId,
        dataType: $dataType,
        name: $name,
        singleSelectOptions: $singleSelectOptions
      }) {
        projectV2Field {
          ... on ProjectV2SingleSelectField {
            id name options { id name }
          }
        }
      }
    }
    """
    options = [{"name": col, "color": "GRAY", "description": ""} for col in COLUMNS]
    result = _gql(q, {
        "projectId": project_id,
        "name": "Pipeline Status",
        "dataType": "SINGLE_SELECT",
        "singleSelectOptions": options,
    })
    field = result["data"]["createProjectV2Field"]["projectV2Field"]
    logger.info("Created Status field with %d options", len(field.get("options", [])))
    return field


def add_issue_to_project(issue_number: int, issue_node_id: str) -> str:
    if issue_number in _item_ids:
        return _item_ids[issue_number]

    project_id, _, _ = _get_or_create_project()
    q = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
        item { id }
      }
    }
    """
    result = _gql(q, {"projectId": project_id, "contentId": issue_node_id})
    item_id = result["data"]["addProjectV2ItemById"]["item"]["id"]
    _item_ids[issue_number] = item_id
    logger.info("Added issue #%d to project, item_id=%s", issue_number, item_id)
    return item_id


def move_issue(issue_number: int, issue_node_id: str, column: str):
    project_id, field_id, option_ids = _get_or_create_project()
    item_id = add_issue_to_project(issue_number, issue_node_id)

    option_id = option_ids.get(column)
    if not option_id:
        logger.error("Column '%s' not found in options: %s", column, list(option_ids.keys()))
        return

    q = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId,
        itemId: $itemId,
        fieldId: $fieldId,
        value: { singleSelectOptionId: $optionId }
      }) {
        projectV2Item { id }
      }
    }
    """
    _gql(q, {
        "projectId": project_id,
        "itemId": item_id,
        "fieldId": field_id,
        "optionId": option_id,
    })
    logger.info("Issue #%d moved to '%s'", issue_number, column)
