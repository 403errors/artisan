"""Gate 2's Verification Agent (SYSTEM_DESIGN.md §4 step 4, SPRINT.md Phase 3.5). Compares an
`ExecutionResult` against the `Plan` and original issue, and emits a `VerificationVerdict`."""

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import ExecutionResult, Plan, VerificationVerdict

APP_NAME = "artisan-verification"

VERIFICATION_INSTRUCTION = """You are Artisan's Verification Agent. You will be given the original \
GitHub issue, the Plan that was supposed to address it, and a summary of what the execution \
attempt actually did (a diff summary). Judge whether the actual change matches the plan's intent \
and would plausibly resolve the issue. Set green=true only if you're confident the change matches \
the plan and addresses the issue; otherwise set green=false and give specific, actionable feedback \
describing what's missing or wrong — feedback a planning agent could act on for a revised attempt."""

verification_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="verification_agent",
    instruction=VERIFICATION_INSTRUCTION,
    output_schema=VerificationVerdict,
    output_key="verification_verdict",
)


def _build_prompt(plan: Plan, execution_result: ExecutionResult, issue_title: str, issue_body: str) -> str:
    return (
        f"Issue title: {issue_title}\n\nIssue body:\n{issue_body}\n\n"
        f"Plan steps: {plan.steps}\n\n"
        f"Execution diff summary:\n{execution_result.diff_summary}"
    )


async def run_verification(
    *, plan: Plan, execution_result: ExecutionResult, issue_title: str, issue_body: str
) -> VerificationVerdict:
    if not execution_result.tests_passed:
        # A red test run can never be verified green regardless of what the model says — never
        # spend a Gemini call asking it to second-guess a fact already known from the test run
        # (SPRINT.md Phase 3.5: "Not green, or green-but-tests-failed" are both failure paths).
        return VerificationVerdict(
            green=False,
            feedback=f"The full test suite failed on this attempt. Logs: {execution_result.logs_uri}",
        )

    return await run_structured(
        agent=verification_agent,
        app_name=APP_NAME,
        output_key="verification_verdict",
        output_model=VerificationVerdict,
        prompt=_build_prompt(plan, execution_result, issue_title, issue_body),
    )
