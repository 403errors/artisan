"""Jira access via the Jira Cloud REST API v2, direct Basic Auth (email + API token).

Originally implemented against `mcp-atlassian` over the real MCP protocol (per Sprint 1's
deferred verification plan). Dropped after live Sprint 2 field-testing: two independently-verified
API tokens (each confirmed working via a direct REST call) both failed identically —
`401 Unauthorized` — when called through the deployed `sooperset/mcp-atlassian:0.23.1` image, which
runs Jira calls through an SSRF-protection hook (`attach_ssrf_hook=True` in its own traceback) that
appears to interfere with outbound Basic Auth in Cloud Run's sandboxed network. That's an
unresolved bug inside the pinned third-party image itself, not a credentials or networking problem
on our side — see docs/CONTEXT.md for the full diagnosis. Direct REST calls with the same
credentials work reliably, so that's what this module does instead."""

import httpx

from artisan_agents.config import (
    JIRA_PROJECT_KEY,
    JIRA_URL,
    JIRA_USERNAME,
    SECRET_JIRA_API_TOKEN,
)
from artisan_agents.gcp.secrets import get_secret


class JiraClientError(Exception):
    """Raised when a Jira REST API call fails."""


def _auth() -> tuple[str, str]:
    return (JIRA_USERNAME, get_secret(SECRET_JIRA_API_TOKEN))


async def _request(method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(base_url=JIRA_URL, auth=_auth(), timeout=15) as client:
        response = await client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise JiraClientError(f"{method} {path} failed ({response.status_code}): {response.text}")
    return response.json() if response.content else {}


async def create_ticket(issue_number: int, issue_title: str, issue_body: str, issue_url: str) -> tuple[str, str]:
    """Creates a Jira issue on the configured project; returns a tuple of (issue_key, summary).
    `issue_number` is prefixed onto the summary since Jira's own key (`ART-N`) is a separate
    per-project auto-increment unrelated to the GitHub issue number — without this prefix there's
    no way to tell which GitHub issue a Jira ticket came from without opening it."""
    summary = f"[GH#{issue_number}] {issue_title}"
    data = await _request(
        "POST",
        "/rest/api/2/issue",
        json={
            "fields": {
                "project": {"key": JIRA_PROJECT_KEY},
                "summary": summary,
                "description": f"{issue_body}\n\nSource: {issue_url}",
                "issuetype": {"name": "Task"},
            }
        },
    )
    return data["key"], summary


async def update_description(jira_key: str, description: str) -> None:
    """Overwrites the ticket's description field — used to fold the issuer's clarification replies
    into Jira once intake resolves, since `description` is otherwise write-once at create_ticket
    time and never reflects anything said after the initial (often vague) issue body."""
    await _request(
        "PUT",
        f"/rest/api/2/issue/{jira_key}",
        json={"fields": {"description": description}},
    )


async def transition_ticket(jira_key: str, status_name: str) -> None:
    """Transitions the ticket to the named status (e.g. `In Progress`)."""
    transitions = await _request("GET", f"/rest/api/2/issue/{jira_key}/transitions")
    match = next(
        (t for t in transitions.get("transitions", []) if t["name"] == status_name),
        None,
    )
    if match is None:
        raise JiraClientError(
            f"no transition named {status_name!r} available for {jira_key}"
        )
    await _request(
        "POST",
        f"/rest/api/2/issue/{jira_key}/transitions",
        json={"transition": {"id": match["id"]}},
    )


async def add_comment(jira_key: str, body: str) -> None:
    await _request("POST", f"/rest/api/2/issue/{jira_key}/comment", json={"body": body})


async def add_label(jira_key: str, label: str) -> None:
    await _request("PUT", f"/rest/api/2/issue/{jira_key}", json={"update": {"labels": [{"add": label}]}})


async def get_ticket_summary(jira_key: str) -> str | None:
    """Fetches the current summary/title of a Jira ticket. Returns None if the ticket is not found."""
    try:
        data = await _request("GET", f"/rest/api/2/issue/{jira_key}")
        return data.get("fields", {}).get("summary")
    except JiraClientError:
        return None
