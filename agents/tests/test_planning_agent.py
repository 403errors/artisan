"""Unit tests for the Planning Agent (Phase 3.3 DoD, generalized by Sprint 7 WS5): a plan for
*any* domain must always end up with non-empty test_cases/doc_updates — enforced by a post-hoc
retry, not just trusted from the model, and no longer gated on a "frontend" domain being present —
and prior-attempt feedback is threaded into the prompt only when given. Stubs the underlying model
— never calls live Gemini."""

from datetime import datetime, timezone

import pytest

from artisan_agents.agents import planning_agent as planning_agent_module
from artisan_agents.agents.planning_agent import _build_prompt, planning_agent, run_planning
from artisan_shared.models import DomainExpertOutput, RepoContext
from google.genai import types
from tests.conftest import FakeLlm


def _repo_context(*, manifests: dict[str, str], file_tree: list[str] | None = None) -> RepoContext:
    return RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=file_tree if file_tree is not None else list(manifests.keys()),
        manifests=manifests,
        languages={".py": 10, ".ts": 3},
        fetched_at=datetime.now(timezone.utc),
    )


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
async def test_backend_only_hollow_plan_is_also_retried(stub_model) -> None:
    # WS5: the retry is no longer gated on a "frontend" domain being present — every domain now
    # requires non-empty test_cases/doc_updates.
    stub_model(
        '{"steps": ["Add endpoint"], "touched_files": ["b.py"], "test_cases": [], "doc_updates": []}',
        '{"steps": ["Add endpoint"], "touched_files": ["b.py"], '
        '"test_cases": ["exports data via /export"], "doc_updates": ["document /export endpoint"]}',
    )
    plan = await run_planning(
        domain_outputs=[_BACKEND_OUTPUT], issue_title="Add endpoint", issue_body="Add /export."
    )
    assert plan.test_cases
    assert plan.doc_updates


def test_prompt_includes_prior_feedback_block_only_when_given() -> None:
    without_feedback = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", None)
    with_feedback = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", "fix the color hex code")

    assert "PRIOR ATTEMPT FEEDBACK" not in without_feedback
    assert "PRIOR ATTEMPT FEEDBACK" in with_feedback
    assert "fix the color hex code" in with_feedback


def test_prompt_includes_repo_context_summary_only_when_given() -> None:
    without_context = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", None, None)
    context = _repo_context(
        manifests={"package.json": '{"name": "demo"}'},
        file_tree=["package.json", "src/App.tsx", "src/index.ts"],
    )
    with_context = _build_prompt([_FRONTEND_OUTPUT], "Title", "Body", None, context)

    assert "Repo context" not in without_context
    assert "Repo context" in with_context
    assert "src/App.tsx" in with_context
    assert "package.json" in with_context
    assert '{"name": "demo"}' in with_context


def test_removed_code_round_trips_on_plan() -> None:
    from artisan_shared.models import Plan, RemovedCodeItem

    plan = Plan(
        steps=["Remove legacy handler"],
        touched_files=["a.py"],
        test_cases=["still handles new path"],
        doc_updates=["update README"],
        removed_code=[
            RemovedCodeItem(file="a.py", symbol="legacy_handler", reason="superseded by new_handler")
        ],
    )
    dumped = plan.model_dump()
    restored = Plan.model_validate(dumped)

    assert restored.removed_code == plan.removed_code
    assert restored.removed_code[0].symbol == "legacy_handler"


def test_plan_defaults_removed_code_to_empty_list() -> None:
    from artisan_shared.models import Plan

    plan = Plan(steps=[], touched_files=[], test_cases=[], doc_updates=[])
    assert plan.removed_code == []


def test_planning_agent_is_configured_with_high_thinking_level() -> None:
    config = planning_agent.generate_content_config
    assert config is not None
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == types.ThinkingLevel.HIGH
