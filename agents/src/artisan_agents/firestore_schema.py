"""Firestore `tickets/{ticketId}` document schema. Per SYSTEM_DESIGN.md §6.4 — this is the
single source of truth per ticket; every gate reads/writes through it, never through a re-derived
GitHub/Jira lookup."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from artisan_agents.models import Plan

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
    clarification_rounds: int = 0
    retry_count: int = 0
    domains: list[str] = []
    plan: Plan | None = None
    pr_url: str | None = None
    escalation_history: list[EscalationEntry] = []
    trace_ids: list[str] = []
    processed_delivery_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
