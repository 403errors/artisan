"""Unit test for github/client.py's `open_pull_request` (Gate 2, MILESTONE.md Phase 3.6). Fakes the
installation client so no real GitHub call is made."""

import pytest

from artisan_agents.github import client as github_client_module
from artisan_agents.github.client import get_pull_request, open_pull_request


class _FakePullRequest:
    def __init__(self, number: int, html_url: str) -> None:
        self.number = number
        self.html_url = html_url


class _FakeRef:
    def __init__(self, ref: str, sha: str = "") -> None:
        self.ref = ref
        self.sha = sha


class _FakeFullPullRequest:
    def __init__(self, *, title: str, body: str | None, base_ref: str, head_ref: str, head_sha: str) -> None:
        self.title = title
        self.body = body
        self.base = _FakeRef(base_ref)
        self.head = _FakeRef(head_ref, head_sha)


class _FakeResponse:
    def __init__(self, parsed_data) -> None:
        self.parsed_data = parsed_data


class _FakePulls:
    def __init__(self) -> None:
        self.calls = []
        self.get_calls = []
        self._full_pr = None

    async def async_create(self, owner, repo, *, title, head, base, body):
        self.calls.append((owner, repo, title, head, base, body))
        return _FakeResponse(_FakePullRequest(42, f"https://github.com/{owner}/{repo}/pull/42"))

    async def async_get(self, owner, repo, pr_number):
        self.get_calls.append((owner, repo, pr_number))
        return _FakeResponse(self._full_pr)


class _FakeRest:
    def __init__(self) -> None:
        self.pulls = _FakePulls()


class _FakeGitHub:
    def __init__(self) -> None:
        self.rest = _FakeRest()


@pytest.mark.asyncio
async def test_open_pull_request_returns_number_and_html_url(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    number, url = await open_pull_request(
        "acme/demo", head="artisan/ART-1-attempt-1", base="main", title="Artisan: fix bug", body="body"
    )

    assert number == 42
    assert url == "https://github.com/acme/demo/pull/42"
    assert fake_gh.rest.pulls.calls == [
        ("acme", "demo", "Artisan: fix bug", "artisan/ART-1-attempt-1", "main", "body")
    ]


@pytest.mark.asyncio
async def test_get_pull_request_returns_title_body_and_refs(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    fake_gh.rest.pulls._full_pr = _FakeFullPullRequest(
        title="Artisan: fix bug",
        body="Resolves #1.",
        base_ref="main",
        head_ref="artisan/ART-1-attempt-1",
        head_sha="deadbeef",
    )
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    title, body, base_ref, head_ref, head_sha = await get_pull_request("acme/demo", 5)

    assert (title, body, base_ref, head_ref, head_sha) == (
        "Artisan: fix bug", "Resolves #1.", "main", "artisan/ART-1-attempt-1", "deadbeef",
    )
    assert fake_gh.rest.pulls.get_calls == [("acme", "demo", 5)]


@pytest.mark.asyncio
async def test_get_pull_request_treats_a_null_body_as_empty_string(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    fake_gh.rest.pulls._full_pr = _FakeFullPullRequest(
        title="T", body=None, base_ref="main", head_ref="head", head_sha="sha",
    )
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    _title, body, *_rest = await get_pull_request("acme/demo", 5)
    assert body == ""
