"""Gate 1's Intake Agent (SYSTEM_DESIGN.md §3 step 4). Judges whether a GitHub issue thread has
enough context to automate, returning the typed `IntakeVerdict` — never free text."""

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import IntakeVerdict

APP_NAME = "artisan-intake"

INTAKE_INSTRUCTION = """You are Artisan's Intake Agent. You will be given a GitHub issue's title, \
body, and comment thread, plus its linked Jira key. Decide whether there is enough context for an \
autonomous coding agent to implement a fix or feature with no further human input: a clear \
description of the problem or desired behavior, and (for bugs) reproduction steps or the \
expected-vs-actual behavior.

Design philosophy: decide with confidence, or ask rather than guess. Never assume missing \
details. If context is sufficient, set sufficient=true and leave missing_context_question unset. \
If not, set sufficient=false and missing_context_question to ONE specific, directly answerable \
question that would unblock work — never a generic "please provide more details"."""

intake_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="intake_agent",
    instruction=INTAKE_INSTRUCTION,
    output_schema=IntakeVerdict,
    output_key="intake_verdict",
)


def _build_prompt(
    issue_title: str, issue_body: str, thread: list[str], jira_key: str
) -> str:
    comments = "\n---\n".join(thread) if thread else "(no comments yet)"
    return (
        f"Jira key: {jira_key}\n\n"
        f"Issue title: {issue_title}\n\n"
        f"Issue body:\n{issue_body}\n\n"
        f"Comment thread:\n{comments}"
    )


async def run_intake(
    *, issue_title: str, issue_body: str, thread: list[str], jira_key: str
) -> IntakeVerdict:
    """Runs one stateless evaluation — a fresh session per call, since Firestore (not agent
    memory) is the source of truth (SYSTEM_DESIGN.md §7); the full current thread is always
    passed in explicitly rather than relying on conversation history across invocations.

    Sprint 6: delegates to `run_structured` (previously its own byte-for-byte duplicate of the
    same five-step shape, predating that helper's extraction) so Gate 1's agent invocation gets
    `agent_invoked`/`agent_completed` events like every other reasoning agent, with no separate
    instrumentation needed here."""
    return await run_structured(
        agent=intake_agent,
        app_name=APP_NAME,
        output_key="intake_verdict",
        output_model=IntakeVerdict,
        prompt=_build_prompt(issue_title, issue_body, thread, jira_key),
    )
