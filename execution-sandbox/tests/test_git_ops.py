"""Tests for the git-subprocess wrappers, run against real local scratch repos (no GCP/GitHub
dependency needed — fully real, not faked). The actual push-to-real-GitHub round trip is a
live-only verification (Phase 3.4's DoD requires a real branch/commit by definition, see
docs/CONTEXT.md) and isn't attempted here."""

import subprocess

import pytest

from artisan_execution_sandbox.git_ops import (
    GitCommandError,
    _run,
    clone,
    commit_all,
    create_branch,
    has_staged_changes,
    stage_all_and_diff_stat,
)


def _init_origin(path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=x@x.com", "-c", "user.name=x", "commit", "-q", "-m", "init"],
        check=True,
    )


def test_clone_and_create_branch(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin(origin)

    clone(str(origin), str(workdir))
    create_branch(str(workdir), "artisan/ART-1-attempt-1")

    current_branch = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert current_branch == "artisan/ART-1-attempt-1"


def test_stage_all_and_diff_stat_then_commit(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin(origin)
    clone(str(origin), str(workdir))

    (workdir / "new_file.py").write_text("print('hi')\n")

    diff_summary = stage_all_and_diff_stat(str(workdir))
    assert "new_file.py" in diff_summary
    assert has_staged_changes(str(workdir)) is True

    commit_all(str(workdir), "Artisan: add new_file.py")
    assert has_staged_changes(str(workdir)) is False

    log = subprocess.run(
        ["git", "-C", str(workdir), "log", "-1", "--pretty=%s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert log == "Artisan: add new_file.py"


def test_run_redacts_sensitive_value_from_raised_error(tmp_path) -> None:
    with pytest.raises(GitCommandError) as exc_info:
        _run(["not-a-real-git-command", "sekret-value"], cwd=str(tmp_path), redact="sekret-value")
    assert "sekret-value" not in str(exc_info.value)
