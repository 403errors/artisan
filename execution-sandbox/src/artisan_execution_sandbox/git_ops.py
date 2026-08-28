"""Thin subprocess wrappers around the `git` CLI. No Python git library is used — nothing in the
monorepo justifies the dependency, `git` is present in any reasonable base image, and subprocess
calls are trivially inspectable/loggable (feeds `ExecutionResult.logs_uri`)."""

import subprocess

_COMMIT_AUTHOR_ARGS = ["-c", "user.email=artisan-bot@users.noreply.github.com", "-c", "user.name=artisan-bot"]


class GitCommandError(Exception):
    """Raised when a `git` subprocess exits non-zero. The message is safe to log — any redacted
    value (e.g. an installation token embedded in a push URL) is scrubbed before this is raised."""


def _run(args: list[str], cwd: str, redact: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    stdout, stderr = result.stdout, result.stderr
    if redact:
        stdout = stdout.replace(redact, "***")
        stderr = stderr.replace(redact, "***")
    if result.returncode != 0:
        safe_args = [a.replace(redact, "***") if redact else a for a in args]
        raise GitCommandError(f"git {' '.join(safe_args)} failed: {stderr}")
    return stdout


def clone(remote_url: str, dest: str, *, redact: str | None = None) -> None:
    _run(["clone", remote_url, dest], cwd=".", redact=redact)


def create_branch(repo_dir: str, branch_name: str) -> None:
    _run(["checkout", "-b", branch_name], cwd=repo_dir)


def stage_all_and_diff_stat(repo_dir: str) -> str:
    """Stages every change (including new untracked files, which a plain `git diff --stat` would
    miss) and returns the staged diff summary, before any commit is made."""
    _run(["add", "-A"], cwd=repo_dir)
    return _run(["diff", "--stat", "--cached"], cwd=repo_dir)


def has_staged_changes(repo_dir: str) -> bool:
    return bool(_run(["status", "--porcelain"], cwd=repo_dir).strip())


def commit_all(repo_dir: str, message: str) -> None:
    """Commits whatever is currently staged. Callers should check `has_staged_changes` first —
    committing with nothing staged is a caller error, not something this function should decide
    is a no-op silently."""
    _run([*_COMMIT_AUTHOR_ARGS, "commit", "-m", message], cwd=repo_dir)


def push(repo_dir: str, branch_name: str, *, token: str, repo: str) -> None:
    """Pushes `branch_name` using an installation-token-in-URL remote. The token is scrubbed from
    any output/error before it can reach a log."""
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    _run(["push", remote_url, branch_name], cwd=repo_dir, redact=token)
