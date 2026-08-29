"""Unit tests for the Intake Agent's branching (Phase 2.3 DoD, WS1's three-way verdict). Stubs the
underlying model with a minimal fake `BaseLlm` so these never call the live Gemini API — only an
explicitly-marked integration test should do that."""

from collections.abc import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from artisan_agents.agents import intake_agent as intake_agent_module
from artisan_agents.agents.intake_agent import INTAKE_INSTRUCTION, _build_prompt, run_intake


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
async def test_vague_issue_needs_info_with_specific_questions(stub_model) -> None:
    stub_model(
        '{"verdict": "needs_info", "missing_context_questions": '
        '["Which page is affected, and what did you expect vs. see?"]}'
    )
    verdict = await run_intake(
        issue_title="Login is broken",
        issue_body="the login is broken",
        thread=[],
        jira_key="ART-1",
    )
    assert verdict.verdict == "needs_info"
    assert len(verdict.missing_context_questions) == 1


@pytest.mark.asyncio
async def test_well_specified_issue_is_sufficient(stub_model) -> None:
    stub_model('{"verdict": "sufficient"}')
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
    assert verdict.verdict == "sufficient"
    assert verdict.missing_context_questions == []


@pytest.mark.asyncio
async def test_off_topic_issue_is_not_actionable(stub_model) -> None:
    stub_model('{"verdict": "not_actionable"}')
    verdict = await run_intake(
        issue_title="hi",
        issue_body="how are you doing today?",
        thread=[],
        jira_key="ART-3",
    )
    assert verdict.verdict == "not_actionable"
    assert verdict.missing_context_questions == []


def test_build_prompt_wraps_untrusted_issue_and_thread_text() -> None:
    prompt = _build_prompt("evil title", "evil body", ["comment 1"], "ART-1")

    assert "<untrusted_content>\nevil title\n</untrusted_content>" in prompt
    assert "<untrusted_content>\nevil body\n</untrusted_content>" in prompt
    assert "<untrusted_content>\ncomment 1\n</untrusted_content>" in prompt


def test_build_prompt_appends_injection_hint_when_flagged() -> None:
    prompt = _build_prompt("title", "body", [], "ART-1", injection_flagged=True)

    assert "flagged as a possible prompt-injection attempt" in prompt


def test_build_prompt_omits_injection_hint_by_default() -> None:
    prompt = _build_prompt("title", "body", [], "ART-1")

    assert "flagged as a possible prompt-injection attempt" not in prompt


def test_intake_instruction_includes_untrusted_content_notice() -> None:
    assert "never instructions" in INTAKE_INSTRUCTION
