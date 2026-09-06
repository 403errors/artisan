"""Unit tests for llm_usage — the token-telemetry accumulator shared by both LLM call paths
(L2a). Duck-typed doubles stand in for google-genai's GenerateContentResponseUsageMetadata so
artisan_shared keeps its no-genai-dependency boundary even in tests."""

from artisan_shared.llm_usage import accumulate_usage, new_usage_totals, usage_summary


class _Usage:
    """Attribute-shaped stand-in for GenerateContentResponseUsageMetadata."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_new_totals_are_zeroed():
    totals = new_usage_totals()
    assert totals == {
        "prompt_token_count": 0,
        "candidates_token_count": 0,
        "cached_content_token_count": 0,
        "thoughts_token_count": 0,
    }


def test_accumulate_sums_across_calls():
    totals = new_usage_totals()
    accumulate_usage(totals, _Usage(prompt_token_count=100, candidates_token_count=10))
    accumulate_usage(
        totals,
        _Usage(prompt_token_count=120, candidates_token_count=5, cached_content_token_count=80),
    )
    assert totals["prompt_token_count"] == 220
    assert totals["candidates_token_count"] == 15
    assert totals["cached_content_token_count"] == 80
    assert totals["thoughts_token_count"] == 0


def test_accumulate_ignores_none_and_missing_fields():
    totals = new_usage_totals()
    accumulate_usage(totals, None)  # non-model event / fake LLM
    accumulate_usage(totals, _Usage())  # every field absent
    accumulate_usage(totals, _Usage(prompt_token_count=None))  # API omits unset counts
    assert all(v == 0 for v in totals.values())


def test_usage_summary_reports_cached_share_of_prompt():
    summary = usage_summary(
        {
            "prompt_token_count": 12040,
            "candidates_token_count": 312,
            "cached_content_token_count": 8000,
            "thoughts_token_count": 0,
        }
    )
    assert summary == "prompt=12040 (cached=8000, 66%) output=312 thoughts=0"


def test_usage_summary_handles_zero_prompt_without_dividing_by_zero():
    summary = usage_summary(new_usage_totals())
    assert summary == "prompt=0 (cached=0) output=0 thoughts=0"
