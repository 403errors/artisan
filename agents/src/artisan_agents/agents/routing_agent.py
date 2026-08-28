"""Gate 2's orchestrator-routing decision (SYSTEM_DESIGN.md §4 step 1, SPRINT.md Phase 3.1).
Decides which domain-expert persona(s) apply to a sufficiently-specified ticket, and whether they
should be dispatched in parallel or sequentially."""

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import RoutingDecision
from google.adk import Agent

APP_NAME = "artisan-routing"

ROUTING_INSTRUCTION = """You are Artisan's routing orchestrator for Gate 2. You will be given a \
GitHub issue's title and body plus its linked Jira key, for a ticket that has already been judged \
to have sufficient context to implement autonomously. Decide which domain-expert persona(s) are \
relevant: "frontend" (UI, client-side behavior, styling), "backend" (server-side logic, APIs, \
data), "infra-devops" (deployment, CI/CD, infrastructure config).

Most issues need exactly one domain. Only select more than one when the issue clearly spans \
multiple layers (e.g. a new API endpoint plus the UI that calls it). Set parallel=true only when \
the selected domains are independent enough to reason about concurrently without one needing the \
other's output first (e.g. two domains touching disjoint files); set parallel=false when the \
domains would need to be reasoned about in sequence (e.g. one domain's technical summary should \
inform the other's), or when only one domain applies."""

routing_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="routing_agent",
    instruction=ROUTING_INSTRUCTION,
    output_schema=RoutingDecision,
    output_key="routing_decision",
)


def _build_prompt(issue_title: str, issue_body: str, jira_key: str) -> str:
    return f"Jira key: {jira_key}\n\nIssue title: {issue_title}\n\nIssue body:\n{issue_body}"


async def run_routing(*, issue_title: str, issue_body: str, jira_key: str) -> RoutingDecision:
    return await run_structured(
        agent=routing_agent,
        app_name=APP_NAME,
        output_key="routing_decision",
        output_model=RoutingDecision,
        prompt=_build_prompt(issue_title, issue_body, jira_key),
    )
