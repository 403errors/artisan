"""Gate 2's Domain-Expert Agent (SYSTEM_DESIGN.md §4 step 1-2, MILESTONE.md Phase 3.2). A single
parameterized `Agent` instance shared across all personas — the persona is injected into the
prompt, not the schema/instruction, since every persona shares identical output shape and
reasoning task (summarize + list relevant files through one lens). This keeps `backend`/
`infra-devops` (and now any other domain the routing agent names — WS4's domain generalization)
true extensible entries in `_PERSONA_LENS` (a prompt-content change, not a new agent registration)
per the "extensible, not exhaustive" scope note in docs/SPRINT.md's risk register — `_DEFAULT_LENS`
is the generic fallback for a domain that hasn't earned a bespoke entry yet."""

from google.adk import Agent

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import DomainExpertOutput, RepoContext
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted

APP_NAME = "artisan-domain-expert"

_DEFAULT_LENS = (
    "You are reasoning as a {domain} specialist, applying general software engineering "
    "judgment to the relevant part of the codebase revealed by the repo context below."
)

_PERSONA_LENS = {
    "frontend": (
        "You are reasoning as a frontend specialist: UI components, client-side state, styling, "
        "accessibility, and the user-facing behavior described in the issue."
    ),
    "backend": (
        "You are reasoning as a backend specialist: API contract shape and versioning, request "
        "validation, error-handling and status-code conventions, and data-layer transaction/"
        "idempotency concerns implied by the issue."
    ),
    "infra-devops": (
        "You are reasoning as an infra/devops specialist: deployment topology and rollout/rollback "
        "safety, configuration and secrets handling, CI pipeline shape and gating, and observability "
        "hooks implied by the issue."
    ),
}

DOMAIN_EXPERT_INSTRUCTION = """You are one of Artisan's Domain-Expert agents. You will be told \
which persona to reason as, plus a GitHub issue's title and body. Produce a technical summary of \
what needs to change from that persona's lens, and a best-effort list of relevant file paths (or \
directories/patterns if exact paths aren't knowable from the issue alone) that a human reviewer \
would find reasonable as a starting point — never fabricate a suspiciously precise path you have \
no basis for; a plausible directory or pattern is fine when a specific file isn't inferable."""

DOMAIN_EXPERT_INSTRUCTION = DOMAIN_EXPERT_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

domain_expert_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="domain_expert_agent",
    instruction=DOMAIN_EXPERT_INSTRUCTION,
    output_schema=DomainExpertOutput,
    output_key="domain_expert_output",
)


def _repo_context_summary(repo_context: RepoContext) -> str:
    top_languages = sorted(repo_context.languages.items(), key=lambda kv: kv[1], reverse=True)[:5]
    languages_str = ", ".join(f"{ext} ({count})" for ext, count in top_languages) or "(none detected)"
    manifests_str = ", ".join(repo_context.manifests.keys()) or "(none detected)"
    return (
        f"\n\nRepo context — top languages by file count: {languages_str}. "
        f"Manifest files found: {manifests_str}."
    )


def _build_prompt(
    domain: str,
    issue_title: str,
    issue_body: str,
    repo_context: RepoContext | None = None,
) -> str:
    lens = _PERSONA_LENS.get(domain, _DEFAULT_LENS).format(domain=domain)
    prompt = (
        f"{lens}\n\nIssue title: {wrap_untrusted(issue_title)}\n\n"
        f"Issue body:\n{wrap_untrusted(issue_body)}"
    )
    if repo_context is not None:
        prompt += _repo_context_summary(repo_context)
    return prompt


async def run_domain_expert(
    *,
    domain: str,
    issue_title: str,
    issue_body: str,
    repo_context: RepoContext | None = None,
) -> DomainExpertOutput:
    return await run_structured(
        agent=domain_expert_agent,
        app_name=APP_NAME,
        output_key="domain_expert_output",
        output_model=DomainExpertOutput,
        prompt=_build_prompt(domain, issue_title, issue_body, repo_context),
    )
