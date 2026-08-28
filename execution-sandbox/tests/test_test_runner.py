"""Tests for the configured test-command runner. Monkeypatches the configured command to a
deterministic subprocess rather than depending on any real repo's actual test suite."""

from artisan_execution_sandbox import config, test_runner


def test_run_tests_reports_pass_on_zero_exit(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "DEMO_REPO_TEST_COMMAND", 'python3 -c "exit(0)"')
    monkeypatch.setattr(test_runner, "DEMO_REPO_TEST_COMMAND", 'python3 -c "exit(0)"')
    passed, _output = test_runner.run_tests(str(tmp_path))
    assert passed is True


def test_run_tests_reports_failure_on_nonzero_exit_and_captures_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        test_runner, "DEMO_REPO_TEST_COMMAND", 'python3 -c "print(\'boom\'); exit(1)"'
    )
    passed, output = test_runner.run_tests(str(tmp_path))
    assert passed is False
    assert "boom" in output
