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


@pytest.fixture(autouse=True)
def stub_security_scan_clean(monkeypatch):
    """WS6's scan gate runs between commit_all and push in both run_attempt and
    run_conflict_resolution. Default every test to a clean/no-op scan so pre-WS6 tests keep their
    original behavior; individual tests below override these to exercise the gate itself."""
    monkeypatch.setattr(main_module.security_scan, "scan_secrets", lambda repo_dir: (True, ""))
    monkeypatch.setattr(main_module.security_scan, "scan_static", lambda repo_dir: (True, ""))
    monkeypatch.setattr(main_module.security_scan, "scan_new_dependencies", lambda repo_dir: [])


@pytest.fixture(autouse=True)
def stub_staged_diff(monkeypatch):
    """#12's bounded real diff + changed-file contents ride along on the success-path
    ExecutionResult — stub them so tests don't shell out to git in a nonexistent workdir."""
    monkeypatch.setattr(
        main_module.git_ops, "staged_diff", lambda repo_dir: "diff --git a/a.py b/a.py\n+x"
    )
    monkeypatch.setattr(
        main_module.git_ops, "staged_file_contents", lambda repo_dir: {"a.py": "x"}
    )


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


@pytest.mark.asyncio
async def test_run_attempt_constructs_a_sink_and_passes_it_to_the_coding_agent_when_issue_number_given(
    monkeypatch,
) -> None:
    """firestore_write.new_event_sink constructs a real Firestore client — monkeypatched here so
    this test never touches the real database, mirroring agents/tests/conftest.py's approach."""
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))

    sentinel_sink = object()
    new_event_sink_calls = []

    def fake_new_event_sink(ticket_id, *, gate, redact_token):
        new_event_sink_calls.append((ticket_id, gate, redact_token))
        return sentinel_sink

    monkeypatch.setattr(main_module.firestore_write, "new_event_sink", fake_new_event_sink)

    received_sink = []

    async def fake_run_coding_agent(**kwargs):
        received_sink.append(kwargs.get("sink"))
        return "did the thing"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)

    await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None, issue_number=7
    )

    assert new_event_sink_calls == [("acme_demo__7", "2", "fake-token")]
    assert received_sink == [sentinel_sink]


@pytest.mark.asyncio
async def test_run_attempt_passes_no_sink_when_issue_number_is_omitted(monkeypatch) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))

    def fail_if_called(*a, **k):
        raise AssertionError("must not construct a real event sink when issue_number is omitted")

    monkeypatch.setattr(main_module.firestore_write, "new_event_sink", fail_if_called)

    received_sink = []

    async def fake_run_coding_agent(**kwargs):
        received_sink.append(kwargs.get("sink"))
        return "did the thing"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)

    await main_module.run_attempt(repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None)

    assert received_sink == [None]


def _stub_happy_path_up_to_push(monkeypatch, *, push_calls: list) -> None:
    monkeypatch.setattr(main_module.git_ops, "clone", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "create_branch", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: push_calls.append((a, k)))
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))

    async def fake_run_coding_agent(**kwargs):
        return "did the thing"

    monkeypatch.setattr(main_module, "run_coding_agent", fake_run_coding_agent)


@pytest.mark.asyncio
async def test_run_attempt_blocks_push_on_secret_detected(monkeypatch) -> None:
    push_calls: list = []
    _stub_happy_path_up_to_push(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_secrets", lambda repo_dir: (False, "aws-key in a.py:1")
    )

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert push_calls == []
    assert result.tests_passed is False
    assert "security scan blocked: secret detected" in result.logs_uri
    assert "aws-key in a.py:1" in result.logs_uri


@pytest.mark.asyncio
async def test_run_attempt_blocks_push_on_static_error_finding(monkeypatch) -> None:
    push_calls: list = []
    _stub_happy_path_up_to_push(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_static", lambda repo_dir: (False, "sql-injection in b.py:2")
    )

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert push_calls == []
    assert result.tests_passed is False
    assert "security scan blocked: static analysis finding" in result.logs_uri
    assert "sql-injection in b.py:2" in result.logs_uri


@pytest.mark.asyncio
async def test_run_attempt_appends_non_blocking_findings_and_still_pushes(monkeypatch) -> None:
    push_calls: list = []
    _stub_happy_path_up_to_push(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_static", lambda repo_dir: (True, "minor-warning in c.py:3")
    )
    monkeypatch.setattr(
        main_module.security_scan,
        "scan_new_dependencies",
        lambda repo_dir: ["added dependency: lodash (package.json)"],
    )

    result = await main_module.run_attempt(
        repo="acme/demo", branch="artisan/x-1", plan=_PLAN, prior_feedback=None
    )

    assert len(push_calls) == 1
    assert result.tests_passed is True
    assert "New dependencies detected" in result.diff_summary
    assert "lodash" in result.diff_summary
    assert "Static analysis notes (non-blocking)" in result.diff_summary
    assert "minor-warning in c.py:3" in result.diff_summary


def _stub_conflict_resolution_happy_path(monkeypatch, *, push_calls: list) -> None:
    _stub_conflicted_merge(monkeypatch)
    monkeypatch.setattr(main_module.git_ops, "stage_all_and_diff_stat", lambda repo_dir: "1 file changed")
    monkeypatch.setattr(main_module.git_ops, "has_staged_changes", lambda repo_dir: True)
    monkeypatch.setattr(main_module.git_ops, "commit_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module.test_runner, "run_tests", lambda repo_dir: (True, "ok"))
    monkeypatch.setattr(main_module.git_ops, "push", lambda *a, **k: push_calls.append((a, k)))

    async def fake_run_conflict_resolution_agent(**kwargs):
        return "resolved shared.py"

    monkeypatch.setattr(main_module, "run_conflict_resolution_agent", fake_run_conflict_resolution_agent)


@pytest.mark.asyncio
async def test_run_conflict_resolution_blocks_push_on_secret_detected(monkeypatch) -> None:
    push_calls: list = []
    _stub_conflict_resolution_happy_path(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_secrets", lambda repo_dir: (False, "aws-key in a.py:1")
    )

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert push_calls == []
    assert result.tests_passed is False
    assert "security scan blocked: secret detected" in result.logs_uri


@pytest.mark.asyncio
async def test_run_conflict_resolution_blocks_push_on_static_error_finding(monkeypatch) -> None:
    push_calls: list = []
    _stub_conflict_resolution_happy_path(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_static", lambda repo_dir: (False, "sql-injection in b.py:2")
    )

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert push_calls == []
    assert result.tests_passed is False
    assert "security scan blocked: static analysis finding" in result.logs_uri


@pytest.mark.asyncio
async def test_run_conflict_resolution_appends_non_blocking_findings_and_still_pushes(
    monkeypatch,
) -> None:
    push_calls: list = []
    _stub_conflict_resolution_happy_path(monkeypatch, push_calls=push_calls)
    monkeypatch.setattr(
        main_module.security_scan, "scan_static", lambda repo_dir: (True, "minor-warning in c.py:3")
    )
    monkeypatch.setattr(
        main_module.security_scan,
        "scan_new_dependencies",
        lambda repo_dir: ["added dependency: lodash (package.json)"],
    )

    result = await main_module.run_conflict_resolution(
        repo="acme/demo", base_branch="main", head_branch="feature"
    )

    assert len(push_calls) == 1
    assert result.tests_passed is True
    assert "New dependencies detected" in result.diff_summary
    assert "Static analysis notes (non-blocking)" in result.diff_summary
