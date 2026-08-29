"""Gate 2's Planning Agent (SYSTEM_DESIGN.md §4 step 2, MILESTONE.md Phase 3.3). Consumes one or more
`DomainExpertOutput`s (plus, on a retry, the prior attempt's verification feedback) and emits a
`Plan`."""

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import DomainExpertOutput, Plan

APP_NAME = "artisan-planning"

PLANNING_INSTRUCTION = """You are Artisan's Planning Agent. You will be given one or more \
domain-expert technical summaries (each already scoped to a specific persona/lens) for a single \
GitHub issue, and sometimes feedback from a prior failed attempt. Produce a concrete `Plan`: an \
ordered list of implementation steps, the files you expect to touch, the test cases that should \
be written or updated to cover the change, and any documentation that should be updated to \
reflect it (e.g. README, other docs describing the changed behavior).

Design philosophy: every plan that touches user-facing or documented behavior must include \
non-empty test_cases and non-empty doc_updates — never leave these empty just because the issue \
itself didn't mention tests or docs explicitly. If you are given prior-attempt feedback, address \
it explicitly in the revised plan rather than repeating the same approach."""

planning_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="planning_agent",
    instruction=PLANNING_INSTRUCTION,
    output_schema=Plan,
    output_key="plan",
)

_RETRY_NUDGE = (
    "\n\nYour previous plan had empty test_cases or doc_updates for a change that touches "
    "user-facing behavior. Revise it: include specific, non-empty test_cases and doc_updates."
)


def _build_prompt(
    domain_outputs: list[DomainExpertOutput],
    issue_title: str,
    issue_body: str,
    prior_feedback: str | None,
) -> str:
    summaries = "\n---\n".join(
        f"[{o.domain}] {o.technical_summary}\nRelevant files: {', '.join(o.relevant_files) or '(none given)'}"
        for o in domain_outputs
    )
    prompt = f"Issue title: {issue_title}\n\nIssue body:\n{issue_body}\n\nDomain-expert summaries:\n{summaries}"
    if prior_feedback:
        prompt += f"\n\nPRIOR ATTEMPT FEEDBACK (address this explicitly):\n{prior_feedback}"
    return prompt


async def run_planning(
    *,
    domain_outputs: list[DomainExpertOutput],
    issue_title: str,
    issue_body: str,
    prior_feedback: str | None = None,
) -> Plan:
    prompt = _build_prompt(domain_outputs, issue_title, issue_body, prior_feedback)
    plan = await run_structured(
        agent=planning_agent,
        app_name=APP_NAME,
        output_key="plan",
        output_model=Plan,
        prompt=prompt,
    )

    touches_user_facing = any(o.domain == "frontend" for o in domain_outputs)
    if touches_user_facing and not (plan.test_cases and plan.doc_updates):
        plan = await run_structured(
            agent=planning_agent,
            app_name=APP_NAME,
            output_key="plan",
            output_model=Plan,
            prompt=prompt + _RETRY_NUDGE,
        )
    return plan
