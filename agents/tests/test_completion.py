"""Unit tests for completion.mark_ticket_done (Sprint 6): idempotent no-op if already done, and a
Jira failure doesn't roll back the Firestore write — Firestore is the source of truth, not Jira."""

from datetime import datetime, timezone

import pytest

from artisan_agents import completion
from artisan_agents.jira.client import JiraClientError
from artisan_shared.firestore_schema import TicketDoc

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"


class _FakeTicketStore:
    def __init__(self, *, status: str = "pr_open") -> None:
        now = datetime.now(timezone.utc)
        self.doc = TicketDoc(
            github_issue_number=ISSUE_NUMBER,
            github_repo=REPO,
            jira_key=JIRA_KEY,
            status=status,
            current_step="opening_pr",
            created_at=now,
            updated_at=now,
        )

    async def get_ticket(self, repo: str, issue_number: int) -> TicketDoc:
        return self.doc

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        self.doc = self.doc.model_copy(update=fields)


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeTicketStore()
    monkeypatch.setattr(completion.firestore_client, "get_ticket", store.get_ticket)
    monkeypatch.setattr(completion.firestore_client, "update_ticket", store.update_ticket)
    return store


@pytest.mark.asyncio
async def test_marks_ticket_done_clears_current_step_and_transitions_jira(fake_store, monkeypatch) -> None:
    jira_calls = []

    async def fake_transition(jira_key, status_name):
        jira_calls.append((jira_key, status_name))

    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.mark_ticket_done(REPO, ISSUE_NUMBER, JIRA_KEY, trigger="merge")

    assert fake_store.doc.status == "done"
    assert fake_store.doc.current_step is None
    assert jira_calls == [(JIRA_KEY, "Done")]


@pytest.mark.asyncio
async def test_noop_when_already_done(fake_store, monkeypatch) -> None:
    fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})
    jira_calls = []

    async def fake_transition(jira_key, status_name):
        jira_calls.append((jira_key, status_name))

    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.mark_ticket_done(REPO, ISSUE_NUMBER, JIRA_KEY, trigger="manual", actor="octocat")

    assert jira_calls == []  # short-circuited before ever attempting the Jira call


@pytest.mark.asyncio
async def test_jira_failure_does_not_roll_back_the_firestore_write(fake_store, monkeypatch) -> None:
    async def fake_transition(jira_key, status_name):
        raise JiraClientError("jira is down")

    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.mark_ticket_done(REPO, ISSUE_NUMBER, JIRA_KEY, trigger="merge")

    assert fake_store.doc.status == "done"
