"""Gate 2's Verification Agent (SYSTEM_DESIGN.md §4 step 4, MILESTONE.md Phase 3.5). Compares an
`ExecutionResult` against the `Plan` and original issue, and emits a `VerificationVerdict`."""

from artisan_shared.models import ExecutionResult, Plan, VerificationVerdict
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted
from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_agents.event_context import current_sink

APP_NAME = "artisan-verification"

VERIFICATION_INSTRUCTION = """You are Artisan's Verification Agent. You will be given the original \
GitHub issue, the Plan that was supposed to address it, and a summary of what the execution \
attempt actually did (a diff summary). Judge whether the actual change matches the plan's intent \
and would plausibly resolve the issue. Set green=true only if you're confident the change matches \
the plan and addresses the issue; otherwise set green=false and give specific, actionable feedback \
describing what's missing or wrong — feedback a planning agent could act on for a revised attempt.

When a "Review criteria" section is present, you must also judge the executed change against \
each listed criterion (v2 wave 1.5 #17): emit exactly one `criteria_results` entry per \
criterion, in order — status "met" or "not_met" when the criterion applies to this change, \
"not_applicable" when it doesn't (e.g. a responsive-layout criterion for a pure API change), \
and always with concrete `evidence` naming what in the diff summary grounds your judgment. \
These per-criterion results are recorded for review; your overall `green` verdict remains a \
holistic judgment of plan-match and issue-resolution, not a mechanical count of criteria."""

VERIFICATION_INSTRUCTION = VERIFICATION_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

verification_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="verification_agent",
    instruction=VERIFICATION_INSTRUCTION,
    output_schema=VerificationVerdict,
    output_key="verification_verdict",
)


def _build_prompt(
    plan: Plan,
    execution_result: ExecutionResult,
    issue_title: str,
    issue_body: str,
    review_criteria: list[str] | None = None,
) -> str:
    # Issue title/body are attacker-controllable — wrap them like every other reasoning prompt
    # (this one was missed alongside routing's; fixed with #17's prompt edit).
    prompt = (
        f"Issue title: {wrap_untrusted(issue_title)}\n\nIssue body:\n{wrap_untrusted(issue_body)}\n\n"
        f"Plan steps: {plan.steps}\n\n"
        f"Execution diff summary:\n{execution_result.diff_summary}"
    )
    if review_criteria:
        criteria = "\n".join(f"- {criterion}" for criterion in review_criteria)
        prompt += f"\n\nReview criteria the change is expected to satisfy (judge each):\n{criteria}"
    return prompt


async def run_verification(
    *,
    plan: Plan,
    execution_result: ExecutionResult,
    issue_title: str,
    issue_body: str,
    review_criteria: list[str] | None = None,
) -> VerificationVerdict:
    if not execution_result.tests_passed:
        # A red test run can never be verified green regardless of what the model says — never
        # spend a Gemini call asking it to second-guess a fact already known from the test run
        # (MILESTONE.md Phase 3.5: "Not green, or green-but-tests-failed" are both failure paths).
        verdict = VerificationVerdict(
            green=False,
            feedback=f"The full test suite failed on this attempt. Logs: {execution_result.logs_uri}",
        )
        # This path never calls run_structured, so it needs its own agent_completed emit — a
        # skipped-but-recorded verification, not an invisible gap in the trail.
        await current_sink().child(actor="verification_agent").emit(
            type="agent_completed",
            summary="verification_agent skipped — tests already failed",
            detail=verdict.model_dump_json(),
        )
        return verdict

    return await run_structured(
        agent=verification_agent,
        app_name=APP_NAME,
        output_key="verification_verdict",
        output_model=VerificationVerdict,
        prompt=_build_prompt(plan, execution_result, issue_title, issue_body, review_criteria),
    )
