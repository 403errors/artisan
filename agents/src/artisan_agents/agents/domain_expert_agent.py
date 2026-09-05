"""Gate 2's Domain-Expert Agent (SYSTEM_DESIGN.md §4 step 1-2, MILESTONE.md Phase 3.2). A single
parameterized `Agent` instance shared across all personas — the persona is injected into the
prompt, not the schema/instruction, since every persona shares identical output shape and
reasoning task (summarize + list relevant files through one lens). This keeps every domain the
routing agent names (WS4's domain generalization) a true extensible entry in `_PERSONA_LENSES`
(a prompt-content change, not a new agent registration) per the "extensible, not exhaustive"
scope note in docs/SPRINT.md's risk register — `_DEFAULT_LENS` is the generic fallback for a
domain that hasn't earned a bespoke entry yet.

v2 wave 1 (#2): lenses are structured `PersonaLens` specs — a `focus` plus concrete
`review_criteria` — rather than one-line labels, so a correctly-routed non-web repo (mobile,
data/ML, CLI, embedded, game, security, database) gets planned with genuine expert depth. A
structural test guards the "real review criteria, not a label" contract, so a shallow entry
can't pass CI."""

import json
from dataclasses import dataclass

from artisan_shared.models import DomainExpertOutput, RepoContext
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted
from google.adk import Agent

from artisan_agents import event_context
from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_agents.repo_context_summary import repo_context_summary

APP_NAME = "artisan-domain-expert"


@dataclass(frozen=True)
class PersonaLens:
    """One domain-expert persona's review depth. `focus` names what the specialist reasons
    about; `review_criteria` are the concrete checks a good change in this domain must satisfy —
    the difference between an expert lens and a bare label. Keep criteria specific enough that a
    plan could be reviewed against them."""

    focus: str
    review_criteria: tuple[str, ...]


_DEFAULT_LENS = (
    "You are reasoning as a {domain} specialist, applying general software engineering "
    "judgment to the relevant part of the codebase revealed by the repo context below."
)

_PERSONA_LENSES: dict[str, PersonaLens] = {
    "frontend": PersonaLens(
        focus=(
            "You are reasoning as a frontend specialist: UI components, client-side state, "
            "styling, accessibility, and the user-facing behavior described in the issue."
        ),
        review_criteria=(
            ("Component boundaries and state ownership stay consistent with the app's existing "
            "patterns — no new global state for a local concern."),
            ("Accessibility is preserved or improved where the change touches interaction: "
            "semantic elements, keyboard operability, focus management, ARIA/contrast."),
            "Loading, empty, and error states are accounted for, not just the happy path.",
            "Responsive/layout behavior does not regress at the viewport sizes the app supports.",
            "User-facing behavior and copy match what the issue actually describes.",
        ),
    ),
    "backend": PersonaLens(
        focus=(
            "You are reasoning as a backend specialist: API contract shape and versioning, "
            "request validation, error-handling and status-code conventions, and data-layer "
            "transaction/idempotency concerns implied by the issue."
        ),
        review_criteria=(
            ("API contract changes are backward-compatible or explicitly versioned; request/"
            "response shapes are validated at the boundary."),
            ("Error handling follows the service's status-code and error-body conventions; "
            "failures don't leak internals."),
            ("Writes are idempotent or transactional wherever retries or concurrent requests are "
            "possible."),
            "Authentication/authorization checks apply to every new or changed endpoint.",
            "Data access avoids obvious N+1 or unbounded-query patterns.",
        ),
    ),
    "infra-devops": PersonaLens(
        focus=(
            "You are reasoning as an infra/devops specialist: deployment topology and rollout/"
            "rollback safety, configuration and secrets handling, CI pipeline shape and gating, "
            "and observability hooks implied by the issue."
        ),
        review_criteria=(
            "Rollout is reversible: the change can be rolled back without manual data surgery.",
            "No secrets or credentials inline; configuration is environment-driven.",
            ("CI gating still reflects the real verification steps — build/test/deploy order is "
            "preserved."),
            "New failure modes emit logs/metrics/traces that existing observability can see.",
            "Resource and permission changes are least-privilege.",
        ),
    ),
    "mobile": PersonaLens(
        focus=(
            "You are reasoning as a mobile specialist: app lifecycle, platform conventions "
            "(iOS/Android/cross-platform frameworks), offline and connectivity behavior, and "
            "device constraints implied by the issue."
        ),
        review_criteria=(
            ("Lifecycle correctness: state survives backgrounding, rotation, and process death "
            "where relevant."),
            ("Platform conventions are respected — navigation patterns, permission prompts, "
            "store guidelines."),
            ("Network calls handle offline/slow connections with sensible retry and caching "
            "behavior."),
            ("Battery, memory, and performance impact is considered for long-running or polling "
            "work."),
            ("Layout adapts across screen sizes and densities (safe areas, tablets where "
            "supported)."),
        ),
    ),
    "data-ml": PersonaLens(
        focus=(
            "You are reasoning as a data/ML specialist: data pipelines, feature handling, model "
            "training/evaluation, and the reproducibility of data-driven behavior implied by "
            "the issue."
        ),
        review_criteria=(
            ("No train/serve skew or leakage: feature logic is shared or identical between "
            "training and inference paths."),
            "Schema changes are versioned and backward-compatible for downstream consumers.",
            "Evaluation covers the metric the issue cares about, not just aggregate accuracy.",
            ("Pipelines are idempotent and re-runnable; partial failures don't silently corrupt "
            "outputs."),
            "Seeds, dependency versions, and data snapshots make results reproducible.",
        ),
    ),
    "cli": PersonaLens(
        focus=(
            "You are reasoning as a CLI specialist: argument parsing and command surface, exit "
            "codes, the stdout/stderr contract, and scriptability of the tool implied by the "
            "issue."
        ),
        review_criteria=(
            ("Exit codes are meaningful and consistent (0 on success, distinct non-zero failure "
            "classes)."),
            "Machine-readable output goes to stdout; diagnostics and progress go to stderr.",
            "Flag / env-var / config-file precedence stays predictable and documented.",
            "The command surface stays backward-compatible, or has an explicit deprecation path.",
            "Behavior is script-friendly: no unexpected interactive prompts on automated paths.",
        ),
    ),
    "embedded": PersonaLens(
        focus=(
            "You are reasoning as an embedded specialist: resource-constrained targets, "
            "real-time constraints, hardware abstraction, and firmware update/flash safety "
            "implied by the issue."
        ),
        review_criteria=(
            "Memory footprint stays within target constraints — no unbounded heap allocation.",
            ("Timing/real-time guarantees are preserved; no blocking calls in interrupt or hot "
            "paths."),
            ("Hardware access goes through the project's HAL/abstraction layer, not raw "
            "registers in new code."),
            ("Failure modes are safe: watchdog, brown-out, and corrupt-state recovery are "
            "considered."),
            ("Firmware update paths can't brick the device (atomicity/rollback where "
            "applicable)."),
        ),
    ),
    "game": PersonaLens(
        focus=(
            "You are reasoning as a game specialist: frame-loop architecture, entity/state "
            "management, asset pipelines, and input/physics behavior implied by the issue."
        ),
        review_criteria=(
            "Per-frame work stays within budget — no per-frame allocations in hot loops.",
            ("Game-state transitions are deterministic and don't leak state between scenes or "
            "sessions."),
            "Input handling covers the platforms and control schemes the project supports.",
            "Assets load/unload through the existing pipeline — no hardcoded absolute paths.",
            ("Physics/timing uses fixed timesteps or delta-time correctly, not wall-clock "
            "assumptions."),
        ),
    ),
    "security": PersonaLens(
        focus=(
            "You are reasoning as a security specialist: trust boundaries, input handling, "
            "authentication/authorization, and secret/credential hygiene implied by the issue."
        ),
        review_criteria=(
            ("All external input is validated/sanitized at the trust boundary (injection, path "
            "traversal, SSRF classes as applicable)."),
            ("Authorization checks happen server-side on every privileged operation, not just "
            "in the UI."),
            "Secrets never appear in code, logs, or error messages.",
            "Crypto uses vetted library primitives, never hand-rolled constructions.",
            ("The change doesn't widen the attack surface (new endpoints, permissions, parsers "
            "of untrusted data) without a stated reason."),
        ),
    ),
    "database": PersonaLens(
        focus=(
            "You are reasoning as a database specialist: schema design and migrations, query "
            "behavior, indexing, and data integrity implied by the issue."
        ),
        review_criteria=(
            ("Migrations are reversible and safe on populated tables — no long locks or table "
            "rewrites without a plan."),
            ("Indexes support the new query patterns; no full-table scans introduced on hot "
            "paths."),
            ("Constraints (uniqueness, foreign keys, nullability) enforce the integrity the "
            "issue assumes."),
            "Data-backfill semantics are explicit: what happens to existing rows.",
            "Query changes are checked for N+1 and pagination behavior.",
        ),
    ),
}

# Domains with bespoke lenses, in registry order. The routing agent's instruction names these so
# routing prefers them when they fit; any other domain still works via `_DEFAULT_LENS`.
PERSONA_DOMAINS: tuple[str, ...] = tuple(_PERSONA_LENSES)

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


def _lens_for(domain: str) -> PersonaLens | None:
    # Normalize so model-casing/whitespace drift in the routing output ("Mobile", " mobile ")
    # still hits the bespoke lens instead of silently falling back to the generic one.
    return _PERSONA_LENSES.get(domain.strip().lower())


def _render_lens(domain: str) -> str:
    lens = _lens_for(domain)
    if lens is None:
        return _DEFAULT_LENS.format(domain=domain)
    criteria = "\n".join(f"- {criterion}" for criterion in lens.review_criteria)
    return f"{lens.focus}\n\nReview criteria a good {domain} change must satisfy:\n{criteria}"


def criteria_for_domains(domains: list[str]) -> list[str]:
    """Flat, domain-prefixed list of the review criteria for the bespoke lenses among `domains`
    (v2 wave 1.5 #17) — the verification agent judges the executed change against each. Domains
    served by the generic fallback lens contribute nothing: there are no bespoke criteria to
    verify for them."""
    criteria: list[str] = []
    for domain in domains:
        lens = _lens_for(domain)
        if lens is not None:
            normalized = domain.strip().lower()
            criteria.extend(f"[{normalized}] {criterion}" for criterion in lens.review_criteria)
    return criteria


# Prompt-side total budget for the conventions section — fetch-side caps (5 docs x 8k chars)
# bound the worst case, but the section gets its own ceiling so a prompt stays focused.
_MAX_CONVENTIONS_SECTION_CHARS = 12000


def _conventions_section(repo_context: RepoContext) -> str:
    """The repo's own conventions, wrapped as untrusted (v2 wave 1.5 #18) — appended only for
    bespoke lenses, whose review criteria are judged against these rules rather than generic
    practice alone."""
    docs = repo_context.convention_docs
    if not docs:
        return ""
    rendered: list[str] = []
    remaining = _MAX_CONVENTIONS_SECTION_CHARS
    for path in sorted(docs):
        if remaining <= 0:
            break
        excerpt = docs[path][:remaining]
        remaining -= len(excerpt)
        rendered.append(f"--- {path} ---\n{wrap_untrusted(excerpt)}")
    return (
        "\n\nRepo conventions (judge the change against these where they apply):\n"
        + "\n\n".join(rendered)
    )


def _build_prompt(
    domain: str,
    issue_title: str,
    issue_body: str,
    repo_context: RepoContext | None = None,
) -> str:
    prompt = (
        f"{_render_lens(domain)}\n\nIssue title: {wrap_untrusted(issue_title)}\n\n"
        f"Issue body:\n{wrap_untrusted(issue_body)}"
    )
    if repo_context is not None:
        prompt += repo_context_summary(repo_context)
        if _lens_for(domain) is not None:
            prompt += _conventions_section(repo_context)
    return prompt


async def run_domain_expert(
    *,
    domain: str,
    issue_title: str,
    issue_body: str,
    repo_context: RepoContext | None = None,
) -> DomainExpertOutput:
    # v2 wave 1.5 (#14): record which lens actually served this dispatch — the fallback rate is
    # the health signal for the whole bespoke-lens investment, and it's only computable if every
    # dispatch logs which side of the registry it hit.
    lens_kind = "bespoke" if _lens_for(domain) is not None else "fallback"
    await event_context.current_sink().child(actor="domain_expert_agent").emit(
        type="domain_lens_used",
        summary=f"domain '{domain.strip().lower()}' served by the {lens_kind} lens",
        detail=json.dumps({"domain": domain, "lens": lens_kind}),
    )
    return await run_structured(
        agent=domain_expert_agent,
        app_name=APP_NAME,
        output_key="domain_expert_output",
        output_model=DomainExpertOutput,
        prompt=_build_prompt(domain, issue_title, issue_body, repo_context),
    )
