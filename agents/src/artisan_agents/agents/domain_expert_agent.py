"""Gate 2's Domain-Expert Agent (SYSTEM_DESIGN.md §4 step 1-2, SPRINT.md Phase 3.2). A single
parameterized `Agent` instance shared across all three personas — the persona is injected into the
prompt, not the schema/instruction, since all three personas share identical output shape and
reasoning task (summarize + list relevant files through one lens). This keeps `backend`/
`infra-devops` true extensible stubs (a prompt-content change later, not a new agent
registration) per the "extensible, not exhaustive" scope note in docs/SPRINT.md's risk register —
only `frontend` has a fully fleshed-out lens for this sprint's demo scope."""

from typing import Literal

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import DomainExpertOutput

APP_NAME = "artisan-domain-expert"

_PERSONA_LENS = {
    "frontend": (
        "You are reasoning as a frontend specialist: UI components, client-side state, styling, "
        "accessibility, and the user-facing behavior described in the issue."
    ),
    "backend": (
        "You are reasoning as a backend specialist: server-side logic, API contracts, data "
        "handling, and business rules implied by the issue."
    ),
    "infra-devops": (
        "You are reasoning as an infra/devops specialist: deployment configuration, CI/CD, "
        "environment/build setup implied by the issue."
    ),
}

DOMAIN_EXPERT_INSTRUCTION = """You are one of Artisan's Domain-Expert agents. You will be told \
which persona to reason as, plus a GitHub issue's title and body. Produce a technical summary of \
what needs to change from that persona's lens, and a best-effort list of relevant file paths (or \
directories/patterns if exact paths aren't knowable from the issue alone) that a human reviewer \
would find reasonable as a starting point — never fabricate a suspiciously precise path you have \
no basis for; a plausible directory or pattern is fine when a specific file isn't inferable."""

domain_expert_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="domain_expert_agent",
    instruction=DOMAIN_EXPERT_INSTRUCTION,
    output_schema=DomainExpertOutput,
    output_key="domain_expert_output",
)


def _build_prompt(domain: str, issue_title: str, issue_body: str) -> str:
    lens = _PERSONA_LENS[domain]
    return f"{lens}\n\nIssue title: {issue_title}\n\nIssue body:\n{issue_body}"


async def run_domain_expert(
    *, domain: Literal["frontend", "backend", "infra-devops"], issue_title: str, issue_body: str
) -> DomainExpertOutput:
    return await run_structured(
        agent=domain_expert_agent,
        app_name=APP_NAME,
        output_key="domain_expert_output",
        output_model=DomainExpertOutput,
        prompt=_build_prompt(domain, issue_title, issue_body),
    )
