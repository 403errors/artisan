"""Tests for the install/build/test step runner (exec-env generalization: the commands now come
from repo_config.resolve and arrive as parameters, so no command monkeypatching is needed — the
subprocesses here are deterministic local ones, not any real repo's toolchain)."""

from artisan_execution_sandbox import check_runner


def test_run_tests_reports_pass_on_zero_exit(tmp_path) -> None:
    passed, _output = check_runner.run_tests('python3 -c "exit(0)"', str(tmp_path))
    assert passed is True


def test_run_tests_reports_failure_on_nonzero_exit_and_captures_output(tmp_path) -> None:
    passed, output = check_runner.run_tests('python3 -c "print(\'boom\'); exit(1)"', str(tmp_path))
    assert passed is False
    assert "boom" in output


def test_unparseable_command_is_a_failed_step_not_a_crash(tmp_path) -> None:
    passed, output = check_runner.run_build('unmatched "quote', str(tmp_path))
    assert passed is False
    assert "could not parse" in output


def test_missing_toolchain_binary_is_a_failed_step_not_a_crash(tmp_path) -> None:
    """The resolved ecosystem's toolchain being absent from the image (e.g. `go` before the
    polyglot image lands) must degrade to a failed step — main.py turns it into a failed
    ExecutionResult — never a raised exception past main.py's always-return-data contract."""
    passed, output = check_runner.run_install(
        "definitely-not-a-real-toolchain-binary --version", str(tmp_path)
    )
    assert passed is False
    assert "could not run" in output
