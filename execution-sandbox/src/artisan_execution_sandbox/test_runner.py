"""Runs the single, config-driven test command for the one fixed demo repo (docs/PRD.md §5 scopes
v1 to one repo — legitimate to hardcode a single command rather than building generic
multi-language test detection)."""

import shlex
import subprocess

from artisan_execution_sandbox.config import DEMO_REPO_TEST_COMMAND


def run_tests(repo_dir: str) -> tuple[bool, str]:
    """Returns (tests_passed, combined_output)."""
    result = subprocess.run(
        shlex.split(DEMO_REPO_TEST_COMMAND),
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output
