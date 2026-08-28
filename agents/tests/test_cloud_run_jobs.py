"""Unit tests for the orchestrator-side Cloud Run Jobs trigger (Phase 3.4). Fakes the
`JobsAsyncClient`/operation/`Execution` and Firestore ticket read — the real `run_job` round-trip
against a live Cloud Run Job execution is a live-only verification (see docs/CONTEXT.md), not
something a unit test can cover by definition."""

from datetime import UTC, datetime

import pytest

from artisan_agents.gcp import cloud_run_jobs
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import ExecutionResult, Plan

REPO = "acme/demo"
ISSUE_NUMBER = 1
BRANCH = "artisan/ART-1-attempt-1"
_PLAN = Plan(steps=["step"], touched_files=["a.py"], test_cases=["t"], doc_updates=["d"])


class _FakeExecution:
    def __init__(self, log_uri: str = "https://console.cloud.google.com/logs/x") -> None:
        self.log_uri = log_uri


class _FakeOperation:
    def __init__(self, execution: _FakeExecution) -> None:
        self._execution = execution

    async def result(self):
        return self._execution


class _FakeJobsClient:
    def __init__(self, execution: _FakeExecution) -> None:
        self._execution = execution
        self.requests = []

    async def run_job(self, *, request):
        self.requests.append(request)
        return _FakeOperation(self._execution)


def _ticket(*, last_execution_result: ExecutionResult | None) -> TicketDoc:
    now = datetime.now(UTC)
    return TicketDoc(
        github_issue_number=ISSUE_NUMBER,
        github_repo=REPO,
        jira_key="ART-1",
        status="in_progress",
        last_execution_result=last_execution_result,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_reads_fresh_execution_result_written_by_the_job(monkeypatch) -> None:
    expected = ExecutionResult(branch=BRANCH, diff_summary="did the thing", tests_passed=True, logs_uri="gs://x")
    fake_client = _FakeJobsClient(_FakeExecution())

    monkeypatch.setattr(cloud_run_jobs, "_jobs_client", lambda: fake_client)
    monkeypatch.setattr(cloud_run_jobs, "_job_path", lambda: "projects/p/locations/l/jobs/j")

    async def fake_get_ticket(repo, issue_number):
        return _ticket(last_execution_result=expected)

    monkeypatch.setattr(cloud_run_jobs.firestore_client, "get_ticket", fake_get_ticket)

    result = await cloud_run_jobs.trigger_execution(
        repo=REPO, issue_number=ISSUE_NUMBER, branch=BRANCH, plan=_PLAN, attempt=1, feedback=None
    )
    assert result == expected
    assert len(fake_client.requests) == 1


@pytest.mark.asyncio
async def test_stale_result_from_a_prior_attempt_is_not_mistaken_for_this_attempts_result(
    monkeypatch,
) -> None:
    stale = ExecutionResult(
        branch="artisan/ART-1-attempt-0", diff_summary="old", tests_passed=True, logs_uri="gs://old"
    )
    fake_client = _FakeJobsClient(_FakeExecution(log_uri="gs://fallback-logs"))

    monkeypatch.setattr(cloud_run_jobs, "_jobs_client", lambda: fake_client)
    monkeypatch.setattr(cloud_run_jobs, "_job_path", lambda: "projects/p/locations/l/jobs/j")

    async def fake_get_ticket(repo, issue_number):
        return _ticket(last_execution_result=stale)

    monkeypatch.setattr(cloud_run_jobs.firestore_client, "get_ticket", fake_get_ticket)

    result = await cloud_run_jobs.trigger_execution(
        repo=REPO, issue_number=ISSUE_NUMBER, branch=BRANCH, plan=_PLAN, attempt=1, feedback=None
    )
    assert result.tests_passed is False
    assert result.branch == BRANCH
    assert result.logs_uri == "gs://fallback-logs"


@pytest.mark.asyncio
async def test_job_crash_with_no_written_result_synthesizes_a_failed_result(monkeypatch) -> None:
    fake_client = _FakeJobsClient(_FakeExecution(log_uri="gs://crash-logs"))

    monkeypatch.setattr(cloud_run_jobs, "_jobs_client", lambda: fake_client)
    monkeypatch.setattr(cloud_run_jobs, "_job_path", lambda: "projects/p/locations/l/jobs/j")

    async def fake_get_ticket(repo, issue_number):
        return _ticket(last_execution_result=None)

    monkeypatch.setattr(cloud_run_jobs.firestore_client, "get_ticket", fake_get_ticket)

    result = await cloud_run_jobs.trigger_execution(
        repo=REPO, issue_number=ISSUE_NUMBER, branch=BRANCH, plan=_PLAN, attempt=1, feedback=None
    )
    assert result.tests_passed is False
    assert result.logs_uri == "gs://crash-logs"


@pytest.mark.asyncio
async def test_env_vars_carry_plan_and_feedback_for_the_attempt(monkeypatch) -> None:
    fake_client = _FakeJobsClient(_FakeExecution())
    monkeypatch.setattr(cloud_run_jobs, "_jobs_client", lambda: fake_client)
    monkeypatch.setattr(cloud_run_jobs, "_job_path", lambda: "projects/p/locations/l/jobs/j")

    async def fake_get_ticket(repo, issue_number):
        return _ticket(last_execution_result=ExecutionResult(
            branch=BRANCH, diff_summary="x", tests_passed=True, logs_uri="gs://x"
        ))

    monkeypatch.setattr(cloud_run_jobs.firestore_client, "get_ticket", fake_get_ticket)

    await cloud_run_jobs.trigger_execution(
        repo=REPO, issue_number=ISSUE_NUMBER, branch=BRANCH, plan=_PLAN, attempt=2,
        feedback="fix the color",
    )
    env_by_name = {
        e.name: e.value for e in fake_client.requests[0].overrides.container_overrides[0].env
    }
    assert env_by_name["GITHUB_REPO"] == REPO
    assert env_by_name["ISSUE_NUMBER"] == str(ISSUE_NUMBER)
    assert env_by_name["BRANCH_NAME"] == BRANCH
    assert env_by_name["ATTEMPT_NUMBER"] == "2"
    assert env_by_name["PRIOR_FEEDBACK"] == "fix the color"
    assert "step" in env_by_name["PLAN_JSON"]
