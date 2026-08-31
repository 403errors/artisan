"""Unit tests for completion.mark_ticket_done (Sprint 6): idempotent no-op if already done, and a
Jira failure doesn't roll back the Firestore write — Firestore is the source of truth, not Jira.
Plus completion.handle_issue_deleted (Sprint 7/8): same shape for the issuer-deleted-issue
terminal state, with an Artisan PR close and Jira comment on top."""

from datetime import datetime, timezone

import pytest
from artisan_agents import completion
from artisan_agents.jira.client import JiraClientError
from artisan_shared.firestore_schema import TicketDoc

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


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


@pytest.mark.asyncio
async def test_issue_deleted_marks_done_closes_pr_and_transitions_jira(
    fake_store, monkeypatch
) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(completion, "current_sink", lambda: sink)
    jira_calls: list[tuple] = []
    jira_comments: list[tuple] = []
    pr_closed: list[tuple] = []

    async def fake_transition(jira_key, status_name):
        jira_calls.append((jira_key, status_name))

    async def fake_add_comment(jira_key, body):
        jira_comments.append((jira_key, body))

    async def fake_close_pr(repo, pr_number, body):
        pr_closed.append((repo, pr_number, body))

    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)
    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)
    monkeypatch.setattr(completion.github_client, "close_pull_request", fake_close_pr)

    await completion.handle_issue_deleted(REPO, ISSUE_NUMBER, JIRA_KEY, pr_number=42)

    assert fake_store.doc.status == "done"
    assert fake_store.doc.current_step is None
    assert pr_closed == [(REPO, 42, ("Closing this PR — the issue it resolves (#1) was deleted by "
                                     "its author, so there's nothing left to merge."))]
    assert jira_calls == [(JIRA_KEY, "Done")]
    assert "deleted by its author" in jira_comments[0][1]
    assert [e["type"] for e in sink.events] == ["issue_deleted", "pr_closed", "jira_synced"]


@pytest.mark.asyncio
async def test_issue_deleted_without_pr_skips_the_pr_close(fake_store, monkeypatch) -> None:
    pr_closed = []

    async def fake_close_pr(repo, pr_number, body):
        pr_closed.append((repo, pr_number, body))

    async def fake_transition(jira_key, status_name):
        pass

    async def fake_add_comment(jira_key, body):
        pass

    monkeypatch.setattr(completion.github_client, "close_pull_request", fake_close_pr)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)
    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)

    await completion.handle_issue_deleted(REPO, ISSUE_NUMBER, JIRA_KEY)

    assert pr_closed == []


@pytest.mark.asyncio
async def test_issue_deleted_noop_when_already_done(fake_store, monkeypatch) -> None:
    fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})
    pr_closed = []
    jira_calls = []

    async def fake_close_pr(repo, pr_number, body):
        pr_closed.append(pr_number)

    async def fake_transition(jira_key, status_name):
        jira_calls.append(status_name)

    monkeypatch.setattr(completion.github_client, "close_pull_request", fake_close_pr)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.handle_issue_deleted(REPO, ISSUE_NUMBER, JIRA_KEY, pr_number=42)

    assert pr_closed == []  # short-circuited before any PR/Jira side effects
    assert jira_calls == []


@pytest.mark.asyncio
async def test_issue_deleted_jira_failure_does_not_roll_back_firestore(
    fake_store, monkeypatch
) -> None:
    async def fake_add_comment(jira_key, body):
        pass

    async def fake_transition(jira_key, status_name):
        raise JiraClientError("jira is down")

    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.handle_issue_deleted(REPO, ISSUE_NUMBER, JIRA_KEY)

    assert fake_store.doc.status == "done"


@pytest.mark.asyncio
async def test_issue_deleted_pr_close_failure_is_best_effort(fake_store, monkeypatch) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(completion, "current_sink", lambda: sink)
    jira_calls = []

    async def fake_close_pr(repo, pr_number, body):
        raise RuntimeError("github is down")

    async def fake_transition(jira_key, status_name):
        jira_calls.append(status_name)

    async def fake_add_comment(jira_key, body):
        pass

    monkeypatch.setattr(completion.github_client, "close_pull_request", fake_close_pr)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)
    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)

    await completion.handle_issue_deleted(REPO, ISSUE_NUMBER, JIRA_KEY, pr_number=42)

    # PR close is best-effort — a GitHub hiccup neither aborts the cleanup nor blocks Jira.
    assert fake_store.doc.status == "done"
    assert jira_calls == ["Done"]
    assert any(e["type"] == "error" for e in sink.events)


@pytest.mark.asyncio
async def test_mark_ticket_duplicate_closes_issue_and_transitions_jira(
    fake_store, monkeypatch
) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(completion, "current_sink", lambda: sink)
    jira_calls: list[tuple] = []
    jira_comments: list[tuple] = []
    closed: list[tuple] = []

    async def fake_close_dup(repo, issue_number, duplicate_of):
        closed.append((repo, issue_number, duplicate_of))

    async def fake_transition(jira_key, status_name):
        jira_calls.append((jira_key, status_name))

    async def fake_add_comment(jira_key, body):
        jira_comments.append((jira_key, body))

    monkeypatch.setattr(completion.github_client, "close_issue_as_duplicate", fake_close_dup)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)
    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)

    await completion.mark_ticket_duplicate(REPO, ISSUE_NUMBER, JIRA_KEY, duplicate_of=12)

    assert fake_store.doc.status == "done"
    assert fake_store.doc.current_step is None
    assert closed == [(REPO, ISSUE_NUMBER, 12)]
    assert jira_calls == [(JIRA_KEY, "Done")]
    assert "duplicate of #12" in jira_comments[0][1]
    assert [e["type"] for e in sink.events] == ["duplicate_confirmed", "jira_synced"]


@pytest.mark.asyncio
async def test_mark_ticket_duplicate_noop_when_already_done(fake_store, monkeypatch) -> None:
    fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})
    closed: list[tuple] = []
    jira_calls: list[tuple] = []

    async def fake_close_dup(repo, issue_number, duplicate_of):
        closed.append((repo, issue_number, duplicate_of))

    async def fake_transition(jira_key, status_name):
        jira_calls.append(status_name)

    monkeypatch.setattr(completion.github_client, "close_issue_as_duplicate", fake_close_dup)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)

    await completion.mark_ticket_duplicate(REPO, ISSUE_NUMBER, JIRA_KEY, duplicate_of=12)

    assert closed == []  # short-circuited before any GitHub/Jira side effects
    assert jira_calls == []


@pytest.mark.asyncio
async def test_mark_ticket_duplicate_firestore_first_when_github_fails(
    fake_store, monkeypatch
) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(completion, "current_sink", lambda: sink)

    async def fake_close_dup(repo, issue_number, duplicate_of):
        raise RuntimeError("github is down")

    async def fake_transition(jira_key, status_name):
        pass

    async def fake_add_comment(jira_key, body):
        pass

    monkeypatch.setattr(completion.github_client, "close_issue_as_duplicate", fake_close_dup)
    monkeypatch.setattr(completion.jira_client, "transition_ticket", fake_transition)
    monkeypatch.setattr(completion.jira_client, "add_comment", fake_add_comment)

    await completion.mark_ticket_duplicate(REPO, ISSUE_NUMBER, JIRA_KEY, duplicate_of=12)

    # The GitHub close is best-effort — a hiccup neither aborts the terminal transition nor rolls
    # back the Firestore write (Firestore is the source of truth, per SYSTEM_DESIGN.md §7).
    assert fake_store.doc.status == "done"
    assert any(e["type"] == "error" for e in sink.events)
