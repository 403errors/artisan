"""Integration-style tests for Gate 3's control flow (gate3.py). Firestore, Jira, GitHub, the
Conflict Agent, and the Cloud Run Jobs conflict triggers are all faked here — this test is about
gate3.py's control flow, not any one integration, mirroring test_gate2.py's style exactly."""

from datetime import datetime, timezone

import pytest

from artisan_agents import gate3
from artisan_agents.gcp.cloud_run_jobs import ConflictDetectionCrashed
from artisan_agents.gcp.firestore_client import TrivialConflictCapExceeded
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import ConflictDetectionResult, ConflictVerdict, ExecutionResult

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

    async def append_trace_id(self, ticket_id: str, trace_id: str) -> None:
        self.ticket = self.ticket.model_copy(update={"trace_ids": [*self.ticket.trace_ids, trace_id]})


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
