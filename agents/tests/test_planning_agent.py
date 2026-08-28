"""Unit tests for the Planning Agent (Phase 3.3 DoD): a plan for a frontend (user-facing) change
must always end up with non-empty test_cases/doc_updates — enforced by a post-hoc retry, not just
trusted from the model — and prior-attempt feedback is threaded into the prompt only when given.
Stubs the underlying model — never calls live Gemini."""

import pytest

from artisan_agents.agents import planning_agent as planning_agent_module
from artisan_agents.agents.planning_agent import _build_prompt, run_planning
from artisan_shared.models import DomainExpertOutput
from tests.conftest import FakeLlm


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(*response_jsons: str) -> None:
        # Supports a single response, or two responses to simulate the post-hoc retry path
        # (first call returns something hollow, second call returns the amended plan).
        responses = iter(response_jsons)
        llm = FakeLlm(response_text=response_jsons[0])

        original = planning_agent_module.run_structured

        async def _run_structured(**kwargs):
            llm.response_text = next(responses)
            monkeypatch.setattr(planning_agent_module.planning_agent, "model", llm)
            return await original(**kwargs)

        monkeypatch.setattr(planning_agent_module, "run_structured", _run_structured)

    return _stub


_FRONTEND_OUTPUT = DomainExpertOutput(
    domain="frontend", technical_summary="Change button color to blue.", relevant_files=["a.tsx"]
)
_BACKEND_OUTPUT = DomainExpertOutput(
    domain="backend", technical_summary="Add export endpoint.", relevant_files=["b.py"]
)


@pytest.mark.asyncio
async def test_plan_for_frontend_change_has_non_empty_tests_and_docs(stub_model) -> None:
    stub_model(
        '{"steps": ["Update button color"], "touched_files": ["a.tsx"], '
        '"test_cases": ["renders blue button"], "doc_updates": ["update component README"]}'
    )
    plan = await run_planning(
        domain_outputs=[_FRONTEND_OUTPUT], issue_title="Button color", issue_body="Make it blue."
    )
    assert plan.test_cases
    assert plan.doc_updates


@pytest.mark.asyncio
async def test_hollow_plan_for_frontend_change_is_retried_once(stub_model) -> None:
    stub_model(
        '{"steps": ["Update button color"], "touched_files": ["a.tsx"], '
        '"test_cases": [], "doc_updates": []}',
        '{"steps": ["Update button color"], "touched_files": ["a.tsx"], '
        '"test_cases": ["renders blue button"], "doc_updates": ["update component README"]}',
    )
    plan = await run_planning(
        domain_outputs=[_FRONTEND_OUTPUT], issue_title="Button color", issue_body="Make it blue."
    )
    assert plan.test_cases
    assert plan.doc_updates


@pytest.mark.asyncio
async def test_backend_only_plan_is_not_forced_to_retry_when_hollow(stub_model) -> None:
    stub_model(
        '{"steps": ["Add endpoint"], "touched_files": ["b.py"], "test_cases": [], "doc_updates": []}'
    )
    plan = await run_planning(
        domain_outputs=[_BACKEND_OUTPUT], issue_title="Add endpoint", issue_body="Add /export."
    )
    assert plan.test_cases == []
    assert plan.doc_updates == []


def test_prompt_includes_prior_feedback_block_only_when_given() -> None:
    without_feedback = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", None)
    with_feedback = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", "fix the color hex code")

    assert "PRIOR ATTEMPT FEEDBACK" not in without_feedback
    assert "PRIOR ATTEMPT FEEDBACK" in with_feedback
    assert "fix the color hex code" in with_feedback
