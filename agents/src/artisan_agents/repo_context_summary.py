"""Shared repo-context summary for the routing and domain-expert prompts (v2 wave 1.5 #16).

Both agents previously inlined an identical private `_repo_context_summary` that surfaced only
manifest *paths* and a language histogram — even though `RepoContext.manifests` already caches
full manifest *contents*. A routing decision that can't see dependency names can't tell Django
from FastAPI (or a CLI `Cargo.toml` from a web `Cargo.toml`). This helper surfaces bounded
manifest excerpts alongside the paths so both prompts reason over the same richer signal.

planning_agent keeps its own, separate summary: it grounds `touched_files`/`removed_code` in the
file *tree* (a different cut of the context), not in manifest contents.

Budgets keep the prompt bounded on large monorepos: at most `_MAX_MANIFESTS` excerpts, each
capped by lines and chars. Manifest content is repo-sourced (not issue-reporter-sourced), but
excerpts are still wrapped as untrusted — a merged malicious manifest is injection surface too.
"""

import re

from artisan_shared.models import RepoContext
from artisan_shared.prompt_safety import wrap_untrusted

_MAX_LANGUAGES = 5
_MAX_MANIFESTS = 4
_MAX_MANIFEST_LINES = 40
_MAX_MANIFEST_CHARS = 2000
_MAX_FILE_TREE_SAMPLE = 200  # same budget planning_agent uses for grounding touched_files
_MAX_SKELETON_ENTRIES = 30

# Cheap lexical relevance: enough to surface "files whose path mentions what the issue talks
# about" without embeddings. Stopwords keep generic English from matching path segments.
_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "when", "from", "into", "are", "not",
    "should", "must", "have", "has", "been", "will", "would", "could", "all", "any", "our",
    "your", "their", "its", "use", "using", "used", "via", "per", "each", "every",
}


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2 and t not in _STOPWORDS
    }


def ranked_file_sample(
    paths: list[str], query: str, budget: int = _MAX_FILE_TREE_SAMPLE
) -> list[str]:
    """Relevance-ranked file-tree sample (v2 wave 1.6): an alphabetical first-N of a 10k-file
    repo covers ~2% of it — useless grounding on SWE-bench-scale repos. Rank paths by token
    overlap between the issue text and path segments; ties keep the tree's original (sorted)
    order so output stays deterministic. With an empty query, degenerates to the first-N cut."""
    if not query.strip():
        return paths[:budget]
    query_tokens = _tokens(query)

    def score(path: str) -> int:
        return len(query_tokens & _tokens(path))

    return sorted(paths, key=lambda p: -score(p))[:budget]


def _top_level_skeleton(paths: list[str]) -> str:
    entries = sorted({p.split("/", 1)[0] + ("/" if "/" in p else "") for p in paths})
    shown = entries[:_MAX_SKELETON_ENTRIES]
    suffix = f", ... ({len(entries) - len(shown)} more)" if len(entries) > len(shown) else ""
    return ", ".join(shown) + suffix or "(empty tree)"


def _manifest_excerpt(content: str) -> str:
    excerpt = "\n".join(content.splitlines()[:_MAX_MANIFEST_LINES])
    return excerpt[:_MAX_MANIFEST_CHARS]


def repo_context_summary(
    repo_context: RepoContext, *, include_file_tree: bool = False, query: str = ""
) -> str:
    top_languages = sorted(repo_context.languages.items(), key=lambda kv: kv[1], reverse=True)[
        :_MAX_LANGUAGES
    ]
    languages_str = ", ".join(f"{ext} ({count})" for ext, count in top_languages) or "(none detected)"
    manifest_paths = list(repo_context.manifests.keys())
    manifests_str = ", ".join(manifest_paths) or "(none detected)"
    summary = (
        f"\n\nRepo context — top languages by file count: {languages_str}. "
        f"Manifest files found: {manifests_str}."
    )

    excerpts = []
    for path in manifest_paths[:_MAX_MANIFESTS]:
        content = repo_context.manifests[path]
        if content.strip():
            excerpts.append(f"--- {path} (excerpt) ---\n{wrap_untrusted(_manifest_excerpt(content))}")
    if excerpts:
        summary += "\n\nManifest excerpts:\n" + "\n\n".join(excerpts)

    # Opt-in: the domain expert names concrete relevant_files — without the tree it invents
    # plausible paths (measured 71.6% hallucinated in the wave-1.6 expert eval). Routing keeps
    # the cheaper prompt: it classifies domains, it doesn't name files. The sample is
    # relevance-ranked against the issue when a query is given, with a top-level skeleton so
    # global structure survives even when the ranked sample is narrow.
    if include_file_tree:
        tree = repo_context.file_tree
        sample = ranked_file_sample(tree, query)
        listing = "\n".join(f"- {p}" for p in sample) or "(empty tree)"
        truncated = (
            f"\n... ({len(tree) - len(sample)} more files not shown)"
            if len(tree) > len(sample)
            else ""
        )
        summary += (
            f"\n\nRepo layout: {_top_level_skeleton(tree)}"
            f"\n\nRepo file tree (sample{', ranked by relevance to the issue' if query.strip() else ''}):"
            f"\n{listing}{truncated}"
        )
    return summary
