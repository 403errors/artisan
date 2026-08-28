"""Unit tests for the Intake Agent's branching (Phase 2.3 DoD). Stubs the underlying model with a
minimal fake `BaseLlm` so these never call the live Gemini API — only an explicitly-marked
integration test should do that."""

from collections.abc import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from artisan_agents.agents import intake_agent as intake_agent_module
from artisan_agents.agents.intake_agent import run_intake


class _FakeLlm(BaseLlm):
    model: str = "fake"
    response_text: str = ""

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.response_text)])
        )


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(intake_agent_module.intake_agent, "model", _FakeLlm(response_text=response_json))

    return _stub


@pytest.mark.asyncio
async def test_vague_issue_is_insufficient_with_a_specific_question(stub_model) -> None:
    stub_model(
        '{"sufficient": false, "missing_context_question": '
        '"Which page/endpoint is affected, and what did you expect vs. see?"}'
    )
    verdict = await run_intake(
        issue_title="Login is broken",
        issue_body="the login is broken",
        thread=[],
        jira_key="ART-1",
    )
    assert verdict.sufficient is False
    assert verdict.missing_context_question
    assert len(verdict.missing_context_question) > 0


@pytest.mark.asyncio
async def test_well_specified_issue_is_sufficient(stub_model) -> None:
    stub_model('{"sufficient": true}')
    verdict = await run_intake(
        issue_title="Password reset email link 404s",
        issue_body=(
            "Steps: 1) request password reset 2) click the emailed link. "
            "Expected: reset form loads. Actual: 404 at /auth/reset?token=... "
            "Affects src/routes/auth/reset.tsx."
        ),
        thread=[],
        jira_key="ART-2",
    )
    assert verdict.sufficient is True
    assert verdict.missing_context_question is None
