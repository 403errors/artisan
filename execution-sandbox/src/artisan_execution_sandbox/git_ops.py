"""Thin subprocess wrappers around the `git` CLI. No Python git library is used — nothing in the
monorepo justifies the dependency, `git` is present in any reasonable base image, and subprocess
calls are trivially inspectable/loggable (feeds `ExecutionResult.logs_uri`)."""

import re
import subprocess

_STATUS_TAGS = {"A": "new file", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied"}

# `git diff --numstat`'s rename notation abbreviates a shared path prefix/suffix, e.g.
# "src/{old.py => new.py}" — this pulls out the post-rename path so it matches --name-status's key.
_RENAME_BRACE_RE = re.compile(r"\{(?:.*) => (.*)\}")


def _resolve_new_path(raw_path: str) -> str:
    match = _RENAME_BRACE_RE.search(raw_path)
    if match:
        return raw_path[: match.start()] + match.group(1) + raw_path[match.end() :]
    if " => " in raw_path:
        return raw_path.split(" => ", 1)[1]
    return raw_path

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
    miss) and returns a per-file summary — one `path (tag) +added -deleted` line per file — before
    any commit is made. Built from `--numstat` (line counts) and `--name-status` (new/modified/
    deleted/renamed), zipped by path, rather than raw `git diff --stat` text: that text's own
    `+`/`-`/`|` bar-chart characters get misinterpreted as Jira wiki markup (underline/strikethrough)
    when a comment embeds it verbatim."""
    _run(["add", "-A"], cwd=repo_dir)
    numstat = _run(["diff", "--numstat", "--cached"], cwd=repo_dir)
    name_status = _run(["diff", "--name-status", "--cached"], cwd=repo_dir)

    statuses: dict[str, str] = {}
    for line in name_status.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        statuses[fields[-1]] = fields[0]

    lines = []
    for line in numstat.splitlines():
        if not line:
            continue
        added, deleted, raw_path = line.split("\t", 2)
        path = _resolve_new_path(raw_path)
        tag = _STATUS_TAGS.get(statuses.get(path, "M")[0], "modified")
        if added == "-" and deleted == "-":
            lines.append(f"{path} ({tag}, binary)")
        else:
            lines.append(f"{path} ({tag}) +{added} -{deleted}")
    return "\n".join(lines)


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
    checked out (Gate 3, MILESTONE.md Phase 4.1/4.3). A real conflict is expected OUTPUT here, not a
    subprocess failure — unlike every other wrapper in this module, a nonzero exit does not
    automatically raise. It's distinguished from a genuine git-level error (e.g. an unknown ref) by
    checking whether `list_conflicted_files` actually reports conflicted files; only a genuine
    error raises GitCommandError. Returns (merged_clean, combined_output).

    Passes `_COMMIT_AUTHOR_ARGS` even though `--no-commit` means no commit is ever created here:
    found live that the execution-sandbox container (no global git identity configured, unlike a
    dev machine) raised "Committer identity unknown" on this exact merge for a real two-file
    conflict, despite `--no-commit` — not reproduced locally with the same repo content on a
    different git build, so this looks like a container/git-version-specific identity check rather
    than universal `--no-ff` behavior. Passing identity here (matching `commit_all`'s existing
    pattern) is safe regardless of the precise cause and directly resolves the observed failure —
    see docs/CONTEXT.md."""
    result = subprocess.run(
        ["git", *_COMMIT_AUTHOR_ARGS, "merge", "--no-commit", "--no-ff", f"origin/{branch_name}"],
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
