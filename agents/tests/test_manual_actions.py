"""Unit tests for manual_actions.handle_action (Sprint 6): one test per action, the
manual_action-event-emitted-first ordering, the in-flight double-click guard, and the
branch-generation increment that feeds gate2's collision fix."""

from datetime import datetime, timedelta, timezone

import pytest

from artisan_agents import manual_actions
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import ManualActionEnvelope

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"


def _ticket(**overrides) -> TicketDoc:
    now = datetime.now(timezone.utc)
    defaults: dict = dict(
        github_issue_number=ISSUE_NUMBER,
        github_repo=REPO,
        jira_key=JIRA_KEY,
        status="escalated",
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    defaults.update(overrides)
    return TicketDoc(**defaults)


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


@pytest.fixture
def fake_firestore(monkeypatch):
    state = {"ticket": _ticket()}
    sink = _RecordingSink()
    escalations = []

    async def get_ticket(repo, issue_number):
        return state["ticket"]

    async def update_ticket(repo, issue_number, **fields):
        state["ticket"] = state["ticket"].model_copy(update=fields)

    async def append_escalation(repo, issue_number, entry):
        escalations.append(entry)
        state["ticket"] = state["ticket"].model_copy(
            update={
                "escalation_history": [*state["ticket"].escalation_history, entry],
                "status": "escalated",
            }
        )

    monkeypatch.setattr(manual_actions.firestore_client, "get_ticket", get_ticket)
    monkeypatch.setattr(manual_actions.firestore_client, "update_ticket", update_ticket)
    monkeypatch.setattr(manual_actions.firestore_client, "append_escalation", append_escalation)
    monkeypatch.setattr(manual_actions.firestore_client, "ticket_doc_id", lambda r, n: f"{r}__{n}")
    monkeypatch.setattr(manual_actions.firestore_client, "new_event_sink", lambda *a, **k: sink)

    return state, sink, escalations


def _envelope(action: str, **overrides) -> ManualActionEnvelope:
    defaults: dict = dict(
        action_id="action-1", action=action, repo=REPO, issue_number=ISSUE_NUMBER, actor="octocat"
    )
    defaults.update(overrides)
    return ManualActionEnvelope(**defaults)


@pytest.mark.asyncio
async def test_unknown_ticket_is_a_noop(monkeypatch) -> None:
    async def get_ticket(repo, issue_number):
        return None

    monkeypatch.setattr(manual_actions.firestore_client, "get_ticket", get_ticket)

    await manual_actions.handle_action(_envelope("mark_done"))  # must not raise


@pytest.mark.asyncio
async def test_manual_action_event_is_emitted_before_the_action_runs(fake_firestore, monkeypatch) -> None:
    state, sink, _escalations = fake_firestore

    async def fake_mark_done(*args, **kwargs):
        raise RuntimeError("boom — the audit event must already be recorded by now")

    monkeypatch.setattr(manual_actions, "mark_ticket_done", fake_mark_done)

    with pytest.raises(RuntimeError):
        await manual_actions.handle_action(_envelope("mark_done"))

    assert sink.events[0]["type"] == "manual_action"
    assert "mark_done" in sink.events[0]["summary"]


@pytest.mark.asyncio
async def test_in_flight_guard_rejects_a_recently_updated_live_ticket(fake_firestore, monkeypatch) -> None:
    state, sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="in_progress", updated_at=datetime.now(timezone.utc))

    called = []
    monkeypatch.setattr(manual_actions, "mark_ticket_done", lambda *a, **k: called.append(1))

    await manual_actions.handle_action(_envelope("mark_done"))

    assert called == []
    assert sink.events[-1]["type"] == "error"
    assert "already actively being worked" in sink.events[-1]["summary"]


@pytest.mark.asyncio
async def test_retry_gate1_resets_clarification_rounds_and_calls_evaluate_intake(
    fake_firestore, monkeypatch
) -> None:
    state, _sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="manual_pickup", clarification_rounds=3)

    calls = []

    async def fake_evaluate_intake(repo, issue_number, jira_key):
        calls.append((repo, issue_number, jira_key))

    monkeypatch.setattr(manual_actions.dispatch, "evaluate_intake", fake_evaluate_intake)

    await manual_actions.handle_action(_envelope("retry_gate1"))

    assert state["ticket"].clarification_rounds == 0
    assert state["ticket"].status == "intake"
    assert calls == [(REPO, ISSUE_NUMBER, JIRA_KEY)]


@pytest.mark.asyncio
async def test_retry_gate2_resets_retry_count_increments_generation_and_calls_start_gate2(
    fake_firestore, monkeypatch
) -> None:
    state, _sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="escalated", retry_count=3, manual_retry_generation=0)

    async def fake_get_issue_thread(repo, issue_number):
        return "Title", "Body", "octocat", []

    calls = []

    async def fake_start_gate2(repo, issue_number, jira_key, *, issue_title, issue_body, retry_generation):
        calls.append((repo, issue_number, jira_key, issue_title, issue_body, retry_generation))

    monkeypatch.setattr(manual_actions.github_client, "get_issue_thread", fake_get_issue_thread)
    monkeypatch.setattr(manual_actions.gate2, "start_gate2", fake_start_gate2)

    await manual_actions.handle_action(_envelope("retry_gate2"))

    assert state["ticket"].retry_count == 0
    assert state["ticket"].status == "in_progress"
    assert state["ticket"].manual_retry_generation == 1
    assert calls == [(REPO, ISSUE_NUMBER, JIRA_KEY, "Title", "Body", 1)]


@pytest.mark.asyncio
async def test_retry_gate3_rejected_without_a_pr_number(fake_firestore, monkeypatch) -> None:
    state, sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="escalated", pr_number=None)

    called = []
    monkeypatch.setattr(manual_actions.gate3, "start_gate3", lambda **k: called.append(k))

    await manual_actions.handle_action(_envelope("retry_gate3"))

    assert called == []
    assert sink.events[-1]["type"] == "error"
    assert "no PR" in sink.events[-1]["summary"]


@pytest.mark.asyncio
async def test_retry_gate3_reconstructs_pr_data_and_calls_start_gate3(fake_firestore, monkeypatch) -> None:
    state, _sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="escalated", pr_number=5, trivial_conflict_attempts=1)

    async def fake_get_pull_request(repo, pr_number):
        return "Artisan: fix", "Resolves #1.", "main", "artisan/ART-1-attempt-1", "deadbeef"

    calls = []

    async def fake_start_gate3(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(manual_actions.github_client, "get_pull_request", fake_get_pull_request)
    monkeypatch.setattr(manual_actions.gate3, "start_gate3", fake_start_gate3)

    await manual_actions.handle_action(_envelope("retry_gate3"))

    assert state["ticket"].trivial_conflict_attempts == 0
    assert calls == [
        {
            "repo": REPO,
            "issue_number": ISSUE_NUMBER,
            "jira_key": JIRA_KEY,
            "pr_number": 5,
            "pr_title": "Artisan: fix",
            "pr_body": "Resolves #1.",
            "base_branch": "main",
            "head_branch": "artisan/ART-1-attempt-1",
            "head_sha": "deadbeef",
        }
    ]


@pytest.mark.asyncio
async def test_escalate_appends_escalation_and_notifies_both_systems(fake_firestore, monkeypatch) -> None:
    state, _sink, escalations = fake_firestore
    state["ticket"] = _ticket(status="in_progress", current_step="planning (attempt 1)")

    github_comments = []
    jira_comments = []

    async def fake_post_issue_comment(repo, issue_number, body):
        github_comments.append(body)

    async def fake_add_comment(jira_key, body):
        jira_comments.append((jira_key, body))

    monkeypatch.setattr(manual_actions.github_client, "post_issue_comment", fake_post_issue_comment)
    monkeypatch.setattr(manual_actions.jira_client, "add_comment", fake_add_comment)

    await manual_actions.handle_action(_envelope("escalate", reason="taking too long"))

    assert len(escalations) == 1
    assert escalations[0].gate == "2"  # inferred from current_step's "planning" prefix
    assert "octocat" in escalations[0].reason
    assert "taking too long" in escalations[0].reason
    assert len(github_comments) == 1
    assert jira_comments == [(JIRA_KEY, "Artisan needs manual pickup: taking too long")]


@pytest.mark.asyncio
async def test_mark_done_delegates_to_completion(fake_firestore, monkeypatch) -> None:
    state, _sink, _escalations = fake_firestore
    state["ticket"] = _ticket(status="pr_open")

    calls = []

    async def fake_mark_ticket_done(repo, issue_number, jira_key, *, trigger, actor):
        calls.append((repo, issue_number, jira_key, trigger, actor))

    monkeypatch.setattr(manual_actions, "mark_ticket_done", fake_mark_ticket_done)

    await manual_actions.handle_action(_envelope("mark_done"))

    assert calls == [(REPO, ISSUE_NUMBER, JIRA_KEY, "manual", "octocat")]
