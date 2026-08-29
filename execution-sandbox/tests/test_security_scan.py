"""Tests for security_scan.py (Workstream 6): scan_secrets/scan_static/scan_new_dependencies, all
with subprocess.run mocked — no real gitleaks/semgrep/git binary is invoked."""

import json
import subprocess

import pytest

from artisan_execution_sandbox import security_scan


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_scan_secrets_clean_output_reports_clean(monkeypatch) -> None:
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, stdout="[]")
    )
    clean, findings = security_scan.scan_secrets("/repo")
    assert clean is True
    assert findings == ""


def test_scan_secrets_finding_reports_not_clean_with_summary(monkeypatch) -> None:
    findings_json = json.dumps(
        [{"RuleID": "aws-access-key", "File": "config.py", "StartLine": 12}]
    )
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, stdout=findings_json)
    )
    clean, findings = security_scan.scan_secrets("/repo")
    assert clean is False
    assert "aws-access-key" in findings
    assert "config.py" in findings
    assert "12" in findings


def test_scan_secrets_missing_binary_fails_open(monkeypatch) -> None:
    def fake_run(*a, **k):
        raise FileNotFoundError("gitleaks not found")

    monkeypatch.setattr(security_scan.subprocess, "run", fake_run)
    clean, findings = security_scan.scan_secrets("/repo")
    assert clean is True
    assert "unavailable" in findings


def test_scan_secrets_tool_malfunction_nonzero_exit_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(2, stdout="not json")
    )
    clean, findings = security_scan.scan_secrets("/repo")
    assert clean is True
    assert "unavailable" in findings


def test_scan_static_clean_output_reports_ok_with_no_notes(monkeypatch) -> None:
    payload = json.dumps({"results": []})
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, stdout=payload)
    )
    ok, findings = security_scan.scan_static("/repo")
    assert ok is True
    assert findings == ""


def test_scan_static_error_severity_blocks(monkeypatch) -> None:
    payload = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.lang.security.sql-injection",
                    "path": "db.py",
                    "start": {"line": 20},
                    "extra": {"severity": "ERROR"},
                }
            ]
        }
    )
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, stdout=payload)
    )
    ok, findings = security_scan.scan_static("/repo")
    assert ok is False
    assert "sql-injection" in findings
    assert "db.py" in findings


def test_scan_static_warning_severity_is_non_blocking(monkeypatch) -> None:
    payload = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.lang.best-practice.some-warning",
                    "path": "utils.py",
                    "start": {"line": 5},
                    "extra": {"severity": "WARNING"},
                }
            ]
        }
    )
    monkeypatch.setattr(
        security_scan.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0, stdout=payload)
    )
    ok, findings = security_scan.scan_static("/repo")
    assert ok is True
    assert "some-warning" in findings


def test_scan_static_missing_binary_fails_open(monkeypatch) -> None:
    def fake_run(*a, **k):
        raise FileNotFoundError("semgrep not found")

    monkeypatch.setattr(security_scan.subprocess, "run", fake_run)
    ok, findings = security_scan.scan_static("/repo")
    assert ok is True
    assert "unavailable" in findings


def test_scan_new_dependencies_happy_path(monkeypatch, tmp_path) -> None:
    repo_dir = tmp_path
    (repo_dir / "requirements.txt").write_text("requests==2.31.0\nlodash==1.0.0\n")

    def fake_run(args, cwd=None, capture_output=None, text=None):
        if args[:2] == ["git", "diff"]:
            return _FakeCompletedProcess(0, stdout="requirements.txt\n")
        if args[:2] == ["git", "show"]:
            return _FakeCompletedProcess(0, stdout="requests==2.31.0\n")
        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr(security_scan.subprocess, "run", fake_run)
    result = security_scan.scan_new_dependencies(str(repo_dir))
    assert any("lodash==1.0.0" in r and "requirements.txt" in r for r in result)


def test_scan_new_dependencies_never_raises_on_broken_git_history(monkeypatch, tmp_path) -> None:
    """A fresh clone/first-commit branch (no HEAD~1 yet) or any other git failure must never crash
    scan_new_dependencies — it's purely informational. Whatever it returns, it must not raise."""
    repo_dir = tmp_path
    (repo_dir / "requirements.txt").write_text("requests==2.31.0\n")

    def fake_run(*a, **k):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(security_scan.subprocess, "run", fake_run)
    result = security_scan.scan_new_dependencies(str(repo_dir))
    assert isinstance(result, list)


def test_scan_new_dependencies_swallows_unexpected_exceptions(monkeypatch, tmp_path) -> None:
    """A completely unexpected failure anywhere inside the scan (e.g. os.path blowing up) must
    still surface as an empty list, never an exception — this is the module-level guarantee, as
    opposed to the git-specific fallbacks already exercised above."""
    monkeypatch.setattr(
        security_scan, "_scan_new_dependencies", lambda repo_dir: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = security_scan.scan_new_dependencies(str(tmp_path))
    assert result == []


def test_scan_new_dependencies_no_manifests_returns_empty(tmp_path) -> None:
    result = security_scan.scan_new_dependencies(str(tmp_path))
    assert result == []
