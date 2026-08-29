"""Repo Context fetch + cache (WS3) — a cheap, cacheable snapshot of a repo's shape (file tree,
known manifests, a language histogram) that later workstreams (routing/domain-expert/planning
generalization) ground their reasoning in, instead of the issue text alone.

Cached in Firestore's top-level `repo_context/{repo_sanitized}` collection (see
`gcp/firestore_client.py`), keyed by `head_sha` freshness rather than a pure TTL: a cache hit still
refetches nothing extra beyond a single cheap `get_default_branch_head_sha` call, and only pays for
a full tree walk + manifest fetches when the default branch has actually moved (or the cache is
missing/stale beyond `REPO_CONTEXT_TTL_SECONDS`, which bounds how long a context can go
unrefreshed even if `head_sha` momentarily stops changing, e.g. a quiet repo)."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from artisan_agents.gcp import firestore_client
from artisan_agents.github import client as github_client
from artisan_shared.models import RepoContext

KNOWN_MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "composer.json",
)
REPO_CONTEXT_TTL_SECONDS = 6 * 3600


def _is_stale(cached: RepoContext, fresh_head_sha: str) -> bool:
    if cached.head_sha != fresh_head_sha:
        return True
    fetched_at = cached.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age >= REPO_CONTEXT_TTL_SECONDS


async def _fetch_manifests(repo: str, file_tree: list[str], sha: str) -> dict[str, str]:
    manifests: dict[str, str] = {}
    for path in file_tree:
        basename = Path(path).name
        if basename in KNOWN_MANIFESTS:
            content = await github_client.get_file_content(repo, path, sha)
            if content is not None:
                manifests[path] = content
    return manifests


def _languages_histogram(file_tree: list[str]) -> dict[str, int]:
    return dict(Counter(suffix for p in file_tree if (suffix := Path(p).suffix)))


async def get_repo_context(repo: str) -> RepoContext:
    cached = await firestore_client.get_cached_repo_context(repo)
    head_sha = await github_client.get_default_branch_head_sha(repo)

    if cached is not None and not _is_stale(cached, head_sha):
        return cached

    file_tree = await github_client.get_repo_tree(repo, head_sha)
    manifests = await _fetch_manifests(repo, file_tree, head_sha)
    languages = _languages_histogram(file_tree)

    context = RepoContext(
        repo=repo,
        head_sha=head_sha,
        file_tree=file_tree,
        manifests=manifests,
        languages=languages,
        fetched_at=datetime.now(timezone.utc),
    )
    await firestore_client.set_repo_context(repo, context)
    return context
