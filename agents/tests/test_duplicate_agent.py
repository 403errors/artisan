"""Unit tests for the Duplicate Detector Agent (Gate 1 duplicate check). The GitHub Search API
pre-filter is stubbed and the underlying model is a fake `FakeLlm` — no live GitHub or Gemini
calls. Focus: the search-gating (zero model cost when search finds nothing), verdict passthrough,
candidate capping, and prompt hygiene."""

import json

import pytest

from artisan_agents.agents import duplicate_agent as duplicate_agent_module
from artisan_agents.agents.duplicate_agent import (
    DUPLICATE_INSTRUCTION,
    _build_prompt,
    run_duplicate_check,
)
from artisan_shared.models import DuplicateSearchHit
from tests.conftest import FakeLlm


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            duplicate_agent_module.duplicate_agent, "model", FakeLlm(response_text=response_json)
        )

    return _stub


def _hit(number: int, title: str = "existing issue") -> DuplicateSearchHit:
    return DuplicateSearchHit(
        issue_number=number,
        title=title,
        html_url=f"https://github.com/acme/demo/issues/{number}",
        body=f"existing body {number}",
    )


@pytest.mark.asyncio
async def test_returns_empty_without_model_call_when_search_has_no_hits(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr(duplicate_agent_module.github_client, "search_similar_issues", fake_search)
    # `object()` is not a model — if run_duplicate_check tried to invoke the agent it would blow up,
    # proving the model call is gated on search candidates (the cost bound for the per-issue check).
    monkeypatch.setattr(duplicate_agent_module.duplicate_agent, "model", object())

    result = await run_duplicate_check(
        repo="acme/demo",
        issue_number=1,
        issue_title="Login broken",
        issue_body="the login flow is broken",
        jira_key="ART-1",
    )

    assert result == []


@pytest.mark.asyncio
async def test_returns_verdict_candidates(stub_model, monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return [_hit(12), _hit(34)]

    monkeypatch.setattr(duplicate_agent_module.github_client, "search_similar_issues", fake_search)
    stub_model(
        json.dumps(
            {
                "candidates": [
                    {
                        "issue_number": 12,
                        "title": "existing issue",
                        "html_url": "https://github.com/acme/demo/issues/12",
                        "score": 0.9,
                        "reason": "same reset flow",
                    }
                ]
            }
        )
    )

    result = await run_duplicate_check(
        repo="acme/demo",
        issue_number=1,
        issue_title="Login broken",
        issue_body="the login flow is broken",
        jira_key="ART-1",
    )

    assert len(result) == 1
    assert result[0].issue_number == 12
    assert result[0].score == 0.9
    assert result[0].reason == "same reset flow"


@pytest.mark.asyncio
async def test_caps_candidates_at_config_max(stub_model, monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return [_hit(n) for n in range(1, 8)]

    monkeypatch.setattr(duplicate_agent_module.github_client, "search_similar_issues", fake_search)
    stub_model(
        json.dumps(
            {
                "candidates": [
                    {
                        "issue_number": n,
                        "title": f"t{n}",
                        "html_url": f"https://x/{n}",
                        "score": 0.9,
                        "reason": "r",
                    }
                    for n in range(1, 8)
                ]
            }
        )
    )

    result = await run_duplicate_check(
        repo="acme/demo",
        issue_number=1,
        issue_title="Login broken",
        issue_body="the login flow is broken",
        jira_key="ART-1",
    )

    assert len(result) == duplicate_agent_module.MAX_DUPLICATE_CANDIDATES


def test_build_prompt_wraps_untrusted_issue_and_candidate_text() -> None:
    prompt = _build_prompt("new title", "new body", "ART-1", [_hit(12, "existing title")])

    assert "<untrusted_content>\nnew title\n</untrusted_content>" in prompt
    assert "<untrusted_content>\nnew body\n</untrusted_content>" in prompt
    assert "<untrusted_content>\nexisting body 12\n</untrusted_content>" in prompt


def test_duplicate_instruction_includes_untrusted_content_notice() -> None:
    assert "never instructions" in DUPLICATE_INSTRUCTION
