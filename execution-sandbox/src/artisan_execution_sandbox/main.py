"""Cloud Run Jobs entrypoint for one execution-sandbox attempt (SPRINT.md Phase 3.4). Reads the
env-var contract agents/gcp/cloud_run_jobs.py::trigger_execution sets on this execution
(GITHUB_REPO, ISSUE_NUMBER, BRANCH_NAME, PLAN_JSON, PRIOR_FEEDBACK), clones the repo, runs the
bounded coding agent against the Plan, runs the configured test command, commits + pushes, and
writes the resulting ExecutionResult back to Firestore.

Always exits 0 — a red test run, an incomplete coding attempt, or a clone/push failure is *data*
(`ExecutionResult.tests_passed=False`, a descriptive `diff_summary`), not a sandbox crash. A
nonzero exit is reserved for the sandbox failing to even write that result (a genuine crash),
which `agents/gcp/cloud_run_jobs.py::trigger_execution`'s own fallback-synthesis path is built to
handle."""

import asyncio
import os
import tempfile
from pathlib import Path

from artisan_execution_sandbox import git_ops, test_runner
from artisan_execution_sandbox.coding_agent import run_coding_agent
from artisan_execution_sandbox.config import CLOUD_RUN_REGION, GCP_PROJECT_ID
from artisan_execution_sandbox.firestore_write import write_execution_result
from artisan_execution_sandbox.github_auth import get_installation_token
from artisan_shared.models import ExecutionResult, Plan


def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    repo = os.environ["GITHUB_REPO"]
    issue_number = int(os.environ["ISSUE_NUMBER"])
    branch = os.environ["BRANCH_NAME"]
    plan = Plan.model_validate_json(os.environ["PLAN_JSON"])
    prior_feedback = os.environ.get("PRIOR_FEEDBACK") or None

    print(f"[artisan-execution-sandbox] attempt for {repo}#{issue_number}, branch={branch}")
    result = await run_attempt(repo=repo, branch=branch, plan=plan, prior_feedback=prior_feedback)
    print(f"[artisan-execution-sandbox] result: tests_passed={result.tests_passed}")
    await write_execution_result(repo, issue_number, result)


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
    *, repo: str, branch: str, plan: Plan, prior_feedback: str | None
) -> ExecutionResult:
    """Runs one full attempt (clone -> code -> test -> push) in a fresh temp checkout. Every
    failure path returns a failed `ExecutionResult` rather than raising, so `main()` always
    reaches its Firestore write."""
    token = await get_installation_token()

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
        summary = await run_coding_agent(workdir=workdir, plan=plan, prior_feedback=prior_feedback)

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
