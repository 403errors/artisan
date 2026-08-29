"""Tests for the git-subprocess wrappers, run against real local scratch repos (no GCP/GitHub
dependency needed — fully real, not faked). The actual push-to-real-GitHub round trip is a
live-only verification (Phase 3.4's DoD requires a real branch/commit by definition, see
docs/CONTEXT.md) and isn't attempted here."""

import subprocess

import pytest

from artisan_execution_sandbox.git_ops import (
    GitCommandError,
    _run,
    checkout,
    clone,
    commit_all,
    create_branch,
    fetch,
    has_staged_changes,
    list_conflicted_files,
    log_for_paths,
    merge,
    read_conflict_markers,
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


def _commit(path, message: str) -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=x@x.com", "-c", "user.name=x", "commit", "-q", "-m", message],
        check=True,
    )


def _checkout_new(path, branch: str) -> None:
    subprocess.run(["git", "-C", str(path), "checkout", "-q", "-b", branch], check=True)


def _checkout(path, branch: str) -> None:
    subprocess.run(["git", "-C", str(path), "checkout", "-q", branch], check=True)


def _init_origin_with_conflicting_branches(path) -> None:
    """Builds an origin with `main` and `feature` both editing `shared.py`'s same line
    differently from their common ancestor — a real, git-detectable conflict."""
    _init_origin(path)
    (path / "shared.py").write_text("value = 1\n")
    _commit(path, "add shared.py")

    _checkout_new(path, "feature")
    (path / "shared.py").write_text("value = 2\n")
    _commit(path, "feature: bump to 2")

    _checkout(path, "main")
    (path / "shared.py").write_text("value = 3\n")
    _commit(path, "main: bump to 3")


def _init_origin_with_non_overlapping_branches(path) -> None:
    """Builds an origin with `main` and `feature` touching different files — merges cleanly."""
    _init_origin(path)

    _checkout_new(path, "feature")
    (path / "feature_only.py").write_text("print('feature')\n")
    _commit(path, "feature: add feature_only.py")

    _checkout(path, "main")
    (path / "main_only.py").write_text("print('main')\n")
    _commit(path, "main: add main_only.py")


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
    assert "new_file.py (new file) +1 -0" in diff_summary
    assert has_staged_changes(str(workdir)) is True

    commit_all(str(workdir), "Artisan: add new_file.py")
    assert has_staged_changes(str(workdir)) is False

    log = subprocess.run(
        ["git", "-C", str(workdir), "log", "-1", "--pretty=%s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert log == "Artisan: add new_file.py"


def test_stage_all_and_diff_stat_tags_modified_and_deleted_files(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin(origin)
    (origin / "to_delete.py").write_text("print('bye')\n")
    _commit(origin, "add to_delete.py")
    clone(str(origin), str(workdir))

    (workdir / "README.md").write_text("hello\nworld\n")
    (workdir / "to_delete.py").unlink()

    diff_summary = stage_all_and_diff_stat(str(workdir))
    lines = diff_summary.splitlines()
    assert "README.md (modified) +1 -0" in lines
    assert "to_delete.py (deleted) +0 -1" in lines


def test_run_redacts_sensitive_value_from_raised_error(tmp_path) -> None:
    with pytest.raises(GitCommandError) as exc_info:
        _run(["not-a-real-git-command", "sekret-value"], cwd=str(tmp_path), redact="sekret-value")
    assert "sekret-value" not in str(exc_info.value)


def test_checkout_creates_local_tracking_branch_from_origin(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin_with_non_overlapping_branches(origin)

    clone(str(origin), str(workdir))
    fetch(str(workdir), "feature")
    checkout(str(workdir), "feature")

    current_branch = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert current_branch == "feature"
    assert (workdir / "feature_only.py").exists()


def test_merge_clean_returns_true_and_stays_uncommitted(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin_with_non_overlapping_branches(origin)

    clone(str(origin), str(workdir))
    fetch(str(workdir), "feature")
    checkout(str(workdir), "feature")
    fetch(str(workdir), "main")

    merged_clean, output = merge(str(workdir), "main")

    assert merged_clean is True
    assert (workdir / "main_only.py").exists()
    assert has_staged_changes(str(workdir)) is True
    log_count = subprocess.run(
        ["git", "-C", str(workdir), "log", "--oneline"], capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()
    # --no-commit means the merge itself never adds a new commit.
    assert len(log_count) == 2  # "add ... feature_only.py" + "init"


def test_merge_conflict_returns_false_with_conflicted_files_listed(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin_with_conflicting_branches(origin)

    clone(str(origin), str(workdir))
    fetch(str(workdir), "feature")
    checkout(str(workdir), "feature")
    fetch(str(workdir), "main")

    merged_clean, output = merge(str(workdir), "main")

    assert merged_clean is False
    conflicted = list_conflicted_files(str(workdir))
    assert conflicted == ["shared.py"]
    markers = read_conflict_markers(str(workdir), conflicted)
    assert "<<<<<<<" in markers
    assert "=======" in markers
    assert ">>>>>>>" in markers


def test_merge_raises_git_command_error_for_a_genuine_error_not_a_conflict(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin(origin)
    clone(str(origin), str(workdir))

    with pytest.raises(GitCommandError):
        merge(str(workdir), "does-not-exist")


def test_merge_passes_bot_identity_to_the_subprocess(monkeypatch, tmp_path) -> None:
    """`--no-commit` never creates a commit, but some git environments still preflight-check
    committer identity for a `--no-ff` merge regardless — found live when a container with no
    global git identity configured raised "Committer identity unknown" on every conflict-detection
    attempt, real conflict or not (see docs/CONTEXT.md). `merge()` must pass the same
    `_COMMIT_AUTHOR_ARGS` `commit_all()` already uses, so the subprocess never depends on the
    environment having a global identity configured."""
    import artisan_execution_sandbox.git_ops as git_ops_module

    captured_args: list[str] = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_ops_module.subprocess, "run", fake_run)
    monkeypatch.setattr(git_ops_module, "list_conflicted_files", lambda repo_dir: [])

    merge(str(tmp_path), "main")

    assert "-c" in captured_args
    assert "user.email=artisan-bot@users.noreply.github.com" in captured_args
    assert "user.name=artisan-bot" in captured_args


def test_log_for_paths_scopes_to_given_files(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin_with_conflicting_branches(origin)

    clone(str(origin), str(workdir))
    fetch(str(workdir), "main")

    log = log_for_paths(str(workdir), "main", ["shared.py"])
    assert "main: bump to 3" in log


def test_log_for_paths_returns_empty_string_for_no_paths(tmp_path) -> None:
    origin = tmp_path / "origin"
    workdir = tmp_path / "workdir"
    _init_origin(origin)
    clone(str(origin), str(workdir))

    assert log_for_paths(str(workdir), "main", []) == ""
