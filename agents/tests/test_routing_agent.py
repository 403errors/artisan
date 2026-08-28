"""Unit tests for the routing agent's branching (Phase 3.1 DoD): a multi-domain issue should
produce a multi-domain RoutingDecision, a single-domain issue a single-domain one. Stubs the
underlying model — never calls live Gemini."""

import pytest

from artisan_agents.agents import routing_agent as routing_agent_module
from artisan_agents.agents.routing_agent import run_routing
from tests.conftest import FakeLlm


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
