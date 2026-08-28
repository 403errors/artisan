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


def checkout(repo_dir: str, branch_name: str) -> None:
    """Checks out an EXISTING branch (unlike create_branch, never `-b`). Relies on git's DWIM
    behavior to create a local tracking branch from `origin/<branch_name>` automatically if it
    isn't local yet — safe here since these clones only ever have one remote."""
    _run(["checkout", branch_name], cwd=repo_dir)


def fetch(repo_dir: str, branch_name: str, *, redact: str | None = None) -> None:
    _run(["fetch", "origin", branch_name], cwd=repo_dir, redact=redact)


def merge(repo_dir: str, branch_name: str) -> tuple[bool, str]:
    """Attempts `git merge --no-commit --no-ff origin/<branch_name>` into whatever's currently
    checked out (Gate 3, SPRINT.md Phase 4.1/4.3). A real conflict is expected OUTPUT here, not a
    subprocess failure — unlike every other wrapper in this module, a nonzero exit does not
    automatically raise. It's distinguished from a genuine git-level error (e.g. an unknown ref) by
    checking whether `list_conflicted_files` actually reports conflicted files; only a genuine
    error raises GitCommandError. Returns (merged_clean, combined_output)."""
    result = subprocess.run(
        ["git", "merge", "--no-commit", "--no-ff", f"origin/{branch_name}"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode == 0:
        return True, output
    if list_conflicted_files(repo_dir):
        return False, output
    raise GitCommandError(f"git merge origin/{branch_name} failed: {output}")


def abort_merge(repo_dir: str) -> None:
    _run(["merge", "--abort"], cwd=repo_dir)


def list_conflicted_files(repo_dir: str) -> list[str]:
    output = _run(["diff", "--name-only", "--diff-filter=U"], cwd=repo_dir)
    return [line for line in output.splitlines() if line]


def read_conflict_markers(repo_dir: str, conflicted_files: list[str]) -> str:
    """Concatenates each conflicted file's full contents (including the literal <<<<<<</=======/
    >>>>>>> markers) — the Conflict Agent's and the resolution agent's shared raw material."""
    sections = []
    for path in conflicted_files:
        try:
            with open(f"{repo_dir}/{path}", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            content = f"(could not read file: {exc})"
        sections.append(f"--- {path} ---\n{content}")
    return "\n\n".join(sections)


def log_for_paths(repo_dir: str, branch_name: str, paths: list[str], *, limit: int = 5) -> str:
    """`git log -n<limit> --oneline origin/<branch_name> -- <paths>` — side B's recent history
    scoped to the conflicted files, gathered here since this job already has the fetch; not worth
    a second GitHub API round-trip from the orchestrator."""
    if not paths:
        return ""
    return _run(["log", f"-n{limit}", "--oneline", f"origin/{branch_name}", "--", *paths], cwd=repo_dir)
