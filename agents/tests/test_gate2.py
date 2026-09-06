"""Integration-style tests for Gate 2's control flow (gate2.py). Firestore, Jira, GitHub, the
routing/domain-expert/planning/verification agents, and the Cloud Run Jobs trigger are all faked
here — this test is about gate2.py's control flow, not any one integration, mirroring
test_dispatch.py's style exactly.

Every test drives the shared `_Gate2Harness`: it wires all boundary fakes with recording lists and
behavior knobs, so a test sets the one knob it cares about (routing decision, per-attempt
execution results, verification verdicts, ...) instead of re-defining six fakes per test."""

import asyncio
import inspect
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from artisan_agents import gate2
from artisan_agents.gcp.firestore_client import RetryCapExceeded
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import (
    CriterionResult,
    DomainExpertOutput,
    ExecutionResult,
    Plan,
    RepoContext,
    RoutingDecision,
    VerificationVerdict,
)

REPO = "acme/demo"
ISSUE_NUMBER = 1
JIRA_KEY = "ART-1"

_PLAN = Plan(steps=["do the thing"], touched_files=["a.py"], test_cases=["t1"], doc_updates=["d1"])


@pytest.fixture(autouse=True)
def stub_repo_context(monkeypatch):
    """start_gate2 fetches a RepoContext before routing. These control-flow tests don't exercise
    repo_context.py itself (see test_repo_context.py for that) — stub it to a no-op so no test
    here also needs a GitHub/Firestore double for it."""

    async def fake_get_repo_context(repo: str):
        return None

    monkeypatch.setattr(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)


def _domain_output(domain: str) -> DomainExpertOutput:
    return DomainExpertOutput(domain=domain, technical_summary=f"{domain} summary", files_to_modify=["a.py"])


def _forbidden(message: str) -> Callable:
    """Behavior-knob value for a boundary that must not be crossed in this scenario."""

    def _raise(_kwargs):
        raise AssertionError(message)

    return _raise


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


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


class _Gate2Harness:
    """All of gate2's boundaries wired with recording fakes whose behavior is driven by instance
    attributes. Defaults are the happy path: one backend domain, planning returns _PLAN, execution
    passes, verification mirrors tests_passed. Tests override the knobs their scenario needs:

        harness.routing = RoutingDecision(domains=["frontend"], parallel=False)
        harness.execute = lambda kw: ExecutionResult(..., tests_passed=kw["attempt"] == 2, ...)
        harness.verify = _forbidden("verification must not run")
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mp = monkeypatch
        self.store = _FakeTicketStore()

        # Recorded interactions.
        self.prs: list[tuple] = []
        self.jira_comments: list[tuple] = []
        self.github_comments: list[tuple] = []
        self.github_labels: list[tuple] = []
        self.jira_labels: list[tuple] = []
        self.execution_calls: list[int] = []
        self.branches: list[str] = []
        self.tool_call_caps: list[int | None] = []
        self.planning_feedbacks: list[str | None] = []
        self.verification_calls: list[dict] = []
        self.domain_events: list[str] = []

        # Behavior knobs.
        self.routing = RoutingDecision(domains=["backend"], parallel=False)
        self.on_domain_expert: Callable | None = None  # sync or async hook(domain)
        self.plan: Callable | None = None  # hook(kwargs) -> Plan
        self.execute: Callable | None = None  # hook(kwargs) -> ExecutionResult
        self.verify: Callable | None = None  # hook(kwargs) -> VerificationVerdict
        self.default_branch = "main"
        self.fail_github_label = False
        self.fail_jira_label = False

        self._wire_store()
        self._wire_clients()
        self._wire_agents()

    def _wire_store(self) -> None:
        mp, store = self._mp, self.store
        mp.setattr(gate2.firestore_client, "get_ticket", store.get_ticket)
        mp.setattr(gate2.firestore_client, "update_ticket", store.update_ticket)
        mp.setattr(gate2.firestore_client, "increment_retry_round", store.increment_retry_round)
        mp.setattr(gate2.firestore_client, "append_escalation", store.append_escalation)
        mp.setattr(gate2.firestore_client, "write_pr_pointer", store.write_pr_pointer)
        mp.setattr(gate2.firestore_client, "ticket_doc_id", store.ticket_doc_id)
        mp.setattr(gate2.firestore_client, "append_trace_id", store.append_trace_id)

    def _wire_clients(self) -> None:
        mp = self._mp

        async def fake_open_pull_request(repo, *, head, base, title, body):
            self.prs.append((repo, head, base, title, body))
            return 42, f"https://github.com/{repo}/pull/42"

        async def fake_get_default_branch(repo):
            return self.default_branch

        async def fake_add_comment(jira_key, body):
            self.jira_comments.append((jira_key, body))

        async def fake_post_issue_comment(repo, issue_number, body):
            self.github_comments.append((repo, issue_number, body))

        async def fake_add_github_label(repo, issue_number, label):
            if self.fail_github_label:
                raise RuntimeError("github label API is down")
            self.github_labels.append((repo, issue_number, label))

        async def fake_add_jira_label(jira_key, label):
            if self.fail_jira_label:
                raise RuntimeError("jira label API is down")
            self.jira_labels.append((jira_key, label))

        mp.setattr(gate2.github_client, "open_pull_request", fake_open_pull_request)
        mp.setattr(gate2.github_client, "get_default_branch", fake_get_default_branch)
        mp.setattr(gate2.jira_client, "add_comment", fake_add_comment)
        mp.setattr(gate2.github_client, "post_issue_comment", fake_post_issue_comment)
        mp.setattr(gate2.github_client, "add_label", fake_add_github_label)
        mp.setattr(gate2.jira_client, "add_label", fake_add_jira_label)

    def _wire_agents(self) -> None:
        mp = self._mp

        async def fake_run_routing(**kwargs):
            return self.routing

        async def fake_run_domain_expert(*, domain, issue_title, issue_body, repo_context=None):
            if self.on_domain_expert is not None:
                result = self.on_domain_expert(domain)
                if inspect.isawaitable(result):
                    await result
            return _domain_output(domain)

        async def fake_run_planning(**kwargs):
            self.planning_feedbacks.append(kwargs.get("prior_feedback"))
            if self.plan is not None:
                return self.plan(kwargs)
            return _PLAN

        async def fake_trigger_execution(**kwargs):
            self.execution_calls.append(kwargs["attempt"])
            self.branches.append(kwargs["branch"])
            self.tool_call_caps.append(kwargs.get("tool_call_cap"))
            if self.execute is not None:
                return self.execute(kwargs)
            return ExecutionResult(
                branch=kwargs["branch"], diff_summary="x", tests_passed=True, logs_uri="gs://x"
            )

        async def fake_run_verification(**kwargs):
            self.verification_calls.append(kwargs)
            if self.verify is not None:
                return self.verify(kwargs)
            passed = kwargs["execution_result"].tests_passed
            return VerificationVerdict(green=passed, feedback=None if passed else "tests failed")

        mp.setattr(gate2, "run_routing", fake_run_routing)
        mp.setattr(gate2, "run_domain_expert", fake_run_domain_expert)
        mp.setattr(gate2, "run_planning", fake_run_planning)
        mp.setattr(gate2.cloud_run_jobs, "trigger_execution", fake_trigger_execution)
        mp.setattr(gate2, "run_verification", fake_run_verification)

    def use_sink(self) -> _RecordingSink:
        sink = _RecordingSink()
        self._mp.setattr(gate2.firestore_client, "new_event_sink", lambda *a, **k: sink)
        return sink


@pytest.fixture
def harness(monkeypatch):
    return _Gate2Harness(monkeypatch)


@pytest.mark.asyncio
async def test_single_domain_routes_sequentially_and_multi_domain_dispatches_in_parallel(
    harness,
) -> None:
    harness.routing = RoutingDecision(domains=["frontend", "backend"], parallel=True)

    async def record(domain):
        harness.domain_events.append(f"start:{domain}")
        await asyncio.sleep(0.01 if domain == "frontend" else 0)
        harness.domain_events.append(f"end:{domain}")

    harness.on_domain_expert = record

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    # Parallel dispatch: both domains start before either finishes (backend, the faster one,
    # finishes before frontend even though frontend was started first).
    assert harness.domain_events == ["start:frontend", "start:backend", "end:backend", "end:frontend"]
    assert harness.store.doc.domains == ["frontend", "backend"]
    assert harness.store.doc.status == "pr_open"


@pytest.mark.asyncio
async def test_start_gate2_persists_routing_rationale_and_confidence(harness) -> None:
    # The routing decision's audit trail lands on the ticket doc next to `domains` — report-first
    # (recorded + surfaced, never gated on).
    harness.routing = RoutingDecision(
        domains=["backend"],
        parallel=False,
        rationale="Pure API change, no UI surface.",
        confidence="high",
    )

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.store.doc.routing_rationale == "Pure API change, no UI surface."
    assert harness.store.doc.routing_confidence == "high"


@pytest.mark.asyncio
async def test_start_gate2_threads_lens_criteria_into_verification(harness) -> None:
    # The routed domains' review criteria reach the verification agent.
    harness.routing = RoutingDecision(domains=["backend", "quantum-computing"], parallel=True)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    criteria = harness.verification_calls[0]["review_criteria"]
    assert criteria and all(c.startswith("[backend] ") for c in criteria)
    # The fallback-lens domain contributes no criteria — nothing bespoke to verify against.
    assert not any("quantum-computing" in c for c in criteria)


@pytest.mark.asyncio
async def test_pr_open_jira_comment_wraps_diff_summary_in_noformat(harness) -> None:
    """Jira wiki markup misreads a raw diffstat's own `+`/`-` characters as underline/strikethrough
    — wrapping it in {noformat} keeps it literal."""
    harness.execute = lambda kw: ExecutionResult(
        branch="artisan/x",
        diff_summary="README.md (modified) +141 -26",
        tests_passed=True,
        logs_uri="gs://x",
    )

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert len(harness.jira_comments) == 1
    _jira_key, body = harness.jira_comments[0]
    assert "{noformat}\nREADME.md (modified) +141 -26\n{noformat}" in body


@pytest.mark.asyncio
async def test_single_domain_dispatch_runs_sequentially_with_one_call(harness) -> None:
    harness.routing = RoutingDecision(domains=["frontend"], parallel=False)
    harness.on_domain_expert = lambda domain: harness.domain_events.append(domain)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.domain_events == ["frontend"]


@pytest.mark.asyncio
async def test_n_consecutive_failures_end_in_escalated_with_no_nplus1th_attempt(harness) -> None:
    harness.execute = lambda kw: ExecutionResult(
        branch="artisan/x", diff_summary="x", tests_passed=False, logs_uri="gs://x"
    )

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.execution_calls == [1, 2, 3]
    assert harness.store.doc.status == "escalated"
    assert len(harness.store.doc.escalation_history) == 1
    assert harness.store.doc.escalation_history[0].gate == "2"
    assert len(harness.jira_comments) == 1
    assert len(harness.github_comments) == 1
    assert harness.github_comments[0][:2] == (REPO, ISSUE_NUMBER)


@pytest.mark.asyncio
async def test_green_on_second_attempt_reaches_pr_open_with_retry_count_one(harness) -> None:
    harness.execute = lambda kw: ExecutionResult(
        branch=f"artisan/x-{kw['attempt']}",
        diff_summary="x",
        tests_passed=kw["attempt"] == 2,
        logs_uri="gs://x",
    )

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.execution_calls == [1, 2]
    assert harness.store.doc.retry_count == 1
    assert harness.store.doc.status == "pr_open"
    assert harness.store.doc.pr_url == "https://github.com/acme/demo/pull/42"
    assert harness.store.doc.pr_number == 42
    assert harness.store.pr_pointers == [(REPO, 42, ISSUE_NUMBER)]
    assert len(harness.prs) == 1
    assert len(harness.jira_comments) == 1
    assert len(harness.github_comments) == 0
    assert harness.github_labels == [(REPO, 42, "artisan:ready-for-review")]
    assert harness.jira_labels == [(JIRA_KEY, "artisan-pr-open")]


@pytest.mark.asyncio
async def test_not_met_criterion_overrides_holistic_green_and_retries(harness) -> None:
    """A not_met lens criterion forces the attempt red even when the model's holistic verdict is
    green; the criteria evidence becomes the retry feedback, and the next attempt (clean criteria)
    proceeds to PR."""
    calls = []

    def verify(kwargs):
        calls.append(1)
        if len(calls) == 1:
            return VerificationVerdict(
                green=True,
                criteria_results=[
                    CriterionResult(
                        criterion="[backend] Writes are idempotent or transactional",
                        evidence="The new endpoint performs two writes without a transaction.",
                        status="not_met",
                    )
                ],
            )
        return VerificationVerdict(green=True)

    harness.verify = verify

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.execution_calls == [1, 2]
    assert harness.store.doc.retry_count == 1
    assert harness.store.doc.status == "pr_open"
    assert len(harness.prs) == 1
    # The hard-gate's criteria evidence, not the model's (absent) holistic feedback, drove the retry.
    assert harness.planning_feedbacks[0] is None
    assert "not met" in harness.planning_feedbacks[1]
    assert "two writes without a transaction" in harness.planning_feedbacks[1]


@pytest.mark.asyncio
async def test_open_pr_and_sync_github_label_failure_does_not_abort_pr_flow(harness) -> None:
    """Labeling is a nice-to-have signal, not load-bearing — a label API hiccup must never prevent
    the PR/Jira-comment work that already succeeded from being reported as done."""
    harness.fail_github_label = True

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.store.doc.status == "pr_open"
    assert len(harness.prs) == 1
    assert len(harness.jira_comments) == 1
    assert harness.jira_labels == [(JIRA_KEY, "artisan-pr-open")]


@pytest.mark.asyncio
async def test_open_pr_and_sync_jira_label_failure_does_not_abort_pr_flow(harness) -> None:
    harness.fail_jira_label = True

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.store.doc.status == "pr_open"
    assert len(harness.prs) == 1
    assert len(harness.jira_comments) == 1
    assert harness.github_labels == [(REPO, 42, "artisan:ready-for-review")]


@pytest.mark.asyncio
async def test_pr_base_uses_repo_default_branch_not_hardcoded_main(harness) -> None:
    """Gate 2 used to open PRs against a hardcoded `main` — a repo whose default branch is
    `master`/`develop`/etc. got PRs targeted at the wrong branch. The PR base must be the repo's
    actual default branch, resolved when Gate 2 starts."""
    harness.default_branch = "develop"

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.store.doc.status == "pr_open"
    assert len(harness.prs) == 1
    assert harness.prs[0][2] == "develop"  # PR base is the repo's default branch, not `main`


@pytest.mark.asyncio
async def test_start_gate2_emits_gate_started_then_pr_opened_and_jira_synced(harness) -> None:
    sink = harness.use_sink()

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    types = [e["type"] for e in sink.events]
    assert types[0] == "gate_started"
    assert "pr_opened" in types
    assert "jira_synced" in types
    assert types.index("pr_opened") < types.index("jira_synced")


@pytest.mark.asyncio
async def test_start_gate2_retry_generation_zero_keeps_original_branch_format(harness) -> None:
    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")
    assert harness.branches == [f"artisan/{JIRA_KEY}-attempt-1"]


@pytest.mark.asyncio
async def test_start_gate2_retry_generation_nonzero_avoids_branch_collision(harness) -> None:
    await gate2.start_gate2(
        REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B", retry_generation=1
    )
    assert harness.branches == [f"artisan/{JIRA_KEY}-r1-attempt-1"]


@pytest.mark.asyncio
async def test_start_gate2_aborts_retry_loop_when_ticket_already_done(harness) -> None:
    """Issue deleted while Gate 2 was mid-flight lands the ticket in `done` — the retry loop must
    not burn a sandbox run on a dead issue."""
    harness.store.doc = harness.store.doc.model_copy(update={"status": "done"})
    harness.plan = _forbidden("planning must not run for a deleted issue")
    harness.execute = _forbidden("execution must not run for a deleted issue")

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.store.doc.status == "done"


@pytest.mark.asyncio
async def test_open_pr_is_skipped_when_ticket_deleted_during_execution(harness) -> None:
    """The deletion can land between the retry-loop's status check and the PR open — `_open_pr_and_sync`
    re-checks so a PR for a dead issue is never opened."""

    def delete_during_verification(kwargs):
        harness.store.doc = harness.store.doc.model_copy(update={"status": "done"})
        return VerificationVerdict(green=True)

    harness.verify = delete_during_verification

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.prs == []  # no PR opened for a deleted issue
    assert harness.store.doc.status == "done"


@pytest.mark.asyncio
async def test_escalate_is_skipped_when_ticket_deleted(harness) -> None:
    """Escalating a deleted issue would flip `done` back to `escalated` and 404 on the
    reporter-facing comment — the cleanup already closed the ticket out, so skip it."""
    harness.store.doc = harness.store.doc.model_copy(update={"status": "done"})

    await gate2._escalate(REPO, ISSUE_NUMBER, JIRA_KEY, reason="boom")

    assert harness.store.doc.escalation_history == []
    assert harness.store.doc.status == "done"  # not resurrected to escalated
    assert harness.jira_comments == []
    assert harness.github_comments == []


def _repo_context_of_size(file_count: int) -> RepoContext:
    return RepoContext(
        repo=REPO,
        head_sha="x",
        file_tree=[f"f{i}.py" for i in range(file_count)],
        manifests={},
        languages={},
        convention_docs={},
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_tool_call_cap_tiers_by_repo_size(harness, monkeypatch) -> None:
    """v2 exec-env: the coding agent's tool-call cap scales with repo size (bench evidence:
    real-scale repos escalated at the demo-tuned 40). The autouse fixture stubs repo_context to
    None; each iteration re-stubs it with a known file count."""
    for file_count, expected_cap in ((100, 40), (1000, 80), (6000, 120)):
        context = _repo_context_of_size(file_count)

        async def fake_get_repo_context(repo: str, _context=context) -> RepoContext:
            return _context

        monkeypatch.setattr(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)

        await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

        assert harness.tool_call_caps[-1] == expected_cap


@pytest.mark.asyncio
async def test_tool_call_cap_defaults_to_the_smallest_tier_without_repo_context(harness) -> None:
    """The autouse fixture's None repo_context (fetch failed) must not break the tiering — a
    missing context means a small/unknown repo, i.e. the v1 default cap."""
    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.tool_call_caps == [40]


@pytest.mark.asyncio
async def test_tool_call_cap_env_override_wins_over_the_tiers(harness, monkeypatch) -> None:
    monkeypatch.setattr(gate2, "CODING_AGENT_TOOL_CALL_CAP", 55)

    async def fake_get_repo_context(repo: str) -> RepoContext:
        return _repo_context_of_size(6000)

    monkeypatch.setattr(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)

    await gate2.start_gate2(REPO, ISSUE_NUMBER, JIRA_KEY, issue_title="T", issue_body="B")

    assert harness.tool_call_caps == [55]
