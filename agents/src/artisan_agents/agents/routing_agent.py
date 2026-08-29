"""Gate 2's orchestrator-routing decision (SYSTEM_DESIGN.md §4 step 1, MILESTONE.md Phase 3.1).
Decides which domain-expert persona(s) apply to a sufficiently-specified ticket, and whether they
should be dispatched in parallel or sequentially."""

from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import RepoContext, RoutingDecision
from google.adk import Agent

APP_NAME = "artisan-routing"

ROUTING_INSTRUCTION = """You are Artisan's routing orchestrator for Gate 2. You will be given a \
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

Most issues need exactly one domain. Only select more than one when the issue clearly spans \
multiple layers (e.g. a new API endpoint plus the UI that calls it). Set parallel=true only when \
the selected domains are independent enough to reason about concurrently without one needing the \
other's output first (e.g. two domains touching disjoint files); set parallel=false when the \
domains would need to be reasoned about in sequence (e.g. one domain's technical summary should \
inform the other's), or when only one domain applies.

When the repo context's manifests span multiple directories at different depths (a monorepo \
signal — e.g. both `apps/web/package.json` and `services/api/pyproject.toml` are present), set \
`subproject` to whichever subdirectory the issue is most likely about. Otherwise leave \
`subproject` as null."""

routing_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="routing_agent",
    instruction=ROUTING_INSTRUCTION,
    output_schema=RoutingDecision,
    output_key="routing_decision",
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
    issue_title: str,
    issue_body: str,
    jira_key: str,
    repo_context: RepoContext | None = None,
) -> str:
    prompt = f"Jira key: {jira_key}\n\nIssue title: {issue_title}\n\nIssue body:\n{issue_body}"
    if repo_context is not None:
        prompt += _repo_context_summary(repo_context)
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
