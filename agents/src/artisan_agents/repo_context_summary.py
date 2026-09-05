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

from artisan_shared.models import RepoContext
from artisan_shared.prompt_safety import wrap_untrusted

_MAX_LANGUAGES = 5
_MAX_MANIFESTS = 4
_MAX_MANIFEST_LINES = 40
_MAX_MANIFEST_CHARS = 2000


def _manifest_excerpt(content: str) -> str:
    excerpt = "\n".join(content.splitlines()[:_MAX_MANIFEST_LINES])
    return excerpt[:_MAX_MANIFEST_CHARS]


def repo_context_summary(repo_context: RepoContext) -> str:
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
    return summary
