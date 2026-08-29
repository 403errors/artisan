"""Gate 3's conflict classification (SYSTEM_DESIGN.md §5 step 2, MILESTONE.md Phase 4.2). Classifies
a real trial-merge conflict (from `cloud_run_jobs.trigger_conflict_detection`) as `trivial`
(non-overlapping/mechanically reconcilable, safe to auto-resolve) or `semantic` (both sides changed
the same logic differently — never guess, escalate with a structured comparison instead)."""

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import ConflictDetectionResult, ConflictVerdict
from google.adk import Agent

APP_NAME = "artisan-conflict"

CONFLICT_INSTRUCTION = """You are Artisan's Conflict Agent for Gate 3. A conflicting PR ("side A") \
is being merged against its base branch. You'll be given side A's title/body (its stated intent), \
the base branch's recent history for the conflicted files (side B's intent — whatever already \
landed there), and the literal git conflict markers from a real trial merge. Classify:

- "trivial": the conflict is superficial — non-overlapping regions, a mechanical rename, or \
independent nearby changes that don't actually collide in intent. Both sides' changes can be kept.
- "semantic": both sides changed the same logic differently, in a way that requires a judgment \
call about which behavior is correct. Never guess.

If "semantic", set `comparison` to a structured writeup with two clearly separated sections \
("Side A intent: ..." and "Side B intent: ..."), never a raw diff dump."""

conflict_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="conflict_agent",
    instruction=CONFLICT_INSTRUCTION,
    output_schema=ConflictVerdict,
    output_key="conflict_verdict",
)


def _build_prompt(pr_title: str, pr_body: str, detection: ConflictDetectionResult) -> str:
    return (
        f"Side A (this PR) title: {pr_title}\n\n"
        f"Side A (this PR) body:\n{pr_body}\n\n"
        f"Side B (base branch) recent history for the conflicted files:\n{detection.base_branch_history}\n\n"
        f"Conflicted files: {', '.join(detection.conflicted_files)}\n\n"
        f"Conflict markers:\n{detection.conflict_markers}"
    )


async def run_conflict_classification(
    *, pr_title: str, pr_body: str, detection: ConflictDetectionResult
) -> ConflictVerdict:
    return await run_structured(
        agent=conflict_agent,
        app_name=APP_NAME,
        output_key="conflict_verdict",
        output_model=ConflictVerdict,
        prompt=_build_prompt(pr_title, pr_body, detection),
    )
