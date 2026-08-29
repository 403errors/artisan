"""Thin GitHub REST wrappers used by the intake/clarification flow — all calls go through the
App's installation-token client (github/auth.py), never a PAT."""

import base64
import mimetypes
import re

import httpx
from artisan_shared.models import DuplicateSearchHit
from githubkit.exception import RequestFailed

from artisan_agents.config import DUPLICATE_SEARCH_LIMIT
from artisan_agents.github.auth import get_installation_client

# Repo Context (WS3): cheap file-tree snapshot cap — see artisan_agents.repo_context.
REPO_TREE_MAX_ENTRIES = 500

# WS1 sus-image gate/image ingestion: markdown image syntax `![alt](url)`, restricted to https URLs
# (GitHub-hosted attachment/CDN links are always https).
_MARKDOWN_IMAGE_RE = re.compile(r"!\[.*?\]\((https://[^)\s]+)\)")

# Image ingestion caps (WS1) — bound both cost (per-issue download work) and the number of extra
# inline parts appended to the Intake Agent's prompt.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_TO_DOWNLOAD = 3


def _split_repo(repo: str) -> tuple[str, str]:
    owner, name = repo.split("/", 1)
    return owner, name


async def post_issue_comment(repo: str, issue_number: int, body: str) -> None:
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    await gh.rest.issues.async_create_comment(owner, name, issue_number, body=body)


async def get_issue_thread(repo: str, issue_number: int) -> tuple[str, str, str, list[str]]:
    """Returns (title, body, author_login, comment_bodies) for the Intake Agent's context window
    and for @-mentioning the reporter on Artisan's own comments."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    issue = (await gh.rest.issues.async_get(owner, name, issue_number)).parsed_data
    comments_resp = await gh.rest.issues.async_list_comments(owner, name, issue_number)
    comment_bodies = [c.body or "" for c in comments_resp.parsed_data]
    author_login = issue.user.login if issue.user else "there"
    return issue.title, issue.body or "", author_login, comment_bodies


# Gate 1 duplicate check (SYSTEM_DESIGN.md §3): words too common to be useful as GitHub Search
# API keywords — the title-token pre-filter feeds the Duplicate Detector Agent's semantic scoring.
_SEARCH_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "it", "this", "that", "i", "we", "you", "my", "me", "be", "as", "at", "by", "from",
    "have", "has", "not", "but", "was", "were", "will", "would", "can", "could", "should",
    "please", "help", "bug", "issue", "fix", "error", "problem",
})


def _search_tokens(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in re.split(r"[^a-z0-9]+", (text or "").lower()):
        if len(word) >= 3 and word not in _SEARCH_STOPWORDS and word not in seen:
            seen[word] = None
    return list(seen)


def build_issue_search_query(repo: str, title: str, body: str, *, max_tokens: int = 5) -> str:
    """Builds the GitHub Search API query finding open issues in `repo` similar to this one — the
    keyword pre-filter the Duplicate Detector Agent then scores semantically (Gate 1 duplicate
    check). Title tokens dominate; body tokens backfill a sparse title. Capped at GitHub's 256-char
    query limit."""
    tokens = _search_tokens(title)
    if len(tokens) < 3:
        tokens += _search_tokens(body or "")
    query = f"repo:{repo} is:issue is:open in:title,body {' '.join(tokens[:max_tokens])}".strip()
    return query[:256]


async def search_similar_issues(
    repo: str,
    title: str,
    body: str,
    *,
    exclude_number: int,
    limit: int = DUPLICATE_SEARCH_LIMIT,
) -> list[DuplicateSearchHit]:
    """Returns up to `limit` open issues in `repo` the Search API considers keyword-similar to this
    issue (excluding the issue itself) — the raw candidate set the Duplicate Detector Agent scores
    (Gate 1 duplicate check). A 422 (over-heavy query) or 403 (search rate limit) is treated as no
    candidates rather than failing intake; the Search API has its own 30 req/min rate bucket,
    separate from the REST core limit."""
    _, _ = _split_repo(repo)  # validates the repo string; the Search query carries the parts
    gh = get_installation_client()
    query = build_issue_search_query(repo, title, body)
    if not query:
        return []
    try:
        resp = await gh.rest.search.async_search_issues(
            q=query, per_page=limit, sort="best_match", order="desc"
        )
    except RequestFailed as exc:
        if exc.response.status_code in {422, 403}:
            return []
        raise
    hits: list[DuplicateSearchHit] = []
    for item in resp.parsed_data.items:
        if item.number == exclude_number:
            continue
        hits.append(
            DuplicateSearchHit(
                issue_number=item.number,
                title=item.title or "",
                html_url=item.html_url or "",
                body=(item.body or "")[:500],
            )
        )
    return hits


async def close_issue_as_duplicate(repo: str, issue_number: int, duplicate_of: int) -> None:
    """Closes `issue_number` as a duplicate of `duplicate_of`, after posting an explanatory comment
    (Gate 1 duplicate check — only ever called once the issuer confirmed). Closing with
    `state_reason="not_planned"` is the documented replacement for GitHub's undocumented "mark as
    duplicate" endpoint, which githubkit 0.16.1 has no typed method for; the comment carries the
    cross-reference + link."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    await gh.rest.issues.async_create_comment(
        owner,
        name,
        issue_number,
        body=(
            f"Closing this as a duplicate of #{duplicate_of} — the reporter confirmed it covers "
            f"the same request as https://github.com/{repo}/issues/{duplicate_of}."
        ),
    )
    await gh.rest.issues.async_update(
        owner, name, issue_number, state="closed", state_reason="not_planned"
    )


async def open_pull_request(
    repo: str, *, head: str, base: str, title: str, body: str
) -> tuple[int, str]:
    """Opens a PR via the App's installation token (Gate 2, MILESTONE.md Phase 3.6). Returns
    (pr_number, pr_html_url)."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    response = await gh.rest.pulls.async_create(
        owner, name, title=title, head=head, base=base, body=body
    )
    return response.parsed_data.number, response.parsed_data.html_url


async def close_pull_request(repo: str, pr_number: int, body: str) -> None:
    """Closes an Artisan-owned PR, explaining why in a comment first (the issue-deleted cleanup in
    completion.py). Called only on PRs Artisan itself opened — never on PRs it doesn't own, per
    PRD.md §5's never-operate-on-repo-state-it-doesn't-own rule."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    await gh.rest.issues.async_create_comment(owner, name, pr_number, body=body)
    await gh.rest.pulls.async_update(owner, name, pr_number, state="closed")


async def add_label(repo: str, issue_number: int, label: str) -> None:
    """Adds `label` to an issue/PR, creating it on the repo first if it doesn't exist yet
    (WS6's ready-for-review signal). GitHub's add-labels endpoint 422s when a named label isn't
    already defined on the repo, rather than auto-creating it."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    try:
        await gh.rest.issues.async_add_labels(owner, name, issue_number, labels=[label])
    except RequestFailed as exc:
        if exc.response.status_code == 422:
            await gh.rest.issues.async_create_label(owner, name, name=label, color="0e8a16")
            await gh.rest.issues.async_add_labels(owner, name, issue_number, labels=[label])
        else:
            raise


async def get_pull_request(repo: str, pr_number: int) -> tuple[str, str, str, str, str]:
    """Returns (title, body, base_ref, head_ref, head_sha) — a manual "retry Gate 3" action
    (Sprint 6) needs these to reconstruct start_gate3's inputs, since only `pr_number` is
    persisted on the ticket doc."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    pr = (await gh.rest.pulls.async_get(owner, name, pr_number)).parsed_data
    return pr.title, pr.body or "", pr.base.ref, pr.head.ref, pr.head.sha


async def get_default_branch(repo: str) -> str:
    """Returns the repo's default branch name — the branch Gate 2 opens its PRs against. This
    used to be a hardcoded `main`, which silently targeted the wrong (or non-existent) branch on
    repos whose default branch is `master`/`develop`/etc."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    repo_info = (await gh.rest.repos.async_get(owner, name)).parsed_data
    return repo_info.default_branch


async def get_default_branch_head_sha(repo: str) -> str:
    """Returns the SHA the repo's default branch currently points at — the freshness key
    `repo_context.get_repo_context` compares its cache against (WS3)."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    ref = (
        await gh.rest.git.async_get_ref(owner, name, ref=f"heads/{await get_default_branch(repo)}")
    ).parsed_data
    return ref.object_.sha


async def get_repo_tree(repo: str, sha: str) -> list[str]:
    """Returns file (non-directory) paths from the recursive tree at `sha`, filtered and capped
    for cheap prompt-context use (WS3) — `node_modules/`/`.git/` excluded, first
    `REPO_TREE_MAX_ENTRIES` entries kept."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    tree = (
        await gh.rest.git.async_get_tree(owner, name, sha, recursive="true")
    ).parsed_data.tree
    paths = [
        entry.path
        for entry in tree
        if entry.type == "blob" and "node_modules/" not in entry.path and not entry.path.startswith(".git/")
    ]
    return paths[:REPO_TREE_MAX_ENTRIES]


async def get_file_content(repo: str, path: str, sha: str) -> str | None:
    """Fetches a single file's decoded content at `sha`, or None if it doesn't exist (WS3 manifest
    fetch) — a 404 is an expected outcome here (e.g. a known manifest filename isn't present),
    never an error."""
    owner, name = _split_repo(repo)
    gh = get_installation_client()
    try:
        content = (
            await gh.rest.repos.async_get_content(owner, name, path=path, ref=sha)
        ).parsed_data.content
    except RequestFailed as exc:
        if exc.response.status_code == 404:
            return None
        raise
    return base64.b64decode(content).decode("utf-8", errors="replace")


def _find_markdown_image_urls(title: str, body: str, comments: list[str]) -> list[str]:
    """Collects deduped markdown image URLs (in first-seen order) across `title`/`body`/`comments`
    (WS1) — title is included for completeness/uniformity even though it's unlikely to ever
    contain one."""
    seen: dict[str, None] = {}
    for text in (title, body, *comments):
        for url in _MARKDOWN_IMAGE_RE.findall(text or ""):
            seen[url] = None
    return list(seen)


def count_markdown_images(body: str, comments: list[str]) -> int:
    """Cheap, network-free count of raw markdown image URLs in `body`/`comments` — used by
    dispatch.py's sus-image human-review gate (WS1) before deciding whether to even attempt
    downloading anything."""
    return len(_find_markdown_image_urls("", body, comments))


async def extract_and_download_images(
    title: str, body: str, comments: list[str]
) -> list[tuple[bytes, str]]:
    """Finds markdown image URLs across `title`/`body`/`comments`, downloads each (deduped, plain
    HTTPS GET), and returns at most `MAX_IMAGES_TO_DOWNLOAD` successfully-downloaded
    `(bytes, mime_type)` tuples for the Intake Agent's multimodal prompt (WS1).

    Any single download's failure (network error, non-2xx, oversized) is skipped rather than
    raised — image ingestion is a best-effort enrichment, and must never break the intake flow."""
    urls = _find_markdown_image_urls(title, body, comments)
    downloaded: list[tuple[bytes, str]] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for url in urls:
            if len(downloaded) >= MAX_IMAGES_TO_DOWNLOAD:
                break
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            content_length = response.headers.get("content-length")
            if content_length is not None and int(content_length) > MAX_IMAGE_BYTES:
                continue
            data = response.content
            if len(data) > MAX_IMAGE_BYTES:
                continue
            mime_type = response.headers.get("content-type", "").split(";")[0].strip()
            if not mime_type or not mime_type.startswith("image/"):
                guessed, _ = mimetypes.guess_type(url)
                mime_type = guessed or "application/octet-stream"
            downloaded.append((data, mime_type))
    return downloaded
