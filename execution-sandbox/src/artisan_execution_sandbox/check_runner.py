"""Runs one attempt's resolved install/build/test commands (Gate 2 exec-env generalization) —
replaces v1's test_runner.py, which shelled out to the single hardcoded DEMO_REPO_TEST_COMMAND
(legitimate when v1 was scoped to one demo repo; unworkable for arbitrary repos). The commands
now come from repo_config.resolve — this module is purely the executor.

Each step returns (ok, combined_output) independently so main.py can short-circuit (never run
tests when the build already failed) while still returning data on every path — the same
always-return-data contract as main.py itself: an unparseable command, a missing toolchain
binary, or a timeout is a failed step, never a raised exception."""

import shlex
import subprocess

# Per-step bounds, deliberately much larger than the coding agent's 120s shell cap: a cold
# `npm ci`/`uv pip install` or a full repo test suite legitimately takes minutes on real repos.
INSTALL_TIMEOUT_S = 900
BUILD_TIMEOUT_S = 900
TEST_TIMEOUT_S = 900


def _run(command: str, repo_dir: str, timeout_s: int) -> tuple[bool, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"could not parse command {command!r}: {exc}"
    try:
        result = subprocess.run(
            argv,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"command timed out after {timeout_s}s: {command}"
    except OSError as exc:
        # e.g. the resolved ecosystem's toolchain is missing from the image — data, not a crash.
        return False, f"could not run {command!r}: {exc}"
    return result.returncode == 0, result.stdout + result.stderr


def run_install(command: str, repo_dir: str) -> tuple[bool, str]:
    """Returns (install_ok, combined_output)."""
    return _run(command, repo_dir, INSTALL_TIMEOUT_S)


def run_build(command: str, repo_dir: str) -> tuple[bool, str]:
    """Returns (build_ok, combined_output)."""
    return _run(command, repo_dir, BUILD_TIMEOUT_S)


def run_tests(command: str, repo_dir: str) -> tuple[bool, str]:
    """Returns (tests_passed, combined_output)."""
    return _run(command, repo_dir, TEST_TIMEOUT_S)
