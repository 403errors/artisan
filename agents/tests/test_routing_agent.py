"""Unit tests for the routing agent's branching (Phase 3.1 DoD): a multi-domain issue should
produce a multi-domain RoutingDecision, a single-domain issue a single-domain one. Stubs the
underlying model — never calls live Gemini."""

from datetime import datetime, timezone

import pytest

from artisan_agents.agents import routing_agent as routing_agent_module
from artisan_agents.agents.routing_agent import _build_prompt, run_routing
from artisan_shared.models import RepoContext
from tests.conftest import FakeLlm


def _repo_context(*, manifests: dict[str, str], languages: dict[str, int] | None = None) -> RepoContext:
    return RepoContext(
        repo="octocat/demo",
        head_sha="deadbeef",
        file_tree=list(manifests.keys()),
        manifests=manifests,
        languages=languages or {".py": 10, ".ts": 3},
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def stub_model(monkeypatch):
    def _stub(response_json: str) -> None:
        monkeypatch.setattr(
            routing_agent_module.routing_agent, "model", FakeLlm(response_text=response_json)
        )

    return _stub


@pytest.mark.asyncio
async def test_single_domain_issue_routes_to_one_domain_sequentially(stub_model) -> None:
    stub_model('{"domains": ["frontend"], "parallel": false}')
    decision = await run_routing(
        issue_title="Button color is wrong",
        issue_body="The submit button should be blue, not red.",
        jira_key="ART-1",
    )
    assert decision.domains == ["frontend"]
    assert decision.parallel is False


@pytest.mark.asyncio
async def test_multi_domain_issue_routes_to_multiple_domains_in_parallel(stub_model) -> None:
    stub_model('{"domains": ["frontend", "backend"], "parallel": true}')
    decision = await run_routing(
        issue_title="Add a new /export endpoint and an Export button",
        issue_body="Add a backend endpoint that exports data as CSV, and a frontend button that calls it.",
        jira_key="ART-2",
    )
    assert set(decision.domains) == {"frontend", "backend"}
    assert decision.parallel is True


def test_prompt_omits_repo_context_section_when_none() -> None:
    prompt = _build_prompt("Title", "Body", "ART-1", None)
    assert "Repo context" not in prompt
    assert prompt == "Jira key: ART-1\n\nIssue title: Title\n\nIssue body:\nBody"


def test_prompt_includes_repo_context_summary_when_present() -> None:
    context = _repo_context(manifests={"pyproject.toml": ""})
    prompt = _build_prompt("Title", "Body", "ART-1", context)
    assert "Repo context" in prompt
    assert "pyproject.toml" in prompt
    assert ".py" in prompt


def test_prompt_mentions_subproject_selection_for_monorepo_manifest_signal() -> None:
    # Multiple manifest files at different directory depths is the monorepo signal the routing
    # instruction tells the model to key off of when deciding `subproject`.
    context = _repo_context(
        manifests={"apps/web/package.json": "", "services/api/pyproject.toml": ""}
    )
    prompt = _build_prompt("Title", "Body", "ART-1", context)
    assert "apps/web/package.json" in prompt
    assert "services/api/pyproject.toml" in prompt
    assert "subproject" in routing_agent_module.ROUTING_INSTRUCTION
