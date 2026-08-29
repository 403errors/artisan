"""Unit test for github/client.py's `open_pull_request`/`close_pull_request` (Gate 2 Phase 3.6 +
the issue-deleted cleanup), the Gate 1 duplicate check (`search_similar_issues`/
`close_issue_as_duplicate`), plus WS3's repo-context helpers
(`get_default_branch_head_sha`/`get_repo_tree`/`get_file_content`). Fakes the installation client
so no real GitHub call is made."""

import base64

import httpx
import pytest
from artisan_agents.github import client as github_client_module
from artisan_agents.github.client import (
    add_label,
    build_issue_search_query,
    close_issue_as_duplicate,
    close_pull_request,
    count_markdown_images,
    extract_and_download_images,
    get_default_branch,
    get_default_branch_head_sha,
    get_file_content,
    get_pull_request,
    get_repo_tree,
    open_pull_request,
    search_similar_issues,
)
from githubkit.exception import RequestFailed


class _FakePullRequest:
    def __init__(self, number: int, html_url: str) -> None:
        self.number = number
        self.html_url = html_url


class _FakeRef:
    def __init__(self, ref: str, sha: str = "") -> None:
        self.ref = ref
        self.sha = sha


class _FakeFullPullRequest:
    def __init__(self, *, title: str, body: str | None, base_ref: str, head_ref: str, head_sha: str) -> None:
        self.title = title
        self.body = body
        self.base = _FakeRef(base_ref)
        self.head = _FakeRef(head_ref, head_sha)


class _FakeResponse:
    def __init__(self, parsed_data) -> None:
        self.parsed_data = parsed_data


class _FakePulls:
    def __init__(self) -> None:
        self.calls = []
        self.get_calls = []
        self.update_calls = []
        self._full_pr = None

    async def async_create(self, owner, repo, *, title, head, base, body):
        self.calls.append((owner, repo, title, head, base, body))
        return _FakeResponse(_FakePullRequest(42, f"https://github.com/{owner}/{repo}/pull/42"))

    async def async_get(self, owner, repo, pr_number):
        self.get_calls.append((owner, repo, pr_number))
        return _FakeResponse(self._full_pr)

    async def async_update(self, owner, repo, pr_number, *, state):
        self.update_calls.append((owner, repo, pr_number, state))


class _FakeIssues:
    def __init__(self) -> None:
        self.comment_calls = []
        self.update_calls = []

    async def async_create_comment(self, owner, repo, issue_number, *, body):
        self.comment_calls.append((owner, repo, issue_number, body))

    async def async_update(self, owner, repo, issue_number, *, state, state_reason=None):
        self.update_calls.append((owner, repo, issue_number, state, state_reason))


class _FakeSearchItem:
    def __init__(self, number: int, title: str, html_url: str, body: str) -> None:
        self.number = number
        self.title = title
        self.html_url = html_url
        self.body = body


class _FakeSearchResults:
    def __init__(self, items: list[_FakeSearchItem]) -> None:
        self.items = items


class _FakeSearch:
    def __init__(self) -> None:
        self.calls = []
        self._results: list[_FakeSearchItem] = []
        self._error: RequestFailed | None = None

    async def async_search_issues(self, *, q, per_page, sort, order):
        self.calls.append((q, per_page, sort, order))
        if self._error is not None:
            raise self._error
        return _FakeResponse(_FakeSearchResults(self._results))


class _FakeGithubkitResponse:
    """Minimal stand-in for githubkit's `Response` — `RequestFailed.__init__` only reads
    `raw_request`/`raw_response`, and client code reads `status_code`."""

    def __init__(self, status_code: int) -> None:
        request = httpx.Request("GET", "https://api.github.com/search/issues")
        self.raw_request = request
        self.raw_response = httpx.Response(status_code, request=request)
        self.status_code = status_code


class _FakeRest:
    def __init__(self) -> None:
        self.pulls = _FakePulls()
        self.issues = _FakeIssues()
        self.search = _FakeSearch()


class _FakeGitHub:
    def __init__(self) -> None:
        self.rest = _FakeRest()


@pytest.mark.asyncio
async def test_open_pull_request_returns_number_and_html_url(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    number, url = await open_pull_request(
        "acme/demo", head="artisan/ART-1-attempt-1", base="main", title="Artisan: fix bug", body="body"
    )

    assert number == 42
    assert url == "https://github.com/acme/demo/pull/42"
    assert fake_gh.rest.pulls.calls == [
        ("acme", "demo", "Artisan: fix bug", "artisan/ART-1-attempt-1", "main", "body")
    ]


@pytest.mark.asyncio
async def test_close_pull_request_comments_then_closes(monkeypatch) -> None:
    """Issue-deleted cleanup (completion.handle_issue_deleted): the explanation comment is posted
    before the close, and the close uses pulls.update(state="closed") — never a force-push or
    anything that touches the branch."""
    fake_gh = _FakeGitHub()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    await close_pull_request("acme/demo", 42, "closing because the issue was deleted")

    assert fake_gh.rest.issues.comment_calls == [
        ("acme", "demo", 42, "closing because the issue was deleted")
    ]
    assert fake_gh.rest.pulls.update_calls == [("acme", "demo", 42, "closed")]


def test_build_issue_search_query_scopes_to_repo_and_open_issues() -> None:
    query = build_issue_search_query("acme/demo", "Password reset link returns a blank page", "")

    assert query.startswith("repo:acme/demo is:issue is:open in:title,body ")
    assert "password" in query
    assert "reset" in query


def test_build_issue_search_query_backfills_body_when_title_sparse() -> None:
    query = build_issue_search_query("acme/demo", "crash", "the app crashes when exporting a large CSV")

    assert "exporting" in query


def test_build_issue_search_query_drops_stopwords_and_short_tokens() -> None:
    query = build_issue_search_query("acme/demo", "The bug fix for the API please", "")

    assert "the" not in query
    assert "bug" not in query  # stopword
    assert "api" in query


@pytest.mark.asyncio
async def test_search_similar_issues_excludes_self_and_maps_hits(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    fake_gh.rest.search._results = [
        _FakeSearchItem(1, "same", "https://github.com/acme/demo/issues/1", "body one"),
        _FakeSearchItem(12, "other", "https://github.com/acme/demo/issues/12", "body twelve"),
    ]
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    hits = await search_similar_issues("acme/demo", "Password reset", "body", exclude_number=1)

    assert [h.issue_number for h in hits] == [12]
    assert hits[0].html_url == "https://github.com/acme/demo/issues/12"
    assert fake_gh.rest.search.calls[0][0].startswith("repo:acme/demo is:issue is:open")
    assert fake_gh.rest.search.calls[0][1] == 10  # per_page == DUPLICATE_SEARCH_LIMIT


@pytest.mark.asyncio
async def test_search_similar_issues_treats_422_and_403_as_no_candidates(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    for status in (422, 403):
        fake_gh.rest.search._error = RequestFailed(_FakeGithubkitResponse(status))
        hits = await search_similar_issues("acme/demo", "Password reset", "body", exclude_number=1)
        assert hits == []


@pytest.mark.asyncio
async def test_close_issue_as_duplicate_comments_then_closes(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    await close_issue_as_duplicate("acme/demo", 7, 12)

    assert fake_gh.rest.issues.comment_calls == [
        ("acme", "demo", 7, ("Closing this as a duplicate of #12 — the reporter confirmed it "
                              "covers the same request as https://github.com/acme/demo/issues/12."))
    ]
    assert fake_gh.rest.issues.update_calls == [("acme", "demo", 7, "closed", "not_planned")]


@pytest.mark.asyncio
async def test_get_pull_request_returns_title_body_and_refs(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    fake_gh.rest.pulls._full_pr = _FakeFullPullRequest(
        title="Artisan: fix bug",
        body="Resolves #1.",
        base_ref="main",
        head_ref="artisan/ART-1-attempt-1",
        head_sha="deadbeef",
    )
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    title, body, base_ref, head_ref, head_sha = await get_pull_request("acme/demo", 5)

    assert (title, body, base_ref, head_ref, head_sha) == (
        "Artisan: fix bug", "Resolves #1.", "main", "artisan/ART-1-attempt-1", "deadbeef",
    )
    assert fake_gh.rest.pulls.get_calls == [("acme", "demo", 5)]


@pytest.mark.asyncio
async def test_get_pull_request_treats_a_null_body_as_empty_string(monkeypatch) -> None:
    fake_gh = _FakeGitHub()
    fake_gh.rest.pulls._full_pr = _FakeFullPullRequest(
        title="T", body=None, base_ref="main", head_ref="head", head_sha="sha",
    )
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    _title, body, *_rest = await get_pull_request("acme/demo", 5)
    assert body == ""


def _request_failed(status_code: int) -> RequestFailed:
    # RequestFailed.__init__ needs a real githubkit Response wrapping an httpx one; bypassing it
    # (same pattern as test_dispatch.py's `_request_failed`) lets the test assert purely on the
    # `.response.status_code` classification get_file_content branches on.
    exc = RequestFailed.__new__(RequestFailed)
    exc.response = httpx.Response(status_code, request=httpx.Request("GET", "https://example.com"))
    return exc


class _FakeRepoInfo:
    def __init__(self, default_branch: str) -> None:
        self.default_branch = default_branch


class _FakeGitObject:
    def __init__(self, sha: str) -> None:
        self.sha = sha


class _FakeGitRef:
    def __init__(self, sha: str) -> None:
        self.object_ = _FakeGitObject(sha)


class _FakeReposForContext:
    def __init__(self) -> None:
        self.get_calls = []
        self.content_calls = []
        self._default_branch = "main"
        self._content: str | None = None
        self._raise: Exception | None = None

    async def async_get(self, owner, repo):
        self.get_calls.append((owner, repo))
        return _FakeResponse(_FakeRepoInfo(self._default_branch))

    async def async_get_content(self, owner, repo, *, path, ref):
        self.content_calls.append((owner, repo, path, ref))
        if self._raise is not None:
            raise self._raise
        return _FakeResponse(type("_Content", (), {"content": self._content})())


class _FakeTreeEntry:
    def __init__(self, path: str, type_: str) -> None:
        self.path = path
        self.type = type_


class _FakeTreeResponseData:
    def __init__(self, entries: list[_FakeTreeEntry]) -> None:
        self.tree = entries


class _FakeGit:
    def __init__(self) -> None:
        self.ref_calls = []
        self.tree_calls = []
        self._ref_sha = "deadbeef"
        self._tree_entries: list[_FakeTreeEntry] = []

    async def async_get_ref(self, owner, repo, *, ref):
        self.ref_calls.append((owner, repo, ref))
        return _FakeResponse(_FakeGitRef(self._ref_sha))

    async def async_get_tree(self, owner, repo, sha, *, recursive):
        self.tree_calls.append((owner, repo, sha, recursive))
        return _FakeResponse(_FakeTreeResponseData(self._tree_entries))


class _FakeGitHubForContext:
    def __init__(self) -> None:
        self.rest = type("_Rest", (), {})()
        self.rest.repos = _FakeReposForContext()
        self.rest.git = _FakeGit()


@pytest.mark.asyncio
async def test_get_default_branch_head_sha_resolves_default_branch_then_its_ref(monkeypatch) -> None:
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.repos._default_branch = "develop"
    fake_gh.rest.git._ref_sha = "abc123"
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    sha = await get_default_branch_head_sha("acme/demo")

    assert sha == "abc123"
    assert fake_gh.rest.repos.get_calls == [("acme", "demo")]
    assert fake_gh.rest.git.ref_calls == [("acme", "demo", "heads/develop")]


@pytest.mark.asyncio
async def test_get_default_branch_returns_repo_default_branch(monkeypatch) -> None:
    """Gate 2's PR base: the repo's actual default branch, not a hardcoded `main`."""
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.repos._default_branch = "develop"
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    branch = await get_default_branch("acme/demo")

    assert branch == "develop"
    assert fake_gh.rest.repos.get_calls == [("acme", "demo")]


@pytest.mark.asyncio
async def test_get_repo_tree_filters_directories_node_modules_and_git_and_caps_length(
    monkeypatch,
) -> None:
    fake_gh = _FakeGitHubForContext()
    entries = [
        _FakeTreeEntry("src/index.ts", "blob"),
        _FakeTreeEntry("src", "tree"),
        _FakeTreeEntry("node_modules/left-pad/index.js", "blob"),
        _FakeTreeEntry(".git/HEAD", "blob"),
        _FakeTreeEntry("package.json", "blob"),
    ]
    fake_gh.rest.git._tree_entries = entries
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    paths = await get_repo_tree("acme/demo", "sha1")

    assert paths == ["src/index.ts", "package.json"]
    assert fake_gh.rest.git.tree_calls == [("acme", "demo", "sha1", "true")]


@pytest.mark.asyncio
async def test_get_repo_tree_caps_to_max_entries(monkeypatch) -> None:
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.git._tree_entries = [
        _FakeTreeEntry(f"file{i}.py", "blob")
        for i in range(github_client_module.REPO_TREE_MAX_ENTRIES + 10)
    ]
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    paths = await get_repo_tree("acme/demo", "sha1")

    assert len(paths) == github_client_module.REPO_TREE_MAX_ENTRIES


@pytest.mark.asyncio
async def test_get_file_content_decodes_base64_content(monkeypatch) -> None:
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.repos._content = base64.b64encode(b'{"name": "demo"}').decode("ascii")
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    content = await get_file_content("acme/demo", "package.json", "sha1")

    assert content == '{"name": "demo"}'
    assert fake_gh.rest.repos.content_calls == [("acme", "demo", "package.json", "sha1")]


@pytest.mark.asyncio
async def test_get_file_content_returns_none_on_404(monkeypatch) -> None:
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.repos._raise = _request_failed(404)
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    content = await get_file_content("acme/demo", "missing.json", "sha1")

    assert content is None


@pytest.mark.asyncio
async def test_get_file_content_reraises_non_404_failures(monkeypatch) -> None:
    fake_gh = _FakeGitHubForContext()
    fake_gh.rest.repos._raise = _request_failed(500)
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    with pytest.raises(RequestFailed):
        await get_file_content("acme/demo", "package.json", "sha1")


class _FakeIssuesForLabels:
    def __init__(self, *, fail_first_add_with: int | None = None) -> None:
        self.add_labels_calls = []
        self.create_label_calls = []
        self._fail_first_add_with = fail_first_add_with

    async def async_add_labels(self, owner, repo, issue_number, *, labels):
        self.add_labels_calls.append((owner, repo, issue_number, labels))
        if self._fail_first_add_with is not None and len(self.add_labels_calls) == 1:
            raise _request_failed(self._fail_first_add_with)
        return _FakeResponse(None)

    async def async_create_label(self, owner, repo, *, name, color):
        self.create_label_calls.append((owner, repo, name, color))
        return _FakeResponse(None)


class _FakeGitHubForLabels:
    def __init__(self, *, fail_first_add_with: int | None = None) -> None:
        self.rest = type("_Rest", (), {})()
        self.rest.issues = _FakeIssuesForLabels(fail_first_add_with=fail_first_add_with)


@pytest.mark.asyncio
async def test_add_label_success_path_does_not_create_label(monkeypatch) -> None:
    fake_gh = _FakeGitHubForLabels()
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    await add_label("acme/demo", 42, "artisan:ready-for-review")

    assert fake_gh.rest.issues.add_labels_calls == [
        ("acme", "demo", 42, ["artisan:ready-for-review"])
    ]
    assert fake_gh.rest.issues.create_label_calls == []


@pytest.mark.asyncio
async def test_add_label_creates_label_then_retries_when_label_does_not_exist(monkeypatch) -> None:
    fake_gh = _FakeGitHubForLabels(fail_first_add_with=422)
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    await add_label("acme/demo", 42, "artisan:ready-for-review")

    assert fake_gh.rest.issues.create_label_calls == [
        ("acme", "demo", "artisan:ready-for-review", "0e8a16")
    ]
    assert len(fake_gh.rest.issues.add_labels_calls) == 2


@pytest.mark.asyncio
async def test_add_label_reraises_non_422_failures(monkeypatch) -> None:
    fake_gh = _FakeGitHubForLabels(fail_first_add_with=500)
    monkeypatch.setattr(github_client_module, "get_installation_client", lambda: fake_gh)

    with pytest.raises(RequestFailed):
        await add_label("acme/demo", 42, "artisan:ready-for-review")

    assert fake_gh.rest.issues.create_label_calls == []


# --- WS1: count_markdown_images / extract_and_download_images -------------------------------


def test_count_markdown_images_counts_across_body_and_comments() -> None:
    body = "see ![screenshot](https://example.com/a.png) for context"
    comments = [
        "also ![this](https://example.com/b.png) and ![that](https://example.com/c.png)",
        "no images here",
    ]
    assert count_markdown_images(body, comments) == 3


def test_count_markdown_images_dedupes_repeated_urls() -> None:
    body = "![a](https://example.com/a.png) again: ![a](https://example.com/a.png)"
    assert count_markdown_images(body, []) == 1


def test_count_markdown_images_ignores_non_markdown_image_text() -> None:
    body = "a bare link https://example.com/a.png isn't markdown image syntax"
    assert count_markdown_images(body, []) == 0


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_extract_and_download_images_downloads_and_dedupes(monkeypatch) -> None:
    body = (
        "title has none. ![a](https://img.example.com/one.png) "
        "duplicate: ![a again](https://img.example.com/one.png)"
    )
    comments = ["![b](https://img.example.com/two.jpg)"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/png"})

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    images = await extract_and_download_images("title", body, comments)

    assert len(images) == 2  # deduped: only 2 unique URLs
    assert all(data == b"bytes" and mime == "image/png" for data, mime in images)


@pytest.mark.asyncio
async def test_extract_and_download_images_stops_after_three_successes(monkeypatch) -> None:
    body = "".join(f"![i{i}](https://img.example.com/{i}.png)" for i in range(6))

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    images = await extract_and_download_images("title", body, [])

    assert len(images) == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_extract_and_download_images_skips_oversized_downloads(monkeypatch) -> None:
    body = "![big](https://img.example.com/big.png)"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 10,
            headers={
                "content-type": "image/png",
                "content-length": str(github_client_module.MAX_IMAGE_BYTES + 1),
            },
        )

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    images = await extract_and_download_images("title", body, [])

    assert images == []


@pytest.mark.asyncio
async def test_extract_and_download_images_skips_failed_downloads(monkeypatch) -> None:
    body = (
        "![broken](https://img.example.com/broken.png) "
        "![ok](https://img.example.com/ok.png)"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "broken" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=b"ok", headers={"content-type": "image/png"})

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    images = await extract_and_download_images("title", body, [])

    assert len(images) == 1
    assert images[0] == (b"ok", "image/png")


@pytest.mark.asyncio
async def test_extract_and_download_images_falls_back_to_url_extension_when_content_type_missing(
    monkeypatch,
) -> None:
    body = "![a](https://img.example.com/photo.jpg)"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"jpgbytes")

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    images = await extract_and_download_images("title", body, [])

    assert images == [(b"jpgbytes", "image/jpeg")]
