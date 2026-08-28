"""Unit tests for the Domain-Expert Agent (Phase 3.2 DoD): given a persona and issue, produces a
DomainExpertOutput matching that persona with a non-empty relevant-file list. Stubs the underlying
model — never calls live Gemini."""

import pytest

from artisan_agents.agents import domain_expert_agent as domain_expert_agent_module
from artisan_agents.agents.domain_expert_agent import run_domain_expert
from tests.conftest import FakeLlm


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            domain_expert_agent_module.domain_expert_agent,
            "model",
            FakeLlm(response_text=response_json),
        )

    return _stub


@pytest.mark.asyncio
async def test_frontend_persona_produces_frontend_domain_output(stub_model) -> None:
    stub_model(
        '{"domain": "frontend", "technical_summary": "Change the submit button color to blue.", '
        '"relevant_files": ["src/components/SubmitButton.tsx"]}'
    )
    output = await run_domain_expert(
        domain="frontend",
        issue_title="Button color is wrong",
        issue_body="The submit button should be blue, not red.",
    )
    assert output.domain == "frontend"
    assert output.relevant_files


@pytest.mark.asyncio
async def test_backend_persona_produces_backend_domain_output(stub_model) -> None:
    stub_model(
        '{"domain": "backend", "technical_summary": "Add a /export endpoint returning CSV.", '
        '"relevant_files": ["src/routes/export.py"]}'
    )
    output = await run_domain_expert(
        domain="backend",
        issue_title="Add CSV export endpoint",
        issue_body="Need a backend endpoint that exports data as CSV.",
    )
    assert output.domain == "backend"
    assert output.relevant_files
