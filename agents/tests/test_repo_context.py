"""Unit tests for repo_context.py's get_repo_context (WS3): cache-miss/cache-hit/stale-head-sha
refetch logic, plus manifest detection. Mocks the GitHub client and Firestore client the same way
test_gate2.py does (monkeypatch on the module-level `github_client`/`firestore_client` imports) —
never touches a real GitHub App installation or Firestore."""

from datetime import datetime, timedelta, timezone

import pytest

from artisan_agents import repo_context as repo_context_module
from artisan_shared.models import RepoContext

REPO = "acme/demo"


def _context(*, head_sha="sha1", fetched_at=None, file_tree=None, manifests=None) -> RepoContext:
    return RepoContext(
        repo=REPO,
        head_sha=head_sha,
        file_tree=file_tree or ["a.py"],
        manifests=manifests or {},
        languages={".py": 1},
        fetched_at=fetched_at or datetime.now(timezone.utc),
    )


@pytest.fixture
def fake_clients(monkeypatch):
    state = {
        "cached": None,
        "head_sha": "sha1",
        "tree": ["a.py", "b.py"],
        "file_contents": {},
        "tree_calls": 0,
        "set_calls": [],
    }

    async def fake_get_cached_repo_context(repo: str):
        return state["cached"]

    async def fake_set_repo_context(repo: str, context: RepoContext) -> None:
        state["set_calls"].append(context)
        state["cached"] = context

    async def fake_get_default_branch_head_sha(repo: str) -> str:
        return state["head_sha"]

    async def fake_get_repo_tree(repo: str, sha: str) -> list[str]:
        state["tree_calls"] += 1
        return state["tree"]

    async def fake_get_file_content(repo: str, path: str, sha: str):
        return state["file_contents"].get(path)

    monkeypatch.setattr(
        repo_context_module.firestore_client, "get_cached_repo_context", fake_get_cached_repo_context
    )
    monkeypatch.setattr(repo_context_module.firestore_client, "set_repo_context", fake_set_repo_context)
    monkeypatch.setattr(
        repo_context_module.github_client,
        "get_default_branch_head_sha",
        fake_get_default_branch_head_sha,
    )
    monkeypatch.setattr(repo_context_module.github_client, "get_repo_tree", fake_get_repo_tree)
    monkeypatch.setattr(repo_context_module.github_client, "get_file_content", fake_get_file_content)

    return state


@pytest.mark.asyncio
async def test_cache_miss_triggers_fetch_and_cache_write(fake_clients) -> None:
    fake_clients["cached"] = None

    context = await repo_context_module.get_repo_context(REPO)

    assert context.head_sha == "sha1"
    assert context.file_tree == ["a.py", "b.py"]
    assert fake_clients["tree_calls"] == 1
    assert len(fake_clients["set_calls"]) == 1
    assert fake_clients["set_calls"][0] == context


@pytest.mark.asyncio
async def test_cache_hit_with_matching_sha_and_fresh_fetched_at_skips_refetch(fake_clients) -> None:
    cached = _context(head_sha="sha1", fetched_at=datetime.now(timezone.utc))
    fake_clients["cached"] = cached

    context = await repo_context_module.get_repo_context(REPO)

    assert context == cached
    assert fake_clients["tree_calls"] == 0
    assert fake_clients["set_calls"] == []


@pytest.mark.asyncio
async def test_stale_head_sha_mismatch_triggers_refetch(fake_clients) -> None:
    cached = _context(head_sha="old-sha", fetched_at=datetime.now(timezone.utc))
    fake_clients["cached"] = cached
    fake_clients["head_sha"] = "new-sha"

    context = await repo_context_module.get_repo_context(REPO)

    assert context.head_sha == "new-sha"
    assert fake_clients["tree_calls"] == 1
    assert len(fake_clients["set_calls"]) == 1


@pytest.mark.asyncio
async def test_stale_fetched_at_beyond_ttl_triggers_refetch_even_with_matching_sha(
    fake_clients,
) -> None:
    old_fetched_at = datetime.now(timezone.utc) - timedelta(
        seconds=repo_context_module.REPO_CONTEXT_TTL_SECONDS + 1
    )
    cached = _context(head_sha="sha1", fetched_at=old_fetched_at)
    fake_clients["cached"] = cached

    context = await repo_context_module.get_repo_context(REPO)

    assert fake_clients["tree_calls"] == 1
    assert context.fetched_at > old_fetched_at


@pytest.mark.asyncio
async def test_manifest_detection_picks_up_package_json_in_the_tree(fake_clients) -> None:
    fake_clients["cached"] = None
    fake_clients["tree"] = ["src/index.ts", "package.json", "docs/README.md"]
    fake_clients["file_contents"] = {"package.json": '{"name": "demo"}'}

    context = await repo_context_module.get_repo_context(REPO)

    assert context.manifests == {"package.json": '{"name": "demo"}'}
    assert context.languages == {".ts": 1, ".json": 1, ".md": 1}


@pytest.mark.asyncio
async def test_manifest_not_found_is_skipped_not_raised(fake_clients) -> None:
    fake_clients["cached"] = None
    fake_clients["tree"] = ["package.json"]
    fake_clients["file_contents"] = {}  # get_file_content returns None (404)

    context = await repo_context_module.get_repo_context(REPO)

    assert context.manifests == {}
