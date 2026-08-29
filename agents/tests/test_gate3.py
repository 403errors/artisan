"""Integration-style tests for Gate 3's control flow (gate3.py). Firestore, Jira, GitHub, the
Conflict Agent, and the Cloud Run Jobs conflict triggers are all faked here — this test is about
gate3.py's control flow, not any one integration, mirroring test_gate2.py's style exactly."""

from datetime import datetime, timezone

import pytest
from artisan_agents import gate3
from artisan_agents.gcp.cloud_run_jobs import ConflictDetectionCrashed
from artisan_agents.gcp.firestore_client import TrivialConflictCapExceeded
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import (
    ConflictDetectionResult,
    ConflictVerdict,
    ExecutionResult,
)

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"
PR_NUMBER = 5
PR_TITLE = "Artisan: fix"
PR_BODY = "Resolves #1."
BASE_BRANCH = "main"
HEAD_BRANCH = "artisan/ART-1-attempt-1"
HEAD_SHA = "deadbeef"

_NO_CONFLICT = ConflictDetectionResult(
    has_conflict=False, conflicted_files=[], conflict_markers="", base_branch_history="",
    diff_summary="clean", logs_uri="gs://x", head_sha=HEAD_SHA,
)
_CONFLICT = ConflictDetectionResult(
    has_conflict=True, conflicted_files=["shared.py"], conflict_markers="<<<<<<<",
    base_branch_history="base history", diff_summary="conflict", logs_uri="gs://x", head_sha=HEAD_SHA,
)


class _FakeTicketStore:
    def __init__(self, *, ticket: TicketDoc | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.ticket = ticket or TicketDoc(
            github_issue_number=ISSUE_NUMBER,
            github_repo=REPO,
            jira_key=JIRA_KEY,
            status="pr_open",
            pr_number=PR_NUMBER,
            created_at=now,
            updated_at=now,
        )
        self.trivial_conflict_attempts = self.ticket.trivial_conflict_attempts

    async def claim_semantic_conflict_escalation(self, repo: str, issue_number: int) -> bool:
        if self.ticket.semantic_conflict_escalated:
            return False
        self.ticket = self.ticket.model_copy(update={"semantic_conflict_escalated": True})
        return True

    def ticket_doc_id(self, repo: str, issue_number: int) -> str:
        return f"{repo}__{issue_number}"

    async def get_ticket_by_pr(self, repo: str, pr_number: int) -> TicketDoc | None:
        if pr_number != self.ticket.pr_number:
            return None
        return self.ticket

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        self.ticket = self.ticket.model_copy(update=fields)

    async def increment_trivial_conflict_attempt(self, repo: str, issue_number: int) -> int:
        self.trivial_conflict_attempts += 1
        if self.trivial_conflict_attempts > 1:
            self.ticket = self.ticket.model_copy(update={"status": "escalated"})
            raise TrivialConflictCapExceeded("cap reached")
        return self.trivial_conflict_attempts

    async def append_escalation(self, repo: str, issue_number: int, entry) -> None:
        self.ticket = self.ticket.model_copy(
            update={"escalation_history": [*self.ticket.escalation_history, entry], "status": "escalated"}
        )

    async def append_trace_id(self, ticket_id: str, trace_id: str, label: str) -> None:
        entry = {"trace_id": trace_id, "label": label}
        self.ticket = self.ticket.model_copy(update={"trace_ids": [*self.ticket.trace_ids, entry]})


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeTicketStore()
    monkeypatch.setattr(gate3.firestore_client, "get_ticket_by_pr", store.get_ticket_by_pr)
    monkeypatch.setattr(gate3.firestore_client, "update_ticket", store.update_ticket)
    monkeypatch.setattr(
        gate3.firestore_client, "increment_trivial_conflict_attempt", store.increment_trivial_conflict_attempt
    )
    monkeypatch.setattr(gate3.firestore_client, "append_escalation", store.append_escalation)
    monkeypatch.setattr(gate3.firestore_client, "ticket_doc_id", store.ticket_doc_id)
    monkeypatch.setattr(gate3.firestore_client, "append_trace_id", store.append_trace_id)
    monkeypatch.setattr(
        gate3.firestore_client,
        "claim_semantic_conflict_escalation",
        store.claim_semantic_conflict_escalation,
    )

    async def _instant_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(gate3.asyncio, "sleep", _instant_sleep)
    return store


@pytest.fixture
def stub_jira_and_github(monkeypatch):
    pr_comments = []
    jira_comments = []

    async def fake_post_issue_comment(repo, number, body):
        pr_comments.append((repo, number, body))

    async def fake_add_comment(jira_key, body):
        jira_comments.append((jira_key, body))

    monkeypatch.setattr(gate3.github_client, "post_issue_comment", fake_post_issue_comment)
    monkeypatch.setattr(gate3.jira_client, "add_comment", fake_add_comment)
    return pr_comments, jira_comments


async def _call_start_gate3() -> None:
    await gate3.start_gate3(
        repo=REPO, issue_number=ISSUE_NUMBER, jira_key=JIRA_KEY, pr_number=PR_NUMBER,
        pr_title=PR_TITLE, pr_body=PR_BODY, base_branch=BASE_BRANCH, head_branch=HEAD_BRANCH,
        head_sha=HEAD_SHA,
    )


@pytest.mark.asyncio
async def test_untracked_pr_no_ops_without_triggering_any_job(fake_store, monkeypatch) -> None:
    detection_calls = []

    async def fake_trigger_conflict_detection(**kwargs):
        detection_calls.append(kwargs)
        return _NO_CONFLICT

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)

    await gate3.handle_pull_request_event(
        REPO,
        {
            "pull_request": {
                "number": 999,  # not the tracked PR_NUMBER
                "title": "some other PR",
                "body": "",
                "base": {"ref": "main"},
                "head": {"ref": "some-branch", "sha": "abc123"},
            }
        },
    )

    assert detection_calls == []


@pytest.mark.asyncio
async def test_pull_request_opened_retries_pr_lookup_before_giving_up(fake_store, monkeypatch) -> None:
    """gate2._open_pr_and_sync can only write the pr_index pointer after GitHub assigns the PR
    number, so an `opened` webhook can race ahead of that write. A bounded retry absorbs it
    instead of silently no-op-ing Gate 3's first check (MILESTONE.md Sprint 4 close-out gap,
    closed Sprint 6)."""
    lookups = [None, None, fake_store.ticket]
    calls = []

    async def flaky_get_ticket_by_pr(repo: str, pr_number: int) -> TicketDoc | None:
        calls.append(pr_number)
        return lookups.pop(0)

    detection_calls = []

    async def fake_trigger_conflict_detection(**kwargs):
        detection_calls.append(kwargs)
        return _NO_CONFLICT

    monkeypatch.setattr(gate3.firestore_client, "get_ticket_by_pr", flaky_get_ticket_by_pr)
    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)

    await gate3.handle_pull_request_event(
        REPO,
        {
            "pull_request": {
                "number": PR_NUMBER,
                "title": PR_TITLE,
                "body": PR_BODY,
                "base": {"ref": BASE_BRANCH},
                "head": {"ref": HEAD_BRANCH, "sha": HEAD_SHA},
            }
        },
    )

    assert len(calls) == 3  # gave up only after exhausting the retries, not on the first miss
    assert len(detection_calls) == 1  # and then actually ran Gate 3, not a silent no-op


@pytest.mark.asyncio
async def test_pull_request_opened_still_no_ops_when_pointer_never_lands(
    fake_store, monkeypatch
) -> None:
    """The untracked-PR no-op behavior must survive the retry loop: if every retry also misses,
    it's genuinely not an Artisan-tracked PR, not just an unlucky race."""
    calls = []

    async def always_missing_get_ticket_by_pr(repo: str, pr_number: int) -> TicketDoc | None:
        calls.append(pr_number)
        return None

    detection_calls = []

    async def fake_trigger_conflict_detection(**kwargs):
        detection_calls.append(kwargs)
        return _NO_CONFLICT

    monkeypatch.setattr(gate3.firestore_client, "get_ticket_by_pr", always_missing_get_ticket_by_pr)
    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)

    await gate3.handle_pull_request_event(
        REPO,
        {
            "pull_request": {
                "number": 999,
                "title": "some other PR",
                "body": "",
                "base": {"ref": "main"},
                "head": {"ref": "some-branch", "sha": "abc123"},
            }
        },
    )

    assert len(calls) == 1 + gate3._MAX_PR_LOOKUP_RETRIES
    assert detection_calls == []


@pytest.mark.asyncio
async def test_no_conflict_detected_proceeds_silently_with_no_escalation(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    pr_comments, jira_comments = stub_jira_and_github

    async def fake_trigger_conflict_detection(**kwargs):
        return _NO_CONFLICT

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)

    await _call_start_gate3()

    assert pr_comments == []
    assert jira_comments == []
    assert fake_store.ticket.status == "pr_open"


@pytest.mark.asyncio
async def test_semantic_conflict_escalates_with_dual_comments_containing_both_sides(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    pr_comments, jira_comments = stub_jira_and_github
    comparison = "Side A intent: keep it. Side B intent: remove it."

    async def fake_trigger_conflict_detection(**kwargs):
        return _CONFLICT

    async def fake_run_conflict_classification(**kwargs):
        return ConflictVerdict(classification="semantic", comparison=comparison)

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)
    monkeypatch.setattr(gate3, "run_conflict_classification", fake_run_conflict_classification)

    await _call_start_gate3()

    assert fake_store.ticket.status == "escalated"
    assert len(pr_comments) == 1
    assert comparison in pr_comments[0][2]
    assert len(jira_comments) == 1
    assert comparison in jira_comments[0][1]


@pytest.mark.asyncio
async def test_semantic_conflict_escalation_is_deduped_across_repeated_deliveries(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """Sprint 4 close-out gap, closed Sprint 6: every independent opened/synchronize delivery
    classified `semantic` must not re-post duplicate maintainer-facing comments."""
    pr_comments, jira_comments = stub_jira_and_github
    comparison = "Side A intent: keep it. Side B intent: remove it."

    async def fake_trigger_conflict_detection(**kwargs):
        return _CONFLICT

    async def fake_run_conflict_classification(**kwargs):
        return ConflictVerdict(classification="semantic", comparison=comparison)

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)
    monkeypatch.setattr(gate3, "run_conflict_classification", fake_run_conflict_classification)

    await _call_start_gate3()
    await _call_start_gate3()

    assert len(pr_comments) == 1
    assert len(jira_comments) == 1


@pytest.mark.asyncio
async def test_trivial_conflict_success_proceeds_with_github_and_jira_comments(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    pr_comments, jira_comments = stub_jira_and_github

    async def fake_trigger_conflict_detection(**kwargs):
        return _CONFLICT

    async def fake_run_conflict_classification(**kwargs):
        return ConflictVerdict(classification="trivial")

    resolution_calls = []

    async def fake_trigger_conflict_resolution(**kwargs):
        resolution_calls.append(kwargs)
        return ExecutionResult(branch=HEAD_BRANCH, diff_summary="resolved cleanly", tests_passed=True, logs_uri="gs://x")

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)
    monkeypatch.setattr(gate3, "run_conflict_classification", fake_run_conflict_classification)
    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_resolution", fake_trigger_conflict_resolution)

    await _call_start_gate3()

    assert len(resolution_calls) == 1
    assert fake_store.ticket.status == "pr_open"  # never flipped to escalated
    assert len(pr_comments) == 1
    assert len(jira_comments) == 1


@pytest.mark.asyncio
async def test_trivial_conflict_forced_resolution_failure_escalates_with_exactly_one_attempt(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    pr_comments, jira_comments = stub_jira_and_github

    async def fake_trigger_conflict_detection(**kwargs):
        return _CONFLICT

    async def fake_run_conflict_classification(**kwargs):
        return ConflictVerdict(classification="trivial")

    resolution_calls = []

    async def fake_trigger_conflict_resolution(**kwargs):
        resolution_calls.append(kwargs)
        return ExecutionResult(branch=HEAD_BRANCH, diff_summary="tests still red", tests_passed=False, logs_uri="gs://x")

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)
    monkeypatch.setattr(gate3, "run_conflict_classification", fake_run_conflict_classification)
    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_resolution", fake_trigger_conflict_resolution)

    await _call_start_gate3()

    assert len(resolution_calls) == 1
    assert fake_store.ticket.status == "escalated"
    assert len(pr_comments) == 1
    assert len(jira_comments) == 1

    # A second conflict signal for the same ticket must be blocked by the cap BEFORE a second
    # resolution job is ever triggered — this is Phase 4.3's DoD, control-flow half.
    await _call_start_gate3()
    assert len(resolution_calls) == 1


@pytest.mark.asyncio
async def test_detection_crash_escalates_without_attempting_classification(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    pr_comments, jira_comments = stub_jira_and_github
    classification_calls = []

    async def fake_trigger_conflict_detection(**kwargs):
        raise ConflictDetectionCrashed("no result written")

    async def fake_run_conflict_classification(**kwargs):
        classification_calls.append(kwargs)
        return ConflictVerdict(classification="trivial")

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)
    monkeypatch.setattr(gate3, "run_conflict_classification", fake_run_conflict_classification)

    await _call_start_gate3()

    assert classification_calls == []
    assert fake_store.ticket.status == "escalated"
    assert len(pr_comments) == 1
    assert len(jira_comments) == 1


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


@pytest.mark.asyncio
async def test_start_gate3_emits_gate_started(fake_store, monkeypatch) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(gate3.firestore_client, "new_event_sink", lambda *a, **k: sink)

    async def fake_trigger_conflict_detection(**kwargs):
        return _NO_CONFLICT

    monkeypatch.setattr(gate3.cloud_run_jobs, "trigger_conflict_detection", fake_trigger_conflict_detection)

    await _call_start_gate3()

    assert sink.events[0]["type"] == "gate_started"
    assert "Gate 3" in sink.events[0]["summary"]
