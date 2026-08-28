"""Unit test for github/client.py's `open_pull_request` (Gate 2, SPRINT.md Phase 3.6). Fakes the
installation client so no real GitHub call is made."""

import pytest

from artisan_agents.github import client as github_client_module
from artisan_agents.github.client import open_pull_request


class _FakePullRequest:
    def __init__(self, number: int, html_url: str) -> None:
        self.number = number
        self.html_url = html_url


class _FakeResponse:
    def __init__(self, parsed_data) -> None:
        self.parsed_data = parsed_data


class _FakePulls:
    def __init__(self) -> None:
        self.calls = []

    async def async_create(self, owner, repo, *, title, head, base, body):
        self.calls.append((owner, repo, title, head, base, body))
        return _FakeResponse(_FakePullRequest(42, f"https://github.com/{owner}/{repo}/pull/42"))


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
