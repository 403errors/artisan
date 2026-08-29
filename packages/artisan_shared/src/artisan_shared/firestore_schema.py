"""Firestore `tickets/{ticketId}` document schema. Per SYSTEM_DESIGN.md §6.4 — this is the
single source of truth per ticket; every gate reads/writes through it, never through a re-derived
GitHub/Jira lookup."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from artisan_shared.models import (
    ConflictDetectionResult,
    DuplicateCandidate,
    ExecutionResult,
    Plan,
)

TicketStatus = Literal[
    "intake",
    "in_progress",
    "pr_open",
    "escalated",
    "manual_pickup",
    "needs_human_review",
    "duplicate_review",
    "done",
]


class EscalationEntry(BaseModel):
    at: datetime
    reason: str
    gate: Literal["1", "2", "3"]


class TraceEntry(BaseModel):
    """One Cloud Trace span recorded per gate *decision* (tracing.gate_span) — `label` names which
    decision this is (e.g. "Gate 2: verification passed") since a bare trace id alone doesn't say
    what it corresponds to, and a ticket can accumulate several per gate (one per decision point,
    not one per gate)."""

    trace_id: str
    label: str


class TicketDoc(BaseModel):
    github_issue_number: int
    github_repo: str
    jira_key: str
    jira_summary: str | None = None
    status: TicketStatus
    # Display-only progress hint for the Sprint 5 dashboard's live view (e.g. "planning",
    # "executing (attempt 2)") — not a control-flow-branching value like `status`, so it's a plain
    # str rather than a Literal enum. Written by dispatch.py/gate2.py/gate3.py at each sub-step
    # transition; stale values after a gate completes are harmless since the dashboard only reads
    # it while status is "intake"/"in_progress".
    current_step: str | None = None
    clarification_rounds: int = 0
    # Gate 1 duplicate check (SYSTEM_DESIGN.md §3): `duplicate_checked_at` is set the first time the
    # check runs so re-delivered webhooks / manual Gate 1 retries never re-run it (non-None is the
    # "already checked" guard). `duplicate_candidates` is populated only while the ticket waits on
    # the issuer in `duplicate_review`, and cleared again once resolved. `duplicate_followups` caps
    # how many "please confirm" comments Artisan posts when the issuer's reply is ambiguous.
    duplicate_checked_at: datetime | None = None
    duplicate_candidates: list[DuplicateCandidate] = []
    duplicate_followups: int = 0
    retry_count: int = 0
    # Bumped by a manual "retry" action re-entering Gate 2 for a ticket that already executed once
    # — folded into the execution branch name (gate2.py) so a retry's branch never collides with a
    # branch a prior run already pushed. 0 keeps today's branch-name format byte-identical.
    manual_retry_generation: int = 0
    domains: list[str] = []
    plan: Plan | None = None
    last_execution_result: ExecutionResult | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    trivial_conflict_attempts: int = 0
    # Claimed transactionally before the first semantic-conflict escalation ever posts GitHub/Jira
    # comments (Sprint 6) — unlike trivial_conflict_attempts there's no legitimate "retry" concept
    # here, so this is a one-shot boolean, not a counter: every independent opened/synchronize
    # delivery classified `semantic` re-escalates from scratch without it (MILESTONE.md Sprint 4).
    semantic_conflict_escalated: bool = False
    last_conflict_detection: ConflictDetectionResult | None = None
    # Kept distinct from last_execution_result (same underlying type) so Gate 2's execution
    # history and Gate 3's conflict-resolution history stay separable in the Sprint 5 dashboard's
    # decision trail.
    last_conflict_resolution: ExecutionResult | None = None
    escalation_history: list[EscalationEntry] = []
    trace_ids: list[TraceEntry] = []
    processed_delivery_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
