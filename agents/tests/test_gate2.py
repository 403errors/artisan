"""Integration-style tests for Gate 2's control flow (gate2.py). Firestore, Jira, GitHub, the
routing/domain-expert/planning/verification agents, and the Cloud Run Jobs trigger are all faked
here — this test is about gate2.py's control flow, not any one integration, mirroring
test_dispatch.py's style exactly."""

import asyncio
from datetime import datetime, timezone

import pytest

from artisan_agents import gate2
from artisan_agents.gcp.firestore_client import RetryCapExceeded
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import DomainExpertOutput, ExecutionResult, Plan, RoutingDecision

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"


@pytest.fixture(autouse=True)
def stub_repo_context(monkeypatch):
    """WS3: start_gate2 now fetches a RepoContext before routing. These control-flow tests aren't
    exercising repo_context.py itself (see test_repo_context.py for that) — stub it to a no-op so
    every existing test here doesn't also need a GitHub/Firestore double for it."""

    async def fake_get_repo_context(repo: str):
        return None

    monkeypatch.setattr(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)

_PLAN = Plan(steps=["do the thing"], touched_files=["a.py"], test_cases=["t1"], doc_updates=["d1"])


class _FakeTicketStore:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.doc = TicketDoc(
            github_issue_number=ISSUE_NUMBER,
            github_repo=REPO,
            jira_key=JIRA_KEY,
            status="in_progress",
            created_at=now,
            updated_at=now,
        )

    def ticket_doc_id(self, repo: str, issue_number: int) -> str:
        return f"{repo}__{issue_number}"

    async def get_ticket(self, repo: str, issue_number: int) -> TicketDoc:
        return self.doc

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        self.doc = self.doc.model_copy(update=fields)

    async def increment_retry_round(self, repo: str, issue_number: int) -> int:
        new_count = self.doc.retry_count + 1
        if new_count >= 3:
            self.doc = self.doc.model_copy(update={"retry_count": new_count, "status": "escalated"})
            raise RetryCapExceeded("cap reached")
        self.doc = self.doc.model_copy(update={"retry_count": new_count})
        return new_count

    async def append_escalation(self, repo: str, issue_number: int, entry) -> None:
        self.doc = self.doc.model_copy(
            update={"escalation_history": [*self.doc.escalation_history, entry], "status": "escalated"}
        )

    async def write_pr_pointer(self, repo: str, pr_number: int, issue_number: int) -> None:
        self.pr_pointers = getattr(self, "pr_pointers", [])
        self.pr_pointers.append((repo, pr_number, issue_number))

    async def append_trace_id(self, ticket_id: str, trace_id: str, label: str) -> None:
        entry = {"trace_id": trace_id, "label": label}
        self.doc = self.doc.model_copy(update={"trace_ids": [*self.doc.trace_ids, entry]})


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeTicketStore()
    monkeypatch.setattr(gate2.firestore_client, "get_ticket", store.get_ticket)
    monkeypatch.setattr(gate2.firestore_client, "update_ticket", store.update_ticket)
    monkeypatch.setattr(gate2.firestore_client, "increment_retry_round", store.increment_retry_round)
    monkeypatch.setattr(gate2.firestore_client, "append_escalation", store.append_escalation)
    monkeypatch.setattr(gate2.firestore_client, "write_pr_pointer", store.write_pr_pointer)
    monkeypatch.setattr(gate2.firestore_client, "ticket_doc_id", store.ticket_doc_id)
    monkeypatch.setattr(gate2.firestore_client, "append_trace_id", store.append_trace_id)
    return store


@pytest.fixture
def stub_jira_and_github(monkeypatch):
    prs = []
    jira_comments = []
    github_comments = []
    github_labels = []
    jira_labels = []

    async def fake_open_pull_request(repo, *, head, base, title, body):
        prs.append((repo, head, base, title, body))
        return 42, f"https://github.com/{repo}/pull/42"

    async def fake_add_comment(jira_key, body):
        jira_comments.append((jira_key, body))

    async def fake_post_issue_comment(repo, issue_number, body):
        github_comments.append((repo, issue_number, body))

    async def fake_add_github_label(repo, issue_number, label):
        github_labels.append((repo, issue_number, label))

    async def fake_add_jira_label(jira_key, label):
        jira_labels.append((jira_key, label))

    monkeypatch.setattr(gate2.github_client, "open_pull_request", fake_open_pull_request)
    monkeypatch.setattr(gate2.jira_client, "add_comment", fake_add_comment)
    monkeypatch.setattr(gate2.github_client, "post_issue_comment", fake_post_issue_comment)
    monkeypatch.setattr(gate2.github_client, "add_label", fake_add_github_label)
    monkeypatch.setattr(gate2.jira_client, "add_label", fake_add_jira_label)
    return prs, jira_comments, github_comments, github_labels, jira_labels


def _domain_output(domain: str) -> DomainExpertOutput:
    return DomainExpertOutput(domain=domain, technical_summary=f"{domain} summary", relevant_files=["a.py"])


@pytest.mark.asyncio
async def test_single_domain_routes_sequentially_and_multi_domain_dispatches_in_parallel(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    call_order: list[str] = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["frontend", "backend"], parallel=True)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        call_order.append(f"start:{domain}")
        await asyncio.sleep(0.01 if domain == "frontend" else 0)
        call_order.append(f"end:{domain}")
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    # Parallel dispatch: both domains start before either finishes (backend, the faster one,
    # finishes before frontend even though frontend was started first).
    assert call_order == ["start:frontend", "start:backend", "end:backend", "end:frontend"]
    assert fake_store.doc.domains == ["frontend", "backend"]
    assert fake_store.doc.status == "pr_open"


@pytest.mark.asyncio
async def test_pr_open_jira_comment_wraps_diff_summary_in_noformat(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """Jira wiki markup misreads a raw diffstat's own `+`/`-` characters as underline/strikethrough
    — wrapping it in {noformat} keeps it literal."""
    _prs, jira_comments, _github_comments, _github_labels, _jira_labels = stub_jira_and_github

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(
            branch="artisan/x",
            diff_summary="README.md (modified) +141 -26",
            tests_passed=True,
            logs_uri="gs://x",
        )

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert len(jira_comments) == 1
    _jira_key, body = jira_comments[0]
    assert "{noformat}\nREADME.md (modified) +141 -26\n{noformat}" in body


@pytest.mark.asyncio
async def test_single_domain_dispatch_runs_sequentially_with_one_call(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    calls = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["frontend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        calls.append(domain)
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert calls == ["frontend"]


@pytest.mark.asyncio
async def test_n_consecutive_failures_end_in_escalated_with_no_nplus1th_attempt(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    _, jira_comments, github_comments, _, _ = stub_jira_and_github
    execution_calls = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        execution_calls.append(kwargs["attempt"])
        return ExecutionResult(branch="artisan/x", diff_summary="x", tests_passed=False, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=False, feedback="tests failed")

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert execution_calls == [1, 2, 3]
    assert fake_store.doc.status == "escalated"
    assert len(fake_store.doc.escalation_history) == 1
    assert fake_store.doc.escalation_history[0].gate == "2"
    assert len(jira_comments) == 1
    assert len(github_comments) == 1
    assert github_comments[0][:2] == (REPO, ISSUE_NUMBER)


@pytest.mark.asyncio
async def test_green_on_second_attempt_reaches_pr_open_with_retry_count_one(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    prs, jira_comments, github_comments, github_labels, jira_labels = stub_jira_and_github
    execution_calls = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        execution_calls.append(kwargs["attempt"])
        passed = kwargs["attempt"] == 2
        return ExecutionResult(branch=f"artisan/x-{kwargs['attempt']}", diff_summary="x", tests_passed=passed, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        if kwargs["execution_result"].tests_passed:
            return VerificationVerdict(green=True)
        return VerificationVerdict(green=False, feedback="tests failed")

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert execution_calls == [1, 2]
    assert fake_store.doc.retry_count == 1
    assert fake_store.doc.status == "pr_open"
    assert fake_store.doc.pr_url == "https://github.com/acme/demo/pull/42"
    assert fake_store.doc.pr_number == 42
    assert fake_store.pr_pointers == [(REPO, 42, ISSUE_NUMBER)]
    assert len(prs) == 1
    assert len(jira_comments) == 1
    assert len(github_comments) == 0
    assert github_labels == [(REPO, 42, "artisan:ready-for-review")]
    assert jira_labels == [(JIRA_KEY, "artisan-pr-open")]


@pytest.mark.asyncio
async def test_open_pr_and_sync_github_label_failure_does_not_abort_pr_flow(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """Labeling is a nice-to-have signal, not load-bearing — a label API hiccup must never prevent
    the PR/Jira-comment work that already succeeded from being reported as done."""
    prs, jira_comments, github_comments, github_labels, jira_labels = stub_jira_and_github

    async def failing_add_github_label(repo, issue_number, label):
        raise RuntimeError("github label API is down")

    monkeypatch.setattr(gate2.github_client, "add_label", failing_add_github_label)

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x-1", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert fake_store.doc.status == "pr_open"
    assert len(prs) == 1
    assert len(jira_comments) == 1
    assert jira_labels == [(JIRA_KEY, "artisan-pr-open")]


@pytest.mark.asyncio
async def test_open_pr_and_sync_jira_label_failure_does_not_abort_pr_flow(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    prs, jira_comments, github_comments, github_labels, jira_labels = stub_jira_and_github

    async def failing_add_jira_label(jira_key, label):
        raise RuntimeError("jira label API is down")

    monkeypatch.setattr(gate2.jira_client, "add_label", failing_add_jira_label)

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x-1", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert fake_store.doc.status == "pr_open"
    assert len(prs) == 1
    assert len(jira_comments) == 1
    assert github_labels == [(REPO, 42, "artisan:ready-for-review")]


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


@pytest.mark.asyncio
async def test_start_gate2_emits_gate_started_then_pr_opened_and_jira_synced(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    sink = _RecordingSink()
    monkeypatch.setattr(gate2.firestore_client, "new_event_sink", lambda *a, **k: sink)

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x-1", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    types = [e["type"] for e in sink.events]
    assert types[0] == "gate_started"
    assert "pr_opened" in types
    assert "jira_synced" in types
    assert types.index("pr_opened") < types.index("jira_synced")


@pytest.mark.asyncio
async def test_start_gate2_retry_generation_zero_keeps_original_branch_format(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    branches: list[str] = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        branches.append(kwargs["branch"])
        return ExecutionResult(branch=kwargs["branch"], diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")
    assert branches == [f"artisan/{JIRA_KEY}-attempt-1"]


@pytest.mark.asyncio
async def test_start_gate2_retry_generation_nonzero_avoids_branch_collision(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    branches: list[str] = []

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        branches.append(kwargs["branch"])
        return ExecutionResult(branch=kwargs["branch"], diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(
        REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B", retry_generation=1
    )
    assert branches == [f"artisan/{JIRA_KEY}-r1-attempt-1"]


@pytest.mark.asyncio
async def test_start_gate2_aborts_retry_loop_when_ticket_already_done(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """Issue deleted while Gate 2 was mid-flight lands the ticket in `done` — the retry loop must
    not burn a sandbox run on a dead issue."""
    fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        raise AssertionError("planning must not run for a deleted issue")

    async def fake_trigger_execution(**kwargs):
        raise AssertionError("execution must not run for a deleted issue")

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert fake_store.doc.status == "done"


@pytest.mark.asyncio
async def test_open_pr_is_skipped_when_ticket_deleted_during_execution(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """The deletion can land between the retry-loop's status check and the PR open — `_open_pr_and_sync`
    re-checks so a PR for a dead issue is never opened."""
    prs, _jira_comments, _github_comments, _github_labels, _jira_labels = stub_jira_and_github

    async def fake_run_routing(**kwargs):
        return RoutingDecision(domains=["backend"], parallel=False)

    async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
        return _domain_output(domain)

    async def fake_run_planning(**kwargs):
        return _PLAN

    async def fake_trigger_execution(**kwargs):
        return ExecutionResult(branch="artisan/x", diff_summary="x", tests_passed=True, logs_uri="gs://x")

    async def fake_run_verification(**kwargs):
        from artisan_shared.models import VerificationVerdict

        # The deletion happens while verification runs (after the loop-top check).
        fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})
        return VerificationVerdict(green=True)

    monkeypatch.setattr(gate2, "run_routing", fake_run_routing)
    monkeypatch.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
    monkeypatch.setattr(gate2, "run_planning", fake_run_planning)
    monkeypatch.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
    monkeypatch.setattr(gate2, "run_verification", fake_run_verification)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert prs == []  # no PR opened for a deleted issue
    assert fake_store.doc.status == "done"


@pytest.mark.asyncio
async def test_escalate_is_skipped_when_ticket_deleted(
    fake_store, stub_jira_and_github, monkeypatch
) -> None:
    """Escalating a deleted issue would flip `done` back to `escalated` and 404 on the
    reporter-facing comment — the cleanup already closed the ticket out, so skip it."""
    _prs, jira_comments, github_comments, _github_labels, _jira_labels = stub_jira_and_github
    fake_store.doc = fake_store.doc.model_copy(update={"status": "done"})

    await gate2._escalate(REPO, ISSUE_NUMBER, JIRA_KEY, reason="boom")

    assert fake_store.doc.escalation_history == []
    assert fake_store.doc.status == "done"  # not resurrected to escalated
    assert jira_comments == []
    assert github_comments == []
