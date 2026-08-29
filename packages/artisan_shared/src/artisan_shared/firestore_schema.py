"""Firestore `tickets/{ticketId}` document schema. Per SYSTEM_DESIGN.md §6.4 — this is the
single source of truth per ticket; every gate reads/writes through it, never through a re-derived
GitHub/Jira lookup."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from artisan_shared.models import ConflictDetectionResult, ExecutionResult, Plan

TicketStatus = Literal[
    "intake", "in_progress", "pr_open", "escalated", "manual_pickup", "done"
]


class EscalationEntry(BaseModel):
    at: datetime
    reason: str
    gate: Literal["1", "2", "3"]


class TicketDoc(BaseModel):
    github_issue_number: int
    github_repo: str
    jira_key: str
    status: TicketStatus
    # Display-only progress hint for the Sprint 5 dashboard's live view (e.g. "planning",
    # "executing (attempt 2)") — not a control-flow-branching value like `status`, so it's a plain
    # str rather than a Literal enum. Written by dispatch.py/gate2.py/gate3.py at each sub-step
    # transition; stale values after a gate completes are harmless since the dashboard only reads
    # it while status is "intake"/"in_progress".
    current_step: str | None = None
    clarification_rounds: int = 0
    retry_count: int = 0
    domains: list[str] = []
    plan: Plan | None = None
    last_execution_result: ExecutionResult | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    trivial_conflict_attempts: int = 0
    last_conflict_detection: ConflictDetectionResult | None = None
    # Kept distinct from last_execution_result (same underlying type) so Gate 2's execution
    # history and Gate 3's conflict-resolution history stay separable in the Sprint 5 dashboard's
    # decision trail.
    last_conflict_resolution: ExecutionResult | None = None
    escalation_history: list[EscalationEntry] = []
    trace_ids: list[str] = []
    processed_delivery_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
