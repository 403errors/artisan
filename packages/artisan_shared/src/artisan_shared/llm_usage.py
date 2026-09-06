"""Token-usage telemetry (v2 cost levers, L2a).

Both LLM call paths — `agents/_run_agent.py::run_structured` and the execution-sandbox's
`coding_agent` loop — stream ADK events whose `usage_metadata` carries per-model-call token
counts. Accumulating them makes cost measurable and, via `cached_content_token_count`, shows
whether Vertex's implicit context caching is actually hitting (the gate for any explicit-caching
work). Duck-typed on purpose: artisan_shared has no google-genai dependency, so anything with the
`GenerateContentResponseUsageMetadata` attribute shape (real or test double) works.
"""

# Billed-relevant fields on google.genai's GenerateContentResponseUsageMetadata. `total` is
# derived (prompt + candidates + thoughts), not read from the event, so the dict stays consistent
# even when the API omits total_token_count.
USAGE_FIELDS = (
    "prompt_token_count",
    "candidates_token_count",
    "cached_content_token_count",
    "thoughts_token_count",
)


def new_usage_totals() -> dict[str, int]:
    """Zero-initialized accumulator for `accumulate_usage`."""
    return {field: 0 for field in USAGE_FIELDS}


def accumulate_usage(totals: dict[str, int], usage_metadata: object) -> None:
    """Sums one event's usage metadata into `totals` in place. None/absent metadata (fake LLMs in
    tests, non-model events) and None fields (API omits unset counts) are all no-ops/zeros."""
    if usage_metadata is None:
        return
    for field in USAGE_FIELDS:
        value = getattr(usage_metadata, field, None)
        if value:
            totals[field] += value


def usage_summary(totals: dict[str, int]) -> str:
    """One-line human form for event summaries, e.g.
    `prompt=12040 (cached=8000, 66%) output=312 thoughts=0`."""
    prompt = totals["prompt_token_count"]
    cached = totals["cached_content_token_count"]
    cached_str = f"cached={cached}, {round(100 * cached / prompt)}%" if prompt else f"cached={cached}"
    return (
        f"prompt={prompt} ({cached_str}) "
        f"output={totals['candidates_token_count']} thoughts={totals['thoughts_token_count']}"
    )
