"""Typed inter-agent I/O. Per SYSTEM_DESIGN.md §6.2 — no raw string/dict passing between agents.

Shared between `agents/` (orchestrator) and `execution-sandbox/` (Sprint 3's execution job) since
both sides need `Plan`/`ExecutionResult`'s exact shape to stay in sync — see docs/CONTEXT.md's
Sprint 3 shared-package decision for why this isn't duplicated in each project instead."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class IntakeVerdict(BaseModel):
    verdict: Literal["sufficient", "needs_info", "not_actionable"]
    # Only populated (1-3 entries) when verdict == "needs_info" — see intake_agent.py's
    # INTAKE_INSTRUCTION for the exact bar each question must clear.
    missing_context_questions: list[str] = []


class DuplicateSearchHit(BaseModel):
    """One open issue returned by the GitHub Search API pre-filter (Gate 1 duplicate check) — the
    raw candidate fed to the Duplicate Detector Agent, before any semantic scoring. `body` is a
    truncated excerpt (not the full text) to bound prompt cost."""

    issue_number: int
    title: str
    html_url: str
    body: str


class DuplicateCandidate(BaseModel):
    """One existing open issue the Duplicate Detector Agent judged a likely duplicate of the new
    issue (Gate 1 duplicate check). `score` is the agent's 0-1 similarity confidence; `reason` is
    a one-line human-readable justification shown to the issuer in the flag comment."""

    issue_number: int
    title: str
    html_url: str
    score: float
    reason: str


class DuplicateVerdict(BaseModel):
    """The Duplicate Detector Agent's output (Gate 1 duplicate check). Empty `candidates` means no
    existing issue is a true duplicate — proceed to normal intake. Non-empty means Artisan should
    flag the new issue and ask the issuer to confirm."""

    candidates: list[DuplicateCandidate] = []


class DuplicateConfirmVerdict(BaseModel):
    """The Duplicate Confirm Agent's classification of the issuer's reply to Artisan's duplicate
    flag. `confirm_duplicate` -> close the new issue as a duplicate of `target_issue_number`
    (falls back to the top candidate when None); `not_duplicate` -> proceed to normal intake;
    `needs_clarification` -> the reply was ambiguous, ask once more (capped)."""

    intent: Literal["confirm_duplicate", "not_duplicate", "needs_clarification"]
    target_issue_number: int | None = None


class RoutingDecision(BaseModel):
    """Gate 2's orchestrator-routing output (MILESTONE.md Phase 3.1). `parallel` is explicit rather
    than inferred from `len(domains) > 1` — the routing decision is a real judgment call (e.g. two
    domains touching the same files may still warrant sequential dispatch).

    `domains` is open-ended (WS4, domain generalization) rather than a fixed 3-way `Literal` — the
    routing agent derives a fitting domain name from the issue text and repo context, so
    "frontend"/"backend"/"infra-devops" remain the common defaults but aren't the only valid
    answers (e.g. "mobile", "data-ml", "cli"). `subproject` gives basic monorepo support: it points
    at a relevant subdirectory when the repo has multiple manifest roots, else stays `None`.

    v2 wave 1.5 (#15): `rationale`/`confidence` make the decision auditable — *why* these domains
    and how sure the router was. Report-first: recorded and surfaced, never gated on (an
    abstain/escalate path on low confidence is deferred to wave 2's autonomy tiers). Defaults keep
    pre-#15 producers (and test doubles) valid."""

    domains: list[str]
    parallel: bool
    subproject: str | None = None
    rationale: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"


class DomainExpertOutput(BaseModel):
    # Open-ended (WS4) to match `RoutingDecision.domains` — see that model's docstring.
    domain: str
    technical_summary: str
    relevant_files: list[str]


class RemovedCodeItem(BaseModel):
    """A stale function/branch/exported symbol the Planning Agent identified as fully superseded
    by the new requirement (WS5). The coding agent deletes it as part of carrying out the same
    `Plan` rather than leaving dead code behind."""

    file: str
    symbol: str
    reason: str


class Plan(BaseModel):
    steps: list[str]
    touched_files: list[str]
    test_cases: list[str]
    doc_updates: list[str]
    removed_code: list[RemovedCodeItem] = []


class ExecutionResult(BaseModel):
    branch: str
    diff_summary: str
    tests_passed: bool
    logs_uri: str
    # Bounded full `git diff` content (v2 wave 1.6 #12): verification judged from the coding
    # agent's self-summary + a numstat alone and shipped a partial security fix it couldn't see
    # (false green on the E2E mini-bench). The actual patch — capped by the producer — lets the
    # verifier check what the code DOES, including sibling paths the issue didn't name. Empty
    # when no changes were staged or the producer predates the field.
    diff_patch: str = ""
    # Bounded full content of every changed file (#12 follow-up): a diff shows only changed
    # hunks — an UNCHANGED sibling function with the same bug class (the false green's
    # write_user_file next to the fixed read_user_file) never appears in it. The verifier needs
    # to see what the change DIDN'T touch. Producers cap per-file and total size.
    changed_file_contents: dict[str, str] = {}


class CriterionResult(BaseModel):
    """One domain-lens review criterion judged against the executed change (v2 wave 1.5 #17).
    `evidence` names what in the diff/logs grounds the judgment — a criterion verdict without
    evidence is just a vibe."""

    criterion: str
    status: Literal["met", "not_met", "not_applicable"]
    evidence: str


class VerificationVerdict(BaseModel):
    green: bool
    feedback: str | None = None
    # Report-first (#17): per-criterion results are recorded and surfaced, but overall `green`
    # stays a holistic model judgment — hard-gating on criteria flips only once the eval harness
    # shows criteria verdicts are reliable. Default keeps pre-#17 producers valid.
    criteria_results: list[CriterionResult] = []


class ConflictVerdict(BaseModel):
    classification: Literal["trivial", "semantic"]
    comparison: str | None = None


class ConflictDetectionResult(BaseModel):
    """Gate 3's detection-job output (MILESTONE.md Phase 4.1/4.2) — a real trial merge's outcome, not
    GitHub's async `mergeable_state` (frequently stale/null right when a webhook fires). `head_sha`
    is the freshness key `cloud_run_jobs.trigger_conflict_detection` matches on, since this result
    isn't attempt-numbered like `ExecutionResult` (which matches on `branch` instead)."""

    has_conflict: bool
    conflicted_files: list[str]
    conflict_markers: str
    base_branch_history: str
    diff_summary: str
    logs_uri: str
    head_sha: str


class GitHubWebhookEnvelope(BaseModel):
    """The message published to `artisan-github-events`. Per SYSTEM_DESIGN.md §6.1 — the
    ingestion route's only job is producing this typed envelope, never a raw dict.

    `kind` is defaulted so messages published before `ManualActionEnvelope` existed still validate
    — `gcp/pubsub.py::decode_push_message` peeks at this field to pick which model to validate
    against."""

    kind: Literal["github_event"] = "github_event"
    delivery_id: str
    event: Literal["issues", "issue_comment", "pull_request"]
    action: str
    repo: str
    payload: dict


class RepoContext(BaseModel):
    """A cheap, cacheable snapshot of a repo's shape (WS3) — fetched once per repo (subject to
    `REPO_CONTEXT_TTL_SECONDS`/head-sha staleness) so routing/domain-expert/planning agents can
    ground their reasoning in the repo's actual file tree/manifests rather than the issue text
    alone. See `artisan_agents.repo_context.get_repo_context`."""

    repo: str
    head_sha: str
    file_tree: list[str]
    manifests: dict[str, str]
    languages: dict[str, int]
    # v2 wave 1.5 (#18): the repo's own conventions (CONTRIBUTING / style guides / ADRs), fetched
    # and cached alongside manifests so domain-expert lenses judge changes against *this repo's*
    # rules, not just generic best practice. Default keeps pre-#18 cached docs valid.
    convention_docs: dict[str, str] = {}
    fetched_at: datetime


class ManualActionEnvelope(BaseModel):
    """A dashboard-triggered action, published to the same `artisan-github-events` topic as real
    GitHub webhook events so it gets the same OIDC-authenticated ingress, at-least-once delivery,
    and `claim_delivery` idempotency for free — see docs/SYSTEM_DESIGN.md §8 for the trust-boundary
    rationale (HMAC verification is a GitHub-origin check; this envelope never claims that origin,
    so skipping it here isn't a bypass)."""

    kind: Literal["manual_action"] = "manual_action"
    action_id: str  # uuid4, minted by the dashboard; doubles as the claim_delivery key
    action: Literal["retry_gate1", "retry_gate2", "retry_gate3", "escalate", "mark_done"]
    repo: str
    issue_number: int
    actor: str
    reason: str | None = None
