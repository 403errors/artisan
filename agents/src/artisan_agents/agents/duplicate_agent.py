"""Gate 1's Duplicate Detector Agent (SYSTEM_DESIGN.md §3). Pre-filters the repo's open issues via
the GitHub Search API, then judges which of the top candidates are TRUE duplicates of the new
issue — returning typed `DuplicateCandidate`s, never free text. Empty candidates = proceed to
normal intake. Mirrors the Intake Agent's stateless shape (fresh session per call; Firestore, not
agent memory, is the source of truth)."""

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID, MAX_DUPLICATE_CANDIDATES
from artisan_agents.github import client as github_client
from artisan_shared.models import DuplicateCandidate, DuplicateSearchHit, DuplicateVerdict
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted

APP_NAME = "artisan-duplicate"

DUPLICATE_INSTRUCTION = """You are Artisan's Duplicate Detector Agent. You will be given a newly \
raised GitHub issue's title and body, plus a list of existing open issues in the same repository \
that a keyword search thought might be related. Decide which — if any — of those existing issues \
are TRUE duplicates of the new issue.

A true duplicate means: it describes the same problem or feature request, with the same expected \
behavior, such that resolving one would resolve the other. A superficial similarity (same area of \
the code, same component, same symptom word) is NOT a duplicate if the underlying request differs. \
The new issue is authoritative: if it asks for anything the existing issues do not already cover, \
it is not a duplicate.

Return a list of the candidate issues you are confident are true duplicates, each with:
- a similarity score from 0.0 (unrelated) to 1.0 (identical request)
- a one-line plain-language reason for why it is a duplicate (this may be shown to the issue \
reporter)

Return an empty list when none of the candidates is a true duplicate. Be conservative — a false \
positive (wrongly flagging a genuinely different issue) is worse than a missed duplicate."""

DUPLICATE_INSTRUCTION = DUPLICATE_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

duplicate_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="duplicate_agent",
    instruction=DUPLICATE_INSTRUCTION,
    output_schema=DuplicateVerdict,
    output_key="duplicate_verdict",
)


def _build_prompt(
    issue_title: str,
    issue_body: str,
    jira_key: str,
    hits: list[DuplicateSearchHit],
) -> str:
    candidates = "\n".join(
        f"- #{hit.issue_number} — {hit.title}\n  {wrap_untrusted(hit.body)}" for hit in hits
    )
    return (
        f"Jira key: {jira_key}\n\n"
        f"New issue title: {wrap_untrusted(issue_title)}\n\n"
        f"New issue body:\n{wrap_untrusted(issue_body)}\n\n"
        f"Existing open issues to check:\n{candidates}"
    )


async def run_duplicate_check(
    *,
    repo: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    jira_key: str,
) -> list[DuplicateCandidate]:
    """Runs one stateless duplicate evaluation (a fresh session per call, like every other
    `run_structured` agent). Returns the candidates judged true duplicates (capped at
    MAX_DUPLICATE_CANDIDATES), or [] when none.

    The Search API pre-filter keeps the LLM call gated: if search returns no keyword candidates,
    this returns [] without spending a model call — the cost bound for the new-per-issue check."""
    hits = await github_client.search_similar_issues(
        repo, issue_title, issue_body, exclude_number=issue_number
    )
    if not hits:
        return []
    verdict = await run_structured(
        agent=duplicate_agent,
        app_name=APP_NAME,
        output_key="duplicate_verdict",
        output_model=DuplicateVerdict,
        prompt=_build_prompt(issue_title, issue_body, jira_key, hits),
    )
    return verdict.candidates[:MAX_DUPLICATE_CANDIDATES]
