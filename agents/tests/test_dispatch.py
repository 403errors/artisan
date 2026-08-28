"""Integration-style test for the clarification loop + caps (Phase 2.4 DoD): 3 consecutive
insufficient verdicts must end the ticket in `manual_pickup` after exactly 3 comments/rounds, and
a 4th round must never be attempted. Firestore, Jira, GitHub, and the Intake Agent are all faked
here — this test is about dispatch.py's control flow, not any one integration."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from githubkit.exception import RequestFailed

from artisan_agents import dispatch
from artisan_agents.gcp.firestore_client import ClarificationCapExceeded
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import GitHubWebhookEnvelope, IntakeVerdict


class _FakeTicketStore:
    def __init__(self) -> None:
        self.tickets: dict[str, TicketDoc] = {}

    def _key(self, repo: str, issue_number: int) -> str:
        return f"{repo}__{issue_number}"

    def ticket_doc_id(self, repo: str, issue_number: int) -> str:
        return self._key(repo, issue_number)

    async def get_ticket(self, repo: str, issue_number: int) -> TicketDoc | None:
        return self.tickets.get(self._key(repo, issue_number))

    async def create_ticket(self, repo: str, issue_number: int, jira_key: str) -> TicketDoc:
        now = datetime.now(timezone.utc)
        doc = TicketDoc(
            github_issue_number=issue_number,
            github_repo=repo,
            jira_key=jira_key,
            status="intake",
            created_at=now,
            updated_at=now,
        )
        self.tickets[self._key(repo, issue_number)] = doc
        return doc

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        doc = self.tickets[self._key(repo, issue_number)]
        self.tickets[self._key(repo, issue_number)] = doc.model_copy(update=fields)

    async def increment_clarification_round(self, repo: str, issue_number: int) -> int:
        key = self._key(repo, issue_number)
        doc = self.tickets[key]
        new_count = doc.clarification_rounds + 1
        if new_count >= 3:
            self.tickets[key] = doc.model_copy(
                update={"clarification_rounds": new_count, "status": "manual_pickup"}
            )
            raise ClarificationCapExceeded("cap reached")
        self.tickets[key] = doc.model_copy(update={"clarification_rounds": new_count})
        return new_count


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeTicketStore()
    monkeypatch.setattr(dispatch.firestore_client, "get_ticket", store.get_ticket)
    monkeypatch.setattr(dispatch.firestore_client, "create_ticket", store.create_ticket)
    monkeypatch.setattr(dispatch.firestore_client, "update_ticket", store.update_ticket)
    monkeypatch.setattr(
        dispatch.firestore_client,
        "increment_clarification_round",
        store.increment_clarification_round,
    )
    monkeypatch.setattr(dispatch.firestore_client, "ticket_doc_id", store.ticket_doc_id)
    return store


def _issue_opened(repo: str = "acme/demo", issue_number: int = 1) -> GitHubWebhookEnvelope:
    return GitHubWebhookEnvelope(
        delivery_id="d-open",
        event="issues",
        action="opened",
        repo=repo,
        payload={
            "issue": {
                "number": issue_number,
                "title": "Bug",
                "body": "vague report",
                "html_url": f"https://github.com/{repo}/issues/{issue_number}",
            },
        },
    )


def _issue_comment(
    repo: str = "acme/demo", issue_number: int = 1, delivery_id: str = "d-comment"
) -> GitHubWebhookEnvelope:
    return GitHubWebhookEnvelope(
        delivery_id=delivery_id,
        event="issue_comment",
        action="created",
        repo=repo,
        payload={
            "issue": {"number": issue_number},
            "comment": {"user": {"type": "User"}},
        },
    )


@pytest.fixture
def stub_collaborators(monkeypatch):
    posted_comments: list[str] = []
    jira_comments: list[str] = []

    async def fake_create_ticket(title, body, url):
        return "ART-1"

    async def fake_transition_ticket(jira_key, status_name):
        raise AssertionError("must not transition to In Progress on an insufficient verdict")

    async def fake_add_comment(jira_key, body):
        jira_comments.append(body)

    async def fake_get_issue_thread(repo, issue_number):
        return "title", "body", []

    async def fake_post_issue_comment(repo, issue_number, body):
        posted_comments.append(body)

    async def fake_run_intake(**kwargs):
        return IntakeVerdict(sufficient=False, missing_context_question="which endpoint?")

    monkeypatch.setattr(dispatch.jira_client, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(dispatch.jira_client, "transition_ticket", fake_transition_ticket)
    monkeypatch.setattr(dispatch.jira_client, "add_comment", fake_add_comment)
    monkeypatch.setattr(dispatch.github_client, "get_issue_thread", fake_get_issue_thread)
    monkeypatch.setattr(dispatch.github_client, "post_issue_comment", fake_post_issue_comment)
    monkeypatch.setattr(dispatch, "run_intake", fake_run_intake)

    return posted_comments, jira_comments


@pytest.mark.asyncio
async def test_three_insufficient_rounds_ends_in_manual_pickup_and_does_not_attempt_a_fourth(
    fake_store, stub_collaborators
) -> None:
    posted_comments, jira_comments = stub_collaborators

    await dispatch.handle_event(_issue_opened())
    await dispatch.handle_event(_issue_comment(delivery_id="d-2"))
    await dispatch.handle_event(_issue_comment(delivery_id="d-3"))

    ticket = await fake_store.get_ticket("acme/demo", 1)
    assert ticket.status == "manual_pickup"
    assert ticket.clarification_rounds == 3
    assert len(posted_comments) == 3
    assert jira_comments == [
        "Artisan needs manual pickup: 3 clarification rounds without sufficient context."
    ]

    # Ticket is no longer "intake", so a 4th comment must not trigger another evaluation at all.
    await dispatch.handle_event(_issue_comment(delivery_id="d-4"))
    assert len(posted_comments) == 3


@pytest.mark.asyncio
async def test_bot_comments_never_retrigger_evaluation(fake_store, stub_collaborators) -> None:
    posted_comments, _jira_comments = stub_collaborators
    await dispatch.handle_event(_issue_opened())
    assert len(posted_comments) == 1

    bot_comment = GitHubWebhookEnvelope(
        delivery_id="d-bot",
        event="issue_comment",
        action="created",
        repo="acme/demo",
        payload={"issue": {"number": 1}, "comment": {"user": {"type": "Bot"}}},
    )
    await dispatch.handle_event(bot_comment)
    assert len(posted_comments) == 1


@pytest.mark.asyncio
async def test_sufficient_verdict_transitions_to_in_progress_and_hands_off_to_gate2(
    fake_store, monkeypatch
) -> None:
    transitioned = []
    gate2_calls = []

    async def fake_create_ticket(title, body, url):
        return "ART-1"

    async def fake_transition_ticket(jira_key, status_name):
        transitioned.append((jira_key, status_name))

    async def fake_get_issue_thread(repo, issue_number):
        return "title", "a very well specified body", []

    async def fake_run_intake(**kwargs):
        return IntakeVerdict(sufficient=True)

    async def fake_start_gate2(repo, issue_number, jira_key, *, issue_title, issue_body):
        gate2_calls.append((repo, issue_number, jira_key, issue_title, issue_body))

    monkeypatch.setattr(dispatch.jira_client, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(dispatch.jira_client, "transition_ticket", fake_transition_ticket)
    monkeypatch.setattr(dispatch.github_client, "get_issue_thread", fake_get_issue_thread)
    monkeypatch.setattr(dispatch, "run_intake", fake_run_intake)
    monkeypatch.setattr(dispatch.gate2, "start_gate2", fake_start_gate2)

    await dispatch.handle_event(_issue_opened())

    ticket = await fake_store.get_ticket("acme/demo", 1)
    assert ticket.status == "in_progress"
    assert transitioned == [("ART-1", "In Progress")]
    assert gate2_calls == [("acme/demo", 1, "ART-1", "title", "a very well specified body")]


def _request_failed(status_code: int) -> RequestFailed:
    # RequestFailed.__init__ needs a real githubkit Response wrapping an httpx one; bypassing
    # it lets the test assert purely on the `.response.status_code` classification dispatch.py
    # actually reads, without constructing a full HTTP round trip.
    exc = RequestFailed.__new__(RequestFailed)
    exc.response = SimpleNamespace(status_code=status_code)
    return exc


@pytest.mark.asyncio
async def test_github_404_on_issue_thread_is_classified_non_retriable(
    fake_store, monkeypatch
) -> None:
    async def fake_create_ticket(title, body, url):
        return "ART-1"

    async def fake_get_issue_thread(repo, issue_number):
        raise _request_failed(404)

    monkeypatch.setattr(dispatch.jira_client, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(dispatch.github_client, "get_issue_thread", fake_get_issue_thread)

    with pytest.raises(dispatch.NonRetriableEventError):
        await dispatch.handle_event(_issue_opened())


@pytest.mark.asyncio
async def test_non_404_github_failure_on_issue_thread_propagates_unchanged(
    fake_store, monkeypatch
) -> None:
    async def fake_create_ticket(title, body, url):
        return "ART-1"

    async def fake_get_issue_thread(repo, issue_number):
        raise _request_failed(500)

    monkeypatch.setattr(dispatch.jira_client, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(dispatch.github_client, "get_issue_thread", fake_get_issue_thread)

    with pytest.raises(RequestFailed):
        await dispatch.handle_event(_issue_opened())


def _pull_request_event(action: str, repo: str = "acme/demo") -> GitHubWebhookEnvelope:
    return GitHubWebhookEnvelope(
        delivery_id=f"d-pr-{action}",
        event="pull_request",
        action=action,
        repo=repo,
        payload={
            "pull_request": {
                "number": 5,
                "title": "Artisan: fix",
                "body": "Resolves #1.",
                "base": {"ref": "main"},
                "head": {"ref": "artisan/ART-1-attempt-1", "sha": "deadbeef"},
            }
        },
    )


@pytest.mark.asyncio
async def test_pull_request_opened_and_synchronize_dispatch_to_gate3(monkeypatch) -> None:
    calls = []

    async def fake_handle_pull_request_event(repo, payload):
        calls.append((repo, payload["pull_request"]["number"]))

    monkeypatch.setattr(dispatch.gate3, "handle_pull_request_event", fake_handle_pull_request_event)

    await dispatch.handle_event(_pull_request_event("opened"))
    await dispatch.handle_event(_pull_request_event("synchronize"))

    assert calls == [("acme/demo", 5), ("acme/demo", 5)]


@pytest.mark.asyncio
async def test_other_pull_request_actions_are_ignored(monkeypatch) -> None:
    calls = []

    async def fake_handle_pull_request_event(repo, payload):
        calls.append(repo)

    monkeypatch.setattr(dispatch.gate3, "handle_pull_request_event", fake_handle_pull_request_event)

    await dispatch.handle_event(_pull_request_event("labeled"))
    await dispatch.handle_event(_pull_request_event("closed"))

    assert calls == []
