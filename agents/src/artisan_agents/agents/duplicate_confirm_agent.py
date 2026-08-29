"""Gate 1's Duplicate Confirm Agent (SYSTEM_DESIGN.md §3). Classifies the issuer's reply to
Artisan's duplicate-flag comment into a typed `DuplicateConfirmVerdict` — close as duplicate,
proceed (not a duplicate), or ask once more (ambiguous reply). Same stateless `run_structured`
shape as every other reasoning agent."""

from artisan_shared.models import DuplicateCandidate, DuplicateConfirmVerdict
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted
from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID

APP_NAME = "artisan-duplicate-confirm"

DUPLICATE_CONFIRM_INSTRUCTION = """You are Artisan's Duplicate Confirm Agent. Artisan flagged a \
newly raised GitHub issue as a possible duplicate of some existing issues and asked the reporter \
to confirm. You are given: the candidate issues Artisan flagged (with links and reasons), the \
comment Artisan posted, and the reporter's reply. Decide the reporter's intent.

- "confirm_duplicate" — the reply agrees this issue is the same as one of the listed candidates \
(e.g. "yes it's a duplicate", "same as #12", "sorry, I didn't see #34"). Set target_issue_number \
to the candidate they mean; if they don't name one, leave it null (the caller falls back to the \
top candidate).
- "not_duplicate" — the reply says this is a different issue, or explains how it differs from the \
candidates.
- "needs_clarification" — the reply is ambiguous, off-topic, or doesn't answer the question.

Any human comment counts as the reply. Return exactly one intent."""

DUPLICATE_CONFIRM_INSTRUCTION = DUPLICATE_CONFIRM_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

duplicate_confirm_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="duplicate_confirm_agent",
    instruction=DUPLICATE_CONFIRM_INSTRUCTION,
    output_schema=DuplicateConfirmVerdict,
    output_key="duplicate_confirm_verdict",
)


def _build_prompt(
    candidates: list[DuplicateCandidate],
    flag_comment: str,
    reply: str,
) -> str:
    candidates_text = "\n".join(
        f"- #{c.issue_number} — {c.title} ({c.html_url})\n  reason: {c.reason}"
        for c in candidates
    )
    return (
        f"Candidate issues Artisan flagged:\n{candidates_text}\n\n"
        f"Artisan's flag comment:\n{wrap_untrusted(flag_comment)}\n\n"
        f"Reporter's reply:\n{wrap_untrusted(reply)}"
    )


async def run_duplicate_confirm(
    *,
    candidates: list[DuplicateCandidate],
    flag_comment: str,
    reply: str,
) -> DuplicateConfirmVerdict:
    """Classifies one issuer reply against the flagged candidates (stateless, fresh session per
    call). `flag_comment` is the exact text Artisan posted when it flagged the issue — reconstruct
    it with `dispatch.build_duplicate_flag_comment` so the agent sees what was asked."""
    return await run_structured(
        agent=duplicate_confirm_agent,
        app_name=APP_NAME,
        output_key="duplicate_confirm_verdict",
        output_model=DuplicateConfirmVerdict,
        prompt=_build_prompt(candidates, flag_comment, reply),
    )
