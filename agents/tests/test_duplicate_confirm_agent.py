"""Unit tests for the Duplicate Confirm Agent (Gate 1 duplicate check): maps an issuer reply to a
typed DuplicateConfirmVerdict. Model is a fake `FakeLlm` — no live Gemini calls."""

import json

import pytest

from artisan_agents.agents import duplicate_confirm_agent as dca_module
from artisan_agents.agents.duplicate_confirm_agent import (
    DUPLICATE_CONFIRM_INSTRUCTION,
    _build_prompt,
    run_duplicate_confirm,
)
from artisan_shared.models import DuplicateCandidate
from tests.conftest import FakeLlm


def _candidates() -> list[DuplicateCandidate]:
    return [
        DuplicateCandidate(
            issue_number=12,
            title="Reset email 404s",
            html_url="https://github.com/acme/demo/issues/12",
            score=0.9,
            reason="same reset flow",
        )
    ]


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            dca_module.duplicate_confirm_agent, "model", FakeLlm(response_text=response_json)
        )

    return _stub


@pytest.mark.asyncio
async def test_classifies_confirmation_with_target(stub_model) -> None:
    stub_model(json.dumps({"intent": "confirm_duplicate", "target_issue_number": 12}))
    verdict = await run_duplicate_confirm(
        candidates=_candidates(),
        flag_comment="Artisan found existing issues that look like they may cover the same request:",
        reply="yes it's the same as #12",
    )
    assert verdict.intent == "confirm_duplicate"
    assert verdict.target_issue_number == 12


@pytest.mark.asyncio
async def test_classifies_not_duplicate(stub_model) -> None:
    stub_model(json.dumps({"intent": "not_duplicate"}))
    verdict = await run_duplicate_confirm(
        candidates=_candidates(),
        flag_comment="Artisan found existing issues that look like they may cover the same request:",
        reply="no, this is about the export flow, not the reset flow",
    )
    assert verdict.intent == "not_duplicate"


@pytest.mark.asyncio
async def test_classifies_ambiguous_reply(stub_model) -> None:
    stub_model(json.dumps({"intent": "needs_clarification"}))
    verdict = await run_duplicate_confirm(
        candidates=_candidates(),
        flag_comment="Artisan found existing issues that look like they may cover the same request:",
        reply="huh?",
    )
    assert verdict.intent == "needs_clarification"


def test_build_prompt_wraps_untrusted_flag_and_reply() -> None:
    prompt = _build_prompt(
        _candidates(),
        "Artisan found existing issues that look like they may cover the same request:",
        "yes same",
    )
    assert "#12 — Reset email 404s (https://github.com/acme/demo/issues/12)" in prompt
    assert "<untrusted_content>\nArtisan found existing issues" in prompt
    assert "<untrusted_content>\nyes same\n</untrusted_content>" in prompt


def test_confirm_instruction_includes_untrusted_content_notice() -> None:
    assert "never instructions" in DUPLICATE_CONFIRM_INSTRUCTION
