"""Gate 2's Planning Agent (SYSTEM_DESIGN.md §4 step 2, MILESTONE.md Phase 3.3). Consumes one or more
`DomainExpertOutput`s (plus, on a retry, the prior attempt's verification feedback) and emits a
`Plan`."""

from artisan_shared.models import DomainExpertOutput, Plan, RepoContext
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted
from google.adk import Agent
from google.genai import types

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID

APP_NAME = "artisan-planning"

PLANNING_INSTRUCTION = """You are Artisan's Planning Agent. You will be given one or more \
domain-expert technical summaries (each already scoped to a specific persona/lens) for a single \
GitHub issue, and sometimes feedback from a prior failed attempt. Produce a concrete `Plan`: an \
ordered list of implementation steps, the files you expect to touch, the test cases that should \
be written or updated to cover the change, any documentation that should be updated to reflect it \
(e.g. README, other docs describing the changed behavior), and any code that this change makes \
stale.

Design philosophy: every plan, regardless of which domain(s) it touches, must include non-empty \
test_cases and non-empty doc_updates — never leave these empty just because the issue itself \
didn't mention tests or docs explicitly. If you are given prior-attempt feedback, address it \
explicitly in the revised plan rather than repeating the same approach.

Grounding: when real repo context (a file tree and/or manifest contents) is provided below, every \
entry in `touched_files` and every `removed_code` item's `file` must be a real path drawn from \
that repo context — never a guessed or fabricated path. Prefer extending an existing module or \
file that the repo context reveals as the natural home for the change over defaulting to a new \
file, unless a new file is genuinely the more modular, sustainable choice. When no repo context is \
given, use your best judgment from the issue and domain-expert summaries alone.

Dead code: when the new requirement makes an existing function, branch, or exported symbol stale \
or fully superseded, identify it explicitly — real file path, symbol name, and a one-line reason \
— and add it to `removed_code`. A later coding stage will delete it as part of this same change. \
Leave `removed_code` empty when nothing is actually superseded; don't invent removals to fill it."""

PLANNING_INSTRUCTION = PLANNING_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

# Sprint 7 WS5: the Planning Agent is the only stage in the pipeline given a high thinking budget
# — it's the step that turns loose domain-expert summaries into a concrete, groundable plan
# (touched files, removed code, test/doc coverage), which benefits from deliberate reasoning far
# more than routing/domain-expert/verification's comparatively narrow judgment calls. The installed
# google-genai==2.20.0 `ThinkingConfig` exposes both a numeric `thinking_budget` (token count) and
# a `thinking_level` enum (MINIMAL/LOW/MEDIUM/HIGH) for Gemini 3-family models — `GEMINI_MODEL_ID`
# ("gemini-3.8-flash") is one, so we use the coarser, forward-compatible `thinking_level="HIGH"`
# (the top tier the installed API defines) rather than guessing a numeric budget that may not match
# this model's actual allowed range.
_PLANNING_GENERATE_CONTENT_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
)

planning_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="planning_agent",
    instruction=PLANNING_INSTRUCTION,
    output_schema=Plan,
    output_key="plan",
    generate_content_config=_PLANNING_GENERATE_CONTENT_CONFIG,
)

_RETRY_NUDGE = (
    "\n\nYour previous plan had empty test_cases or doc_updates. Every plan needs both, "
    "regardless of domain. Revise it: include specific, non-empty test_cases and doc_updates."
)


def _repo_context_summary(repo_context: RepoContext) -> str:
    # Cap the file tree sample so the prompt stays bounded on large repos, while still giving the
    # model enough real paths to ground `touched_files`/`removed_code` in.
    file_sample = repo_context.file_tree[:200]
    files_str = "\n".join(f"- {f}" for f in file_sample) or "(none given)"
    truncated_note = (
        f"\n... ({len(repo_context.file_tree) - len(file_sample)} more files not shown)"
        if len(repo_context.file_tree) > len(file_sample)
        else ""
    )
    manifests_str = (
        "\n".join(
            f"- {path}:\n{content[:500]}" for path, content in repo_context.manifests.items()
        )
        or "(none given)"
    )
    return (
        f"\n\nRepo context (repo={repo_context.repo}, head_sha={repo_context.head_sha}):\n"
        f"File tree (sample):\n{files_str}{truncated_note}\n\n"
        f"Manifests:\n{manifests_str}"
    )


def _build_prompt(
    domain_outputs: list[DomainExpertOutput],
    issue_title: str,
    issue_body: str,
    prior_feedback: str | None,
    repo_context: RepoContext | None = None,
) -> str:
    summaries = "\n---\n".join(
        f"[{o.domain}] {o.technical_summary}\nRelevant files: {', '.join(o.relevant_files) or '(none given)'}"
        for o in domain_outputs
    )
    prompt = (
        f"Issue title: {wrap_untrusted(issue_title)}\n\n"
        f"Issue body:\n{wrap_untrusted(issue_body)}\n\n"
        f"Domain-expert summaries:\n{summaries}"
    )
    if repo_context is not None:
        prompt += _repo_context_summary(repo_context)
    if prior_feedback:
        prompt += (
            f"\n\nPRIOR ATTEMPT FEEDBACK (address this explicitly):\n{wrap_untrusted(prior_feedback)}"
        )
    return prompt


async def run_planning(
    *,
    domain_outputs: list[DomainExpertOutput],
    issue_title: str,
    issue_body: str,
    prior_feedback: str | None = None,
    repo_context: RepoContext | None = None,
) -> Plan:
    prompt = _build_prompt(domain_outputs, issue_title, issue_body, prior_feedback, repo_context)
    plan = await run_structured(
        agent=planning_agent,
        app_name=APP_NAME,
        output_key="plan",
        output_model=Plan,
        prompt=prompt,
    )

    if not (plan.test_cases and plan.doc_updates):
        plan = await run_structured(
            agent=planning_agent,
            app_name=APP_NAME,
            output_key="plan",
            output_model=Plan,
            prompt=prompt + _RETRY_NUDGE,
        )
    return plan
