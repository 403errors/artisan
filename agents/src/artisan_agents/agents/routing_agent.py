"""Gate 2's orchestrator-routing decision (SYSTEM_DESIGN.md §4 step 1, MILESTONE.md Phase 3.1).
Decides which domain-expert persona(s) apply to a sufficiently-specified ticket, and whether they
should be dispatched in parallel or sequentially."""

from artisan_shared.models import RepoContext, RoutingDecision
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted
from google.adk import Agent
from google.genai import types

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.agents.domain_expert_agent import PERSONA_DOMAINS
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_agents.repo_context_summary import repo_context_summary

APP_NAME = "artisan-routing"

_BESPOKE_DOMAINS_STR = '", "'.join(PERSONA_DOMAINS)

ROUTING_INSTRUCTION = f"""You are Artisan's routing orchestrator for Gate 2. You will be given a \
GitHub issue's title and body plus its linked Jira key, for a ticket that has already been judged \
to have sufficient context to implement autonomously. Decide which domain-expert persona(s) are \
relevant.

Derive each domain name from the issue text and, when given, the repo context summary (a \
languages histogram and manifest file paths). For a typical web-shaped repo, "frontend" (UI, \
client-side behavior, styling), "backend" (server-side logic, APIs, data), and "infra-devops" \
(deployment, CI/CD, infrastructure config) remain the most common answers — use them by default. \
But when the repo context clearly indicates a different shape, name a more fitting domain instead \
(e.g. "mobile" for a repo with a `pubspec.yaml` or iOS/Android project files, "data-ml" for a \
repo dominated by notebooks/data-science manifests, "cli" for a `Cargo.toml` or `requirements.txt` \
project with no web framework in sight, "game" for a game-engine project, etc.) — don't force a \
web-shaped label onto a repo that isn't one.

These domains have bespoke expert lenses with real review criteria — prefer them, spelled \
exactly as shown, whenever one fits: "{_BESPOKE_DOMAINS_STR}". You may still name a different \
domain when the repo clearly calls for it (a generic fallback lens covers it), but never invent \
a near-duplicate of a bespoke domain (e.g. "web-frontend" when "frontend" fits) — a variant \
spelling silently routes to the shallower fallback lens. And the reverse failure is just as bad: \
if the repo's shape matches NONE of the bespoke domains (e.g. a mainframe/COBOL codebase, a \
blockchain/smart-contract project, a scientific-computing codebase), name a fitting domain \
outside the list instead of forcing the closest bespoke one — a wrong bespoke lens plans with \
irrelevant review criteria, which is worse than the honest generic fallback.

Most issues need exactly one domain. Only select more than one when the issue clearly spans \
multiple layers (e.g. a new API endpoint plus the UI that calls it). Set parallel=true only when \
the selected domains are independent enough to reason about concurrently without one needing the \
other's output first (e.g. two domains touching disjoint files); set parallel=false when the \
domains would need to be reasoned about in sequence (e.g. one domain's technical summary should \
inform the other's), or when only one domain applies.

When the repo context's manifests span multiple directories at different depths (a monorepo \
signal — e.g. both `apps/web/package.json` and `services/api/pyproject.toml` are present), set \
`subproject` to whichever subdirectory the issue is most likely about. Otherwise leave \
`subproject` as null.

Finally, make the decision auditable: set `rationale` to one or two sentences explaining why \
these domains fit this issue and repo, and `confidence` to "high", "medium", or "low" — "low" \
means the issue text and repo signal didn't clearly indicate any domain and your answer is \
largely a guess. An honest "low" is more useful than a confident-sounding guess: it is recorded \
on the ticket for human review."""

ROUTING_INSTRUCTION = ROUTING_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

# v2 wave 1.5 (#13): pin temperature=0 — routing is a classification-style decision, and
# low-temperature sampling keeps it reproducible across identical inputs (cross-run stability is
# measured for real by the eval harness in agents/evals/, not assumed from this pin).
_ROUTING_GENERATE_CONTENT_CONFIG = types.GenerateContentConfig(temperature=0)

routing_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="routing_agent",
    instruction=ROUTING_INSTRUCTION,
    output_schema=RoutingDecision,
    output_key="routing_decision",
    generate_content_config=_ROUTING_GENERATE_CONTENT_CONFIG,
)


def _build_prompt(
    issue_title: str,
    issue_body: str,
    jira_key: str,
    repo_context: RepoContext | None = None,
) -> str:
    # Issue title/body are attacker-controllable (anyone can open a GitHub issue) — wrap them the
    # same way intake/domain-expert/planning prompts do (Sprint 7 WS2); routing was the one
    # reasoning prompt missed by that hardening pass (v2 wave 1.5 #12).
    prompt = (
        f"Jira key: {jira_key}\n\nIssue title: {wrap_untrusted(issue_title)}\n\n"
        f"Issue body:\n{wrap_untrusted(issue_body)}"
    )
    if repo_context is not None:
        prompt += repo_context_summary(repo_context)
    return prompt


async def run_routing(
    *,
    issue_title: str,
    issue_body: str,
    jira_key: str,
    repo_context: RepoContext | None = None,
) -> RoutingDecision:
    return await run_structured(
        agent=routing_agent,
        app_name=APP_NAME,
        output_key="routing_decision",
        output_model=RoutingDecision,
        prompt=_build_prompt(issue_title, issue_body, jira_key, repo_context),
    )
