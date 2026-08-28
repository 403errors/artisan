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


def _stub_clean_merge(monkeypatch) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "checkout", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "merge", lambda *a, **k: (True, "clean merge output"))


def _stub_conflicted_merge(monkeypatch, *, conflicted_files=("shared.py",)) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "checkout", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "merge", lambda *a, **k: (False, "CONFLICT output"))
    monkeypatch.setattr(main_module.git_ops, "list_conflicted_files", lambda repo_dir: list(conflicted_files))
    monkeypatch.setattr(main_module.git_ops, "read_conflict_markers", lambda repo_dir, files: "<<<<<<< markers")
    monkeypatch.setattr(main_module.git_ops, "log_for_paths", lambda *a, **k: "base history")


@pytest.mark.asyncio
async def test_conflict_detection_clean_merge_reports_no_conflict(monkeypatch) -> None:
    _stub_clean_merge(monkeypatch)

    result = await main_module.run_conflict_detection(
        repo="acme/demo", base_branch="main", head_branch="feature", head_sha="deadbeef"
    )

    assert result.has_conflict is False
    assert result.conflicted_files == []
    assert result.head_sha == "deadbeef"


@pytest.mark.asyncio
async def test_conflict_detection_real_conflict_reports_files_and_markers(monkeypatch) -> None:
    _stub_conflicted_merge(monkeypatch)

    result = await main_module.run_conflict_detection(
        repo="acme/demo", base_branch="main", head_branch="feature", head_sha="deadbeef"
    )

    assert result.has_conflict is True
    assert result.conflicted_files == ["shared.py"]
    assert "<<<<<<<" in result.conflict_markers
    assert result.base_branch_history == "base history"


@pytest.mark.asyncio
async def test_conflict_detection_git_error_fails_safe_to_has_conflict_true(monkeypatch) -> None:
    def fake_clone(*a, **k):
        raise GitCommandError("clone failed: repo not found")

    monkeypatch.setattr(main_module.git_ops, "clone", fake_clone)

    result = await main_module.run_conflict_detection(
        repo="acme/demo", base_branch="main", head_branch="feature", head_sha="deadbeef"
    )

    assert result.has_conflict is True


@pytest.mark.asyncio
async def test_conflict_resolution_success_pushes_and_reports_tests_passed(monkeypatch) -> None:
    _stub_conflicted_merge(monkeypatch)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))
    push_calls = []
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: push_calls.append((a, k)))

    async def fake_run_conflict_resolution_agent(**kwargs):
        return "resolved shared.py"

    monkeypatch.setattr(main_module, "run_conflict_resolution_agent", fake_run_conflict_resolution_agent)

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert result.tests_passed is True
    assert result.branch == "feature"
    assert len(push_calls) == 1


@pytest.mark.asyncio
async def test_conflict_resolution_forced_test_failure_does_not_push_and_reports_failed(
    monkeypatch,
) -> None:
    """Phase 4.3's literal DoD: full suite must pass BEFORE push. This proves the sandbox itself
    never pushes a failing resolution — the "no second attempt" half of the DoD is gate3.py's/the
    Firestore cap's responsibility, tested separately in test_gate3.py."""
    _stub_conflicted_merge(monkeypatch)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (False, "FAILED"))
    push_calls = []
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: push_calls.append((a, k)))

    async def fake_run_conflict_resolution_agent(**kwargs):
        return "resolved shared.py"

    monkeypatch.setattr(main_module, "run_conflict_resolution_agent", fake_run_conflict_resolution_agent)

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert result.tests_passed is False
    assert push_calls == []


@pytest.mark.asyncio
async def test_conflict_resolution_clean_merge_needs_no_agent_and_still_tests(monkeypatch) -> None:
    _stub_clean_merge(monkeypatch)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: None)

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert result.tests_passed is True
    assert "nothing to resolve" in result.diff_summary


@pytest.mark.asyncio
async def test_conflict_resolution_merge_error_returns_failed_result_without_raising(monkeypatch) -> None:
    def fake_clone(*a, **k):
        raise GitCommandError("clone failed: repo not found")

    monkeypatch.setattr(main_module.git_ops, "clone", fake_clone)

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert result.tests_passed is False
    assert "clone/merge failed" in result.diff_summary
