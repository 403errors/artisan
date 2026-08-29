"""Cloud Run Jobs entrypoint for execution-sandbox (MILESTONE.md Phase 3.4 / Phase 4.1-4.3). `JOB_MODE`
selects behavior, defaulting to `execute` (Gate 2 back-compat, no env-var change for existing
callers):
- `execute`: reads GITHUB_REPO/ISSUE_NUMBER/BRANCH_NAME/PLAN_JSON/PRIOR_FEEDBACK, clones the repo,
  runs the bounded coding agent against the Plan, runs the configured test command, commits +
  pushes, and writes the resulting ExecutionResult back to Firestore.
- `detect_conflict` (Gate 3): reads GITHUB_REPO/ISSUE_NUMBER/BASE_BRANCH/HEAD_BRANCH/HEAD_SHA,
  attempts a real trial merge, and writes a ConflictDetectionResult.
- `resolve_conflict` (Gate 3): reads GITHUB_REPO/ISSUE_NUMBER/BASE_BRANCH/HEAD_BRANCH, re-does its
  own fresh trial merge, runs the bounded conflict-resolution coding agent if still conflicted,
  and writes an ExecutionResult — never pushing unless the full test suite passes (Phase 4.3's
  literal DoD; unlike `execute`'s Gate 2 path, which always pushes and lets Verification decide).

Always exits 0 — a red test run, an incomplete coding attempt, or a clone/push failure is *data*
(`ExecutionResult.tests_passed=False`, a descriptive `diff_summary`), not a sandbox crash. A
nonzero exit is reserved for the sandbox failing to even write that result (a genuine crash),
which `agents/gcp/cloud_run_jobs.py`'s own fallback-synthesis paths are built to handle."""

import asyncio
import os
import tempfile
from pathlib import Path

from artisan_execution_sandbox import firestore_write, git_ops, test_runner
from artisan_execution_sandbox.coding_agent import run_coding_agent, run_conflict_resolution_agent
from artisan_execution_sandbox.config import CLOUD_RUN_REGION, GCP_PROJECT_ID
from artisan_execution_sandbox.firestore_write import (
    write_conflict_detection_result,
    write_conflict_resolution_result,
    write_execution_result,
)
from artisan_execution_sandbox.github_auth import get_installation_token
from artisan_shared.models import ConflictDetectionResult, ExecutionResult, Plan
from artisan_shared.ticket_ids import ticket_doc_id

JOB_MODE_EXECUTE = "execute"
JOB_MODE_DETECT_CONFLICT = "detect_conflict"
JOB_MODE_RESOLVE_CONFLICT = "resolve_conflict"


def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    mode = os.environ.get("JOB_MODE", JOB_MODE_EXECUTE)
    repo = os.environ["GITHUB_REPO"]
    issue_number = int(os.environ["ISSUE_NUMBER"])

    if mode == JOB_MODE_EXECUTE:
        branch = os.environ["BRANCH_NAME"]
        plan = Plan.model_validate_json(os.environ["PLAN_JSON"])
        prior_feedback = os.environ.get("PRIOR_FEEDBACK") or None
        print(f"[artisan-execution-sandbox] attempt for {repo}#{issue_number}, branch={branch}")
        result = await run_attempt(
            repo=repo, branch=branch, plan=plan, prior_feedback=prior_feedback, issue_number=issue_number
        )
        print(f"[artisan-execution-sandbox] result: tests_passed={result.tests_passed}")
        await write_execution_result(repo, issue_number, result)
    elif mode == JOB_MODE_DETECT_CONFLICT:
        base_branch = os.environ["BASE_BRANCH"]
        head_branch = os.environ["HEAD_BRANCH"]
        head_sha = os.environ["HEAD_SHA"]
        print(f"[artisan-execution-sandbox] conflict check for {repo}#{issue_number}, "
              f"{head_branch} <- {base_branch}")
        detection = await run_conflict_detection(
            repo=repo, base_branch=base_branch, head_branch=head_branch, head_sha=head_sha
        )
        print(f"[artisan-execution-sandbox] result: has_conflict={detection.has_conflict}")
        await write_conflict_detection_result(repo, issue_number, detection)
    elif mode == JOB_MODE_RESOLVE_CONFLICT:
        base_branch = os.environ["BASE_BRANCH"]
        head_branch = os.environ["HEAD_BRANCH"]
        print(f"[artisan-execution-sandbox] conflict resolution for {repo}#{issue_number}, "
              f"{head_branch} <- {base_branch}")
        resolution = await run_conflict_resolution(
            repo=repo, base_branch=base_branch, head_branch=head_branch, issue_number=issue_number
        )
        print(f"[artisan-execution-sandbox] result: tests_passed={resolution.tests_passed}")
        await write_conflict_resolution_result(repo, issue_number, resolution)
    else:
        raise ValueError(f"unknown JOB_MODE: {mode!r}")


def _logs_uri() -> str:
    """Best-effort Cloud Logging console link for this execution, built from the standard
    CLOUD_RUN_EXECUTION env var Cloud Run Jobs sets automatically. Empty outside Cloud Run (e.g.
    local/manual runs), since there's no execution id to link to."""
    execution = os.environ.get("CLOUD_RUN_EXECUTION", "")
    if not execution:
        return ""
    return (
        "https://console.cloud.google.com/run/jobs/executions/details/"
        f"{CLOUD_RUN_REGION}/{execution}/logs?project={GCP_PROJECT_ID}"
    )


async def run_attempt(
    *,
    repo: str,
    branch: str,
    plan: Plan,
    prior_feedback: str | None,
    issue_number: int | None = None,
) -> ExecutionResult:
    """Runs one full attempt (clone -> code -> test -> push) in a fresh temp checkout. Every
    failure path returns a failed `ExecutionResult` rather than raising, so `main()` always
    reaches its Firestore write.

    `issue_number` is optional (tests calling this directly omit it) — when given, a real
    Sprint-6 EventSink is constructed and every coding-agent tool call gets logged; when absent,
    the coding agent silently runs with no event log, exactly as before."""
    token = await get_installation_token()
    sink = (
        firestore_write.new_event_sink(ticket_doc_id(repo, issue_number), gate="2", redact_token=token)
        if issue_number is not None
        else None
    )

    with tempfile.TemporaryDirectory(prefix="artisan-execution-") as tmp:
        workdir = Path(tmp) / "repo"
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

        print("[artisan-execution-sandbox] cloning...")
        try:
            git_ops.clone(remote_url, str(workdir), redact=token)
            git_ops.create_branch(str(workdir), branch)
        except git_ops.GitCommandError as exc:
            return ExecutionResult(
                branch=branch, diff_summary=f"clone/branch failed: {exc}", tests_passed=False,
                logs_uri=_logs_uri(),
            )

        print("[artisan-execution-sandbox] running coding agent...")
        summary = await run_coding_agent(
            workdir=workdir, plan=plan, prior_feedback=prior_feedback, sink=sink
        )

        diff_summary = git_ops.stage_all_and_diff_stat(str(workdir))
        if not git_ops.has_staged_changes(str(workdir)):
            return ExecutionResult(
                branch=branch,
                diff_summary=f"coding agent made no changes. Summary: {summary}",
                tests_passed=False,
                logs_uri=_logs_uri(),
            )

        print("[artisan-execution-sandbox] running tests...")
        tests_passed, test_output = test_runner.run_tests(str(workdir))
        print(test_output)

        git_ops.commit_all(str(workdir), f"Artisan: {summary}"[:200])

        print("[artisan-execution-sandbox] pushing...")
        try:
            git_ops.push(str(workdir), branch, token=token, repo=repo)
        except git_ops.GitCommandError as exc:
            return ExecutionResult(
                branch=branch, diff_summary=diff_summary, tests_passed=False,
                logs_uri=f"push failed: {exc}",
            )

        return ExecutionResult(
            branch=branch,
            diff_summary=f"{summary}\n\n{diff_summary}",
            tests_passed=tests_passed,
            logs_uri=_logs_uri(),
        )


async def run_conflict_detection(
    *, repo: str, base_branch: str, head_branch: str, head_sha: str
) -> ConflictDetectionResult:
    """One real trial merge (Gate 3, MILESTONE.md Phase 4.1/4.2) — checks out the PR's HEAD branch
    and merges BASE into it (never the reverse: merging head into a base checkout would produce a
    commit that isn't a fast-forward of head, forcing a force-push on resolution — PRD.md §5
    forbids force-pushing). Always returns data, never raises. `has_conflict=True` is the fail-safe
    default on an ambiguous git-level error — silently reporting "no conflict" when we actually
    don't know would let a real conflict slip past undetected."""
    token = await get_installation_token()

    with tempfile.TemporaryDirectory(prefix="artisan-conflict-detect-") as tmp:
        workdir = Path(tmp) / "repo"
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

        try:
            git_ops.clone(remote_url, str(workdir), redact=token)
            git_ops.fetch(str(workdir), head_branch, redact=token)
            git_ops.checkout(str(workdir), head_branch)
            git_ops.fetch(str(workdir), base_branch, redact=token)
            merged_clean, merge_output = git_ops.merge(str(workdir), base_branch)
        except git_ops.GitCommandError as exc:
            return ConflictDetectionResult(
                has_conflict=True, conflicted_files=[], conflict_markers="", base_branch_history="",
                diff_summary=f"conflict check failed: {exc}", logs_uri=_logs_uri(), head_sha=head_sha,
            )

        if merged_clean:
            return ConflictDetectionResult(
                has_conflict=False, conflicted_files=[], conflict_markers="", base_branch_history="",
                diff_summary=merge_output, logs_uri=_logs_uri(), head_sha=head_sha,
            )

        conflicted_files = git_ops.list_conflicted_files(str(workdir))
        return ConflictDetectionResult(
            has_conflict=True,
            conflicted_files=conflicted_files,
            conflict_markers=git_ops.read_conflict_markers(str(workdir), conflicted_files),
            base_branch_history=git_ops.log_for_paths(str(workdir), base_branch, conflicted_files),
            diff_summary=merge_output,
            logs_uri=_logs_uri(),
            head_sha=head_sha,
        )


async def run_conflict_resolution(
    *, repo: str, base_branch: str, head_branch: str, issue_number: int | None = None
) -> ExecutionResult:
    """Gate 3's one capped resolution attempt (MILESTONE.md Phase 4.3 — no internal retry, mirrors
    `run_attempt`'s always-return-data shape). Re-does its own fresh clone+merge rather than
    trusting an earlier detection job's result — if the conflict has since cleared (e.g. a human
    already fixed it), this just reports a clean, no-op-ish success rather than blindly trusting a
    stale classification. Unlike `run_attempt`, never pushes unless the full suite passes.

    `issue_number` is optional exactly like `run_attempt`'s — see its docstring."""
    token = await get_installation_token()
    sink = (
        firestore_write.new_event_sink(ticket_doc_id(repo, issue_number), gate="3", redact_token=token)
        if issue_number is not None
        else None
    )

    with tempfile.TemporaryDirectory(prefix="artisan-conflict-resolve-") as tmp:
        workdir = Path(tmp) / "repo"
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

        try:
            git_ops.clone(remote_url, str(workdir), redact=token)
            git_ops.fetch(str(workdir), head_branch, redact=token)
            git_ops.checkout(str(workdir), head_branch)
            git_ops.fetch(str(workdir), base_branch, redact=token)
            merged_clean, merge_output = git_ops.merge(str(workdir), base_branch)
        except git_ops.GitCommandError as exc:
            return ExecutionResult(
                branch=head_branch, diff_summary=f"clone/merge failed: {exc}", tests_passed=False,
                logs_uri=_logs_uri(),
            )

        if merged_clean:
            summary = "merge applied cleanly, nothing to resolve"
        else:
            conflicted_files = git_ops.list_conflicted_files(str(workdir))
            markers = git_ops.read_conflict_markers(str(workdir), conflicted_files)
            summary = await run_conflict_resolution_agent(
                workdir=workdir, conflicted_files=conflicted_files, conflict_markers=markers, sink=sink
            )

        diff_summary = git_ops.stage_all_and_diff_stat(str(workdir))
        if not git_ops.has_staged_changes(str(workdir)):
            return ExecutionResult(
                branch=head_branch, diff_summary=f"no changes after resolution. {summary}",
                tests_passed=False, logs_uri=_logs_uri(),
            )

        print("[artisan-execution-sandbox] running tests...")
        tests_passed, test_output = test_runner.run_tests(str(workdir))
        print(test_output)

        git_ops.commit_all(str(workdir), f"Artisan: resolve merge conflict — {summary}"[:200])

        if not tests_passed:
            # Phase 4.3's literal DoD: full suite must pass BEFORE push — never push a failing
            # resolution, unlike Gate 2's run_attempt which always pushes and lets Verification
            # decide.
            return ExecutionResult(
                branch=head_branch, diff_summary=diff_summary, tests_passed=False,
                logs_uri=_logs_uri(),
            )

        try:
            git_ops.push(str(workdir), head_branch, token=token, repo=repo)
        except git_ops.GitCommandError as exc:
            return ExecutionResult(
                branch=head_branch, diff_summary=diff_summary, tests_passed=False,
                logs_uri=f"push failed: {exc}",
            )

        return ExecutionResult(
            branch=head_branch,
            diff_summary=f"{summary}\n\n{diff_summary}",
            tests_passed=True,
            logs_uri=_logs_uri(),
        )
