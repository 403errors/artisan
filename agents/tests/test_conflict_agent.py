"""Unit tests for the Conflict Agent's classification (Phase 4.2 DoD, verbatim): a synthetic
non-overlapping-region conflict should classify `trivial`; a synthetic same-logic-different-intent
conflict should classify `semantic` with a comparison clearly separating "Side A intent" from
"Side B intent" — not a raw diff dump. Stubs the underlying model — never calls live Gemini."""

import json

import pytest

from artisan_agents.agents import conflict_agent as conflict_agent_module
from artisan_agents.agents.conflict_agent import run_conflict_classification
from artisan_shared.models import ConflictDetectionResult
from tests.conftest import FakeLlm


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            conflict_agent_module.conflict_agent, "model", FakeLlm(response_text=response_json)
        )

    return _stub


@pytest.mark.asyncio
async def test_non_overlapping_region_conflict_classifies_trivial(stub_model) -> None:
    stub_model('{"classification": "trivial"}')
    detection = ConflictDetectionResult(
        has_conflict=True,
        conflicted_files=["app.py"],
        conflict_markers=(
            "--- app.py ---\n"
            "def handler():\n"
            "<<<<<<< HEAD\n"
            "    log_request()\n"
            "    return run()\n"
            "=======\n"
            "    return run()\n"
            "    log_response()\n"
            ">>>>>>> main\n"
        ),
        base_branch_history="a1b2c3d main: add response logging at the end of handler()",
        diff_summary="1 file changed",
        logs_uri="gs://x",
        head_sha="deadbeef",
    )

    verdict = await run_conflict_classification(
        pr_title="Add request logging",
        pr_body="Log every request at the start of handler().",
        detection=detection,
    )

    assert verdict.classification == "trivial"
    assert verdict.resolution_branch is None


@pytest.mark.asyncio
async def test_same_logic_different_intent_conflict_classifies_semantic(stub_model) -> None:
    comparison = (
        "Side A intent: reject the request when the discount exceeds 50%.\n"
        "Side B intent: cap the discount at 50% instead of rejecting the request."
    )
    stub_model(json.dumps({"classification": "semantic", "comparison": comparison}))
    detection = ConflictDetectionResult(
        has_conflict=True,
        conflicted_files=["pricing.py"],
        conflict_markers=(
            "--- pricing.py ---\n"
            "<<<<<<< HEAD\n"
            "if discount > 0.5:\n"
            "    raise ValueError('discount too high')\n"
            "=======\n"
            "discount = min(discount, 0.5)\n"
            ">>>>>>> main\n"
        ),
        base_branch_history="b2c3d4e main: cap oversized discounts instead of erroring",
        diff_summary="1 file changed",
        logs_uri="gs://x",
        head_sha="deadbeef",
    )

    verdict = await run_conflict_classification(
        pr_title="Reject requests with an oversized discount",
        pr_body="Discounts over 50% should be rejected outright.",
        detection=detection,
    )

    assert verdict.classification == "semantic"
    assert "Side A intent" in verdict.comparison
    assert "Side B intent" in verdict.comparison
