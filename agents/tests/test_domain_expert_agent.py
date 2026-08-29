"""Unit tests for the Domain-Expert Agent (Phase 3.2 DoD): given a persona and issue, produces a
DomainExpertOutput matching that persona with a non-empty relevant-file list. Stubs the underlying
model — never calls live Gemini."""

from datetime import datetime, timezone

import pytest
from artisan_agents.agents import domain_expert_agent as domain_expert_agent_module
from artisan_agents.agents.domain_expert_agent import _build_prompt, run_domain_expert
from artisan_shared.models import RepoContext

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


@pytest.mark.asyncio
async def test_unknown_domain_falls_back_to_default_lens_instead_of_raising(stub_model) -> None:
    stub_model(
        '{"domain": "mobile", "technical_summary": "Fix the Flutter widget.", '
        '"relevant_files": ["lib/main.dart"]}'
    )
    output = await run_domain_expert(
        domain="mobile",
        issue_title="Widget layout is broken",
        issue_body="The home screen widget overflows on small devices.",
    )
    assert output.domain == "mobile"


def test_persona_lens_get_falls_back_to_default_lens_for_unknown_domain() -> None:
    prompt = _build_prompt("mobile", "Title", "Body")
    assert "mobile specialist" in prompt
    assert domain_expert_agent_module._DEFAULT_LENS.format(domain="mobile") in prompt


def test_prompt_omits_repo_context_section_when_none() -> None:
    prompt = _build_prompt("frontend", "Title", "Body", None)
    assert "Repo context" not in prompt


def test_prompt_includes_repo_context_summary_when_present() -> None:
    context = RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=["pyproject.toml"],
        manifests={"pyproject.toml": ""},
        languages={".py": 10},
        fetched_at=datetime.now(timezone.utc),
    )
    prompt = _build_prompt("backend", "Title", "Body", context)
    assert "Repo context" in prompt
    assert "pyproject.toml" in prompt
