"""Triggers one attempt of the `execution-sandbox` Cloud Run Job and waits for it to complete
(SYSTEM_DESIGN.md §4 step 3, MILESTONE.md Phase 3.4).

Decision (Sprint 3, confirmed with the user — see docs/CONTEXT.md): trigger-and-await
synchronously inside the same `/pubsub/push` request, rather than building a separate async
completion signal. `JobsAsyncClient.run_job(...)` returns a long-running operation; awaiting its
`.result()` already polls internally until the `Execution` reaches a terminal state — no custom
poll loop needed. Cloud Run services support request timeouts up to 60 minutes, comfortably
covering one clone+code+test attempt against the single demo repo. An async completion signal
(the job posting back via a webhook or a second Pub/Sub topic) would be more correct for very
long-running production executions, but adds a new ingress route, correlation-id bookkeeping, and
idempotency handling with no payoff at this scope/timeline.

The job itself does not return `ExecutionResult` as RPC response data — Cloud Run Jobs' completed
`Execution` proto only reports whether it succeeded/failed, not arbitrary payload. Instead the job
writes `ExecutionResult` directly onto the ticket's Firestore doc (`last_execution_result` —
`execution-sandbox@` already has Firestore write access), and this module reads it back after the
execution completes, matching it against the `branch` we asked for (so a fresh write for *this*
attempt is never confused with a stale one from a previous attempt on the same ticket)."""

from functools import lru_cache

from artisan_shared.models import ConflictDetectionResult, ExecutionResult, Plan
from google.cloud import run_v2

from artisan_agents.config import (
    CLOUD_RUN_REGION,
    EXECUTION_SANDBOX_JOB_NAME,
    GCP_PROJECT_ID,
)
from artisan_agents.event_context import current_sink
from artisan_agents.gcp import firestore_client


class ConflictDetectionCrashed(Exception):
    """Raised when execution-sandbox's `detect_conflict` mode never wrote a
    `last_conflict_detection` matching this check's `head_sha`. Unlike a crashed *execution*
    (trigger_execution's silent fallback-synthesis — a failed ExecutionResult is still safely
    representable and flows through the normal verify/retry decision), a crashed *detection* has no
    honest default to synthesize: neither has_conflict=True nor False can be assumed from nothing.
    The caller must escalate directly, not guess a classification."""


@lru_cache(maxsize=1)
def _jobs_client() -> run_v2.JobsAsyncClient:
    return run_v2.JobsAsyncClient()


def _job_path() -> str:
    return run_v2.JobsAsyncClient.job_path(
        GCP_PROJECT_ID, CLOUD_RUN_REGION, EXECUTION_SANDBOX_JOB_NAME
    )


def _build_request(
    *, ticket_id: str, repo: str, issue_number: int, branch: str, plan: Plan, attempt: int,
    feedback: str | None,
) -> run_v2.RunJobRequest:
    env = [
        run_v2.EnvVar(name="TICKET_ID", value=ticket_id),
        run_v2.EnvVar(name="GITHUB_REPO", value=repo),
        run_v2.EnvVar(name="ISSUE_NUMBER", value=str(issue_number)),
        run_v2.EnvVar(name="BRANCH_NAME", value=branch),
        run_v2.EnvVar(name="ATTEMPT_NUMBER", value=str(attempt)),
        run_v2.EnvVar(name="PLAN_JSON", value=plan.model_dump_json()),
        run_v2.EnvVar(name="PRIOR_FEEDBACK", value=feedback or ""),
    ]
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(env=env)]
    )
    return run_v2.RunJobRequest(name=_job_path(), overrides=overrides)


async def trigger_execution(
    *, repo: str, issue_number: int, branch: str, plan: Plan, attempt: int, feedback: str | None
) -> ExecutionResult:
    """Runs the execution-sandbox Cloud Run Job for one attempt, blocking until it completes, then
    reads the `ExecutionResult` the job itself wrote to Firestore."""
    ticket_id = firestore_client.ticket_doc_id(repo, issue_number)
    request = _build_request(
        ticket_id=ticket_id, repo=repo, issue_number=issue_number, branch=branch, plan=plan,
        attempt=attempt, feedback=feedback,
    )
    await current_sink().emit(
        type="job_started", summary=f"execution-sandbox: attempt {attempt} on {branch}"
    )
    operation = await _jobs_client().run_job(request=request)
    execution = await operation.result()

    ticket = await firestore_client.get_ticket(repo, issue_number)
    fresh_result = (
        ticket.last_execution_result
        if ticket is not None
        and ticket.last_execution_result is not None
        and ticket.last_execution_result.branch == branch
        else None
    )
    if fresh_result is not None:
        await current_sink().emit(
            type="job_completed",
            summary=f"execution-sandbox finished: tests_passed={fresh_result.tests_passed}",
        )
        return fresh_result

    # The sandbox crashed or otherwise failed to write a result for this attempt (e.g. OOM, a
    # container-level crash before its final Firestore write) — don't hang or raise; synthesize a
    # failed ExecutionResult so the retry loop can still make a decision.
    await current_sink().emit(
        type="error", summary="execution-sandbox did not report a result for this attempt"
    )
    return ExecutionResult(
        branch=branch,
        diff_summary="execution-sandbox did not report a result for this attempt",
        tests_passed=False,
        logs_uri=getattr(execution, "log_uri", "") or "",
    )


def _build_conflict_request(
    *, job_mode: str, repo: str, issue_number: int, base_branch: str, head_branch: str,
    head_sha: str | None = None,
) -> run_v2.RunJobRequest:
    env = [
        run_v2.EnvVar(name="JOB_MODE", value=job_mode),
        run_v2.EnvVar(name="GITHUB_REPO", value=repo),
        run_v2.EnvVar(name="ISSUE_NUMBER", value=str(issue_number)),
        run_v2.EnvVar(name="BASE_BRANCH", value=base_branch),
        run_v2.EnvVar(name="HEAD_BRANCH", value=head_branch),
    ]
    if head_sha is not None:
        env.append(run_v2.EnvVar(name="HEAD_SHA", value=head_sha))
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(env=env)]
    )
    return run_v2.RunJobRequest(name=_job_path(), overrides=overrides)


async def trigger_conflict_detection(
    *, repo: str, issue_number: int, base_branch: str, head_branch: str, head_sha: str,
) -> ConflictDetectionResult:
    """Runs execution-sandbox in `detect_conflict` mode (Gate 3, MILESTONE.md Phase 4.1), blocking
    until it completes, then reads the `ConflictDetectionResult` back from Firestore."""
    request = _build_conflict_request(
        job_mode="detect_conflict", repo=repo, issue_number=issue_number, base_branch=base_branch,
        head_branch=head_branch, head_sha=head_sha,
    )
    await current_sink().emit(type="job_started", summary=f"execution-sandbox: detect_conflict at {head_sha}")
    operation = await _jobs_client().run_job(request=request)
    await operation.result()

    ticket = await firestore_client.get_ticket(repo, issue_number)
    fresh = (
        ticket.last_conflict_detection
        if ticket is not None
        and ticket.last_conflict_detection is not None
        and ticket.last_conflict_detection.head_sha == head_sha
        else None
    )
    if fresh is not None:
        await current_sink().emit(
            type="job_completed", summary=f"detect_conflict finished: has_conflict={fresh.has_conflict}"
        )
        return fresh

    await current_sink().emit(
        type="error", summary=f"no conflict-detection result at head_sha={head_sha}"
    )
    raise ConflictDetectionCrashed(
        f"no conflict-detection result for {repo}#{issue_number} at head_sha={head_sha}"
    )


async def trigger_conflict_resolution(
    *, repo: str, issue_number: int, base_branch: str, head_branch: str
) -> ExecutionResult:
    """Runs execution-sandbox in `resolve_conflict` mode (Gate 3, MILESTONE.md Phase 4.3), blocking
    until it completes, then reads the `ExecutionResult` back from Firestore, matched on `branch`
    exactly like `trigger_execution`. Mirrors `trigger_execution`'s crash fallback (synthesizes a
    failed result) rather than raising — a crashed resolution and a real red test run are treated
    identically by gate3.py: escalate, no retry."""
    request = _build_conflict_request(
        job_mode="resolve_conflict", repo=repo, issue_number=issue_number, base_branch=base_branch,
        head_branch=head_branch,
    )
    await current_sink().emit(type="job_started", summary=f"execution-sandbox: resolve_conflict on {head_branch}")
    operation = await _jobs_client().run_job(request=request)
    execution = await operation.result()

    ticket = await firestore_client.get_ticket(repo, issue_number)
    fresh_result = (
        ticket.last_conflict_resolution
        if ticket is not None
        and ticket.last_conflict_resolution is not None
        and ticket.last_conflict_resolution.branch == head_branch
        else None
    )
    if fresh_result is not None:
        await current_sink().emit(
            type="job_completed",
            summary=f"resolve_conflict finished: tests_passed={fresh_result.tests_passed}",
        )
        return fresh_result

    await current_sink().emit(
        type="error", summary="execution-sandbox did not report a conflict-resolution result"
    )
    return ExecutionResult(
        branch=head_branch,
        diff_summary="execution-sandbox did not report a conflict-resolution result",
        tests_passed=False,
        logs_uri=getattr(execution, "log_uri", "") or "",
    )
