"""Unit tests for jira/client.py's direct Jira Cloud REST API calls. Uses httpx.MockTransport so
no real network call is made — see the module docstring for why this replaced mcp-atlassian."""

import json

import httpx
import pytest

from artisan_agents.jira import client as jira_client_module
from artisan_agents.jira.client import JiraClientError, add_comment, create_ticket, transition_ticket


_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*, base_url, auth, timeout):
        return _RealAsyncClient(
            base_url=base_url, auth=auth, timeout=timeout, transport=httpx.MockTransport(handler)
        )

    return factory


@pytest.fixture(autouse=True)
def stub_secret(monkeypatch):
    monkeypatch.setattr(jira_client_module, "get_secret", lambda name: "fake-token")


@pytest.mark.asyncio
async def test_create_ticket_returns_issue_key(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/api/2/issue"
        body = request.read()
        assert b'"project"' in body
        return httpx.Response(201, json={"key": "ART-42"})

    monkeypatch.setattr(jira_client_module.httpx, "AsyncClient", _client_factory(handler))
    key = await create_ticket("Title", "Body", "https://github.com/x/y/issues/1")
    assert key == "ART-42"


@pytest.mark.asyncio
async def test_create_ticket_raises_on_error_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    monkeypatch.setattr(jira_client_module.httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(JiraClientError):
        await create_ticket("Title", "Body", "https://github.com/x/y/issues/1")


@pytest.mark.asyncio
async def test_transition_ticket_looks_up_transition_id_then_posts_it(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/rest/api/2/issue/ART-1/transitions"
            return httpx.Response(
                200,
                json={"transitions": [{"id": "21", "name": "In Progress"}, {"id": "31", "name": "Done"}]},
            )
        assert request.method == "POST"
        assert request.url.path == "/rest/api/2/issue/ART-1/transitions"
        assert json.loads(request.read()) == {"transition": {"id": "21"}}
        return httpx.Response(204)

    monkeypatch.setattr(jira_client_module.httpx, "AsyncClient", _client_factory(handler))
    await transition_ticket("ART-1", "In Progress")


@pytest.mark.asyncio
async def test_transition_ticket_raises_when_status_name_not_found(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Done"}]})

    monkeypatch.setattr(jira_client_module.httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(JiraClientError):
        await transition_ticket("ART-1", "In Progress")


@pytest.mark.asyncio
async def test_add_comment_posts_plain_text_body(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/api/2/issue/ART-1/comment"
        assert json.loads(request.read()) == {"body": "hello"}
        return httpx.Response(201, json={"id": "1"})

    monkeypatch.setattr(jira_client_module.httpx, "AsyncClient", _client_factory(handler))
    await add_comment("ART-1", "hello")
