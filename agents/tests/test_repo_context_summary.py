"""Unit tests for the shared repo-context summary (v2 wave 1.5 #16): manifest *contents* (bounded
excerpts) surface alongside paths/languages, so routing and domain-expert prompts can tell real
frameworks apart — and both agents consume the same helper."""

from datetime import datetime, timezone

from artisan_agents.agents import domain_expert_agent, routing_agent
from artisan_agents.repo_context_summary import (
    _MAX_MANIFEST_CHARS,
    _MAX_MANIFEST_LINES,
    repo_context_summary,
)
from artisan_shared.models import RepoContext

_PYPROJECT = '[project]\nname = "demo"\ndependencies = ["fastapi>=0.100", "uvicorn"]\n'


def _ctx(*, manifests: dict[str, str], languages: dict[str, int] | None = None) -> RepoContext:
    return RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=list(manifests.keys()),
        manifests=manifests,
        languages=languages or {".py": 10},
        fetched_at=datetime.now(timezone.utc),
    )


def test_summary_surfaces_manifest_contents_not_just_paths() -> None:
    summary = repo_context_summary(_ctx(manifests={"pyproject.toml": _PYPROJECT}))
    assert "pyproject.toml" in summary
    assert "fastapi" in summary  # the actual signal routing was blind to before #16
    assert "uvicorn" in summary


def test_summary_wraps_manifest_excerpts_as_untrusted() -> None:
    # Manifest content is repo-sourced, but a merged malicious manifest is injection surface too.
    summary = repo_context_summary(_ctx(manifests={"pyproject.toml": _PYPROJECT}))
    assert "<untrusted_content>" in summary
    assert "</untrusted_content>" in summary


def test_summary_truncates_manifest_excerpts_by_lines_and_chars() -> None:
    many_lines = "\n".join(f"line-{i} = {i}" for i in range(500))
    summary = repo_context_summary(_ctx(manifests={"pyproject.toml": many_lines}))
    assert "line-39" in summary
    assert "line-40" not in summary  # beyond _MAX_MANIFEST_LINES

    long_line = "x" * (_MAX_MANIFEST_CHARS * 3)
    summary = repo_context_summary(_ctx(manifests={"pyproject.toml": long_line}))
    excerpt = summary.split("<untrusted_content>\n", 1)[1].split("\n</untrusted_content>", 1)[0]
    assert len(excerpt) <= _MAX_MANIFEST_CHARS
    assert _MAX_MANIFEST_LINES == 40  # guard the budget constants the assertions above rely on


def test_summary_caps_the_number_of_manifest_excerpts() -> None:
    manifests = {f"pkg-{i}/pyproject.toml": _PYPROJECT for i in range(6)}
    summary = repo_context_summary(_ctx(manifests=manifests))
    assert summary.count("(excerpt) ---") == 4  # _MAX_MANIFESTS
    assert "pkg-5/pyproject.toml" in summary  # path still listed even without an excerpt


def test_summary_omits_excerpts_for_empty_manifest_contents() -> None:
    summary = repo_context_summary(_ctx(manifests={"pyproject.toml": "   "}))
    assert "Manifest excerpts" not in summary
    assert "pyproject.toml" in summary  # path still listed


def test_summary_handles_no_manifests() -> None:
    summary = repo_context_summary(_ctx(manifests={}))
    assert "(none detected)" in summary
    assert "Manifest excerpts" not in summary


def test_routing_and_domain_expert_prompts_share_the_same_summary() -> None:
    ctx = _ctx(manifests={"pyproject.toml": _PYPROJECT})
    routing_prompt = routing_agent._build_prompt("T", "B", "ART-1", ctx)
    expert_prompt = domain_expert_agent._build_prompt("backend", "T", "B", ctx)
    for prompt in (routing_prompt, expert_prompt):
        assert "fastapi" in prompt
        assert "Manifest excerpts" in prompt


def test_file_tree_is_opt_in_and_expert_opts_in() -> None:
    # The expert names concrete relevant_files, so it gets the tree (wave-1.6: without it, 71.6%
    # of predicted paths were hallucinated). Routing only classifies domains — it keeps the
    # cheaper prompt.
    ctx = _ctx(manifests={"pyproject.toml": _PYPROJECT})
    assert "Repo file tree" not in repo_context_summary(ctx)
    assert "Repo file tree" in repo_context_summary(ctx, include_file_tree=True)

    routing_prompt = routing_agent._build_prompt("T", "B", "ART-1", ctx)
    expert_prompt = domain_expert_agent._build_prompt("backend", "T", "B", ctx)
    assert "Repo file tree" not in routing_prompt
    assert "Repo file tree" in expert_prompt


def test_file_tree_sample_is_capped_with_truncation_note() -> None:
    tree = [f"src/mod-{i}.py" for i in range(250)]
    ctx = RepoContext(
        repo="octocat/demo", head_sha="deadbeef", file_tree=tree, manifests={},
        languages={".py": 250}, fetched_at=datetime.now(timezone.utc),
    )
    summary = repo_context_summary(ctx, include_file_tree=True)
    assert "src/mod-199.py" in summary
    assert "src/mod-200.py" not in summary  # beyond _MAX_FILE_TREE_SAMPLE
    assert "50 more files not shown" in summary


def test_file_tree_empty_tree_renders_placeholder() -> None:
    summary = repo_context_summary(_ctx(manifests={}), include_file_tree=True)
    assert "(empty tree)" in summary
