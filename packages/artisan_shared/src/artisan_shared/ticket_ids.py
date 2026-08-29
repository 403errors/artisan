"""The Firestore `tickets/{ticketId}` doc-id scheme. Shared so `execution-sandbox` (Sprint 3) can
write `last_execution_result` onto the exact same doc the orchestrator later reads from, without
re-deriving or duplicating the id-slugging logic."""

import re

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]")


def ticket_doc_id(repo: str, issue_number: int) -> str:
    """Deterministic id so ticket lookups never need a query — just a direct `.get()`."""
    return f"{_SLUG_RE.sub('_', repo)}__{issue_number}"


def pr_pointer_doc_id(repo: str, pr_number: int) -> str:
    """Deterministic id for the top-level `pr_index` collection (Gate 3, MILESTONE.md Phase 4.1) —
    resolves a `pull_request` webhook straight to a ticket doc id without a query, same philosophy
    as `ticket_doc_id` above."""
    return f"{_SLUG_RE.sub('_', repo)}__{pr_number}"
