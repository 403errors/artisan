"""Tests for main.py's run_attempt (Phase 3.4): the clone/code/test/push sequence and its failure
paths, all faked (git_ops, coding_agent, test_runner, github_auth) — this is about the sequencing
and failure handling, not any one integration. The real end-to-end job run against a live repo is
a live-only verification (see docs/CONTEXT.md)."""

import pytest

from artisan_execution_sandbox import main as main_module
from artisan_execution_sandbox.git_ops import GitCommandError
from artisan_shared.models import Plan

_PLAN = Plan(steps=["step"], touched_files=["a.py"], test_cases=["t"], doc_updates=["d"])


@pytest.fixture(autouse=True)
def stub_token(monkeypatch):
    async def fake_get_installation_token():
        return "fake-token"

    monkeypatch.setattr(main_module, "get_installation_token", fake_get_installation_token)


@pytest.mark.asyncio
async def test_happy_path_returns_passed_result(monkeypatch) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    push_calls = []
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: push_calls.append((a, k)))
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))

    async def fake_run_coding_agent(**kwargs):
        return "did the thing"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert result.tests_passed is True
    assert result.branch == "artisan/x-1"
    assert "did the thing" in result.diff_summary
    assert len(push_calls) == 1


@pytest.mark.asyncio
async def test_clone_failure_returns_failed_result_without_raising(monkeypatch) -> None:
    def fake_clone(*a, **k):
        raise GitCommandError("clone failed: repo not found")

    monkeypatch.setattr(main_module.git_ops, "clone", fake_clone)

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert result.tests_passed is False
    assert "clone/branch failed" in result.diff_summary


@pytest.mark.asyncio
async def test_no_changes_from_coding_agent_is_a_failed_result(monkeypatch) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: False)

    async def fake_run_coding_agent(**kwargs):
        return "(coding agent did not call finish)"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert result.tests_passed is False
    assert "no changes" in result.diff_summary


@pytest.mark.asyncio
async def test_push_failure_returns_failed_result_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))

    def fake_push(*a, **k):
        raise GitCommandError("push failed: permission denied")

    monkeypatch.setattr(main_module.git_ops, "push", fake_push)

    async def fake_run_coding_agent(**kwargs):
        return "did the thing"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert result.tests_passed is False
    assert "push failed" in result.logs_uri
