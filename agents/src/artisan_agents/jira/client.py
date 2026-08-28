"""Jira access via the `mcp-atlassian` Cloud Run service, over the real MCP protocol
(initialize -> tools/call) — this is Sprint 1's deferred verification, done for real here,
Cloud-Run-to-Cloud-Run (docs/CONTEXT.md "Known follow-up").

Uses the `mcp` SDK's ClientSession directly rather than ADK's `McpToolset`: these are
deterministic orchestration calls (create/transition/comment), not an LLM picking a tool from a
menu, and ADK's `BaseTool.run_async` requires a full agent `ToolContext` that only exists inside a
Runner session — unnecessary machinery for a fixed, non-agentic call sequence. `McpToolset` is the
right tool when an *agent* needs to browse/pick MCP tools (e.g. a future domain-expert agent); it
isn't needed just to invoke one known tool with known arguments.

Tool names below (`jira_create_issue`, `jira_transition_issue`, `jira_add_comment`,
`jira_get_transitions`) match the `sooperset/mcp-atlassian` image's documented tool surface as of
the 0.23.1 pin (SPRINT.md Phase 1.2) — confirm against a live `session.list_tools()` call the
first time this runs against the deployed service, since that's the one thing that couldn't be
verified from this environment (no network path to the internal-ingress service)."""

from contextlib import asynccontextmanager

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import fetch_id_token
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from artisan_agents.config import JIRA_PROJECT_KEY, MCP_ATLASSIAN_URL


class JiraClientError(Exception):
    """Raised when an mcp-atlassian tool call fails or returns an error result."""


def _id_token_header() -> dict[str, str]:
    """Mints a Google-signed ID token scoped to the mcp-atlassian Cloud Run service, so the
    orchestrator's own service-account identity authorizes the call (roles/run.invoker on
    mcp-atlassian) — no separate Jira credential is ever held by the orchestrator itself."""
    token = fetch_id_token(GoogleAuthRequest(), MCP_ATLASSIAN_URL)
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def _session():
    async with streamablehttp_client(
        f"{MCP_ATLASSIAN_URL}/mcp", headers=_id_token_header()
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _call_tool(tool_name: str, arguments: dict) -> dict:
    async with _session() as session:
        result = await session.call_tool(tool_name, arguments)
    if result.isError:
        raise JiraClientError(f"{tool_name} failed: {result.content}")
    return result.structuredContent or {}


async def create_ticket(issue_title: str, issue_body: str, issue_url: str) -> str:
    """Creates a Jira issue on the configured project; returns the new issue key (e.g. `ART-42`)."""
    data = await _call_tool(
        "jira_create_issue",
        {
            "project_key": JIRA_PROJECT_KEY,
            "summary": issue_title,
            "issue_type": "Task",
            "description": f"{issue_body}\n\nSource: {issue_url}",
        },
    )
    return data["key"]


async def transition_ticket(jira_key: str, status_name: str) -> None:
    """Transitions the ticket to the named status (e.g. `In Progress`)."""
    transitions = await _call_tool("jira_get_transitions", {"issue_key": jira_key})
    match = next(
        (t for t in transitions.get("transitions", []) if t["name"] == status_name),
        None,
    )
    if match is None:
        raise JiraClientError(
            f"no transition named {status_name!r} available for {jira_key}"
        )
    await _call_tool(
        "jira_transition_issue",
        {"issue_key": jira_key, "transition_id": match["id"]},
    )


async def add_comment(jira_key: str, body: str) -> None:
    await _call_tool("jira_add_comment", {"issue_key": jira_key, "comment": body})
