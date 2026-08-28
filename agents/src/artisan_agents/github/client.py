"""Thin GitHub REST wrappers used by the intake/clarification flow — all calls go through the
App's installation-token client (github/auth.py), never a PAT."""

from artisan_agents.github.auth import get_installation_client


def _split_repo(repo: str) -> tuple[str, str]:
    owner, name = repo.split("/", 1)
    return owner, name


async def post_issue_comment(repo: str, issue_number: int, body: str) -> None:
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    await gh.rest.issues.async_create_comment(owner, name, issue_number, body=body)


async def get_issue_thread(repo: str, issue_number: int) -> tuple[str, str, list[str]]:
    """Returns (title, body, comment_bodies) for the Intake Agent's context window."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    issue = (await gh.rest.issues.async_get(owner, name, issue_number)).parsed_data
    comments_resp = await gh.rest.issues.async_list_comments(owner, name, issue_number)
    comment_bodies = [c.body or "" for c in comments_resp.parsed_data]
    return issue.title, issue.body or "", comment_bodies


async def open_pull_request(
    repo: str, *, head: str, base: str, title: str, body: str
) -> tuple[int, str]:
    """Opens a PR via the App's installation token (Gate 2, SPRINT.md Phase 3.6). Returns
    (pr_number, pr_html_url)."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    response = await gh.rest.pulls.async_create(
        owner, name, title=title, head=head, base=base, body=body
    )
    return response.parsed_data.number, response.parsed_data.html_url
