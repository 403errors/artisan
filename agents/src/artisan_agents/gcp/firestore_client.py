"""Firestore access for `tickets/{ticketId}` (SYSTEM_DESIGN.md §6.4) plus the top-level
`processed_deliveries/{delivery_id}` idempotency guard used before a ticket doc exists yet.

Firestore is the single source of truth per ticket (SYSTEM_DESIGN.md §7) — every gate reads and
writes through here, and caps (`clarification_rounds`) are read/incremented transactionally so a
race between duplicate Pub/Sub deliveries can't bypass a cap (cross-cutting rule 3)."""

import re
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from artisan_agents.config import MAX_CLARIFICATION_ROUNDS
from artisan_agents.firestore_schema import TicketDoc

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]")


class ClarificationCapExceeded(Exception):
    """Raised when a ticket has already hit MAX_CLARIFICATION_ROUNDS — the caller must stop
    attempting further automated clarification and flag the ticket for manual pickup instead."""


@lru_cache(maxsize=1)
def _client() -> firestore.AsyncClient:
    return firestore.AsyncClient()


def ticket_doc_id(repo: str, issue_number: int) -> str:
    """Deterministic id so ticket lookups never need a query — just a direct `.get()`."""
    return f"{_SLUG_RE.sub('_', repo)}__{issue_number}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_ticket(repo: str, issue_number: int) -> TicketDoc | None:
    snapshot = await _client().collection("tickets").document(ticket_doc_id(repo, issue_number)).get()
    if not snapshot.exists:
        return None
    return TicketDoc.model_validate(snapshot.to_dict())


async def create_ticket(repo: str, issue_number: int, jira_key: str) -> TicketDoc:
    """Creates the ticket doc. Callers must have already created the Jira ticket (jira/client.py)
    since `jira_key` is a required field — the mapping is stored atomically with the doc, not
    added in a follow-up write."""
    now = _now()
    doc = TicketDoc(
        github_issue_number=issue_number,
        github_repo=repo,
        jira_key=jira_key,
        status="intake",
        created_at=now,
        updated_at=now,
    )
    await _client().collection("tickets").document(ticket_doc_id(repo, issue_number)).set(
        doc.model_dump(mode="json")
    )
    return doc


async def update_ticket(repo: str, issue_number: int, **fields) -> None:
    fields["updated_at"] = _now().isoformat()
    await _client().collection("tickets").document(ticket_doc_id(repo, issue_number)).update(fields)


async def is_duplicate_delivery(delivery_id: str) -> bool:
    snapshot = await _client().collection("processed_deliveries").document(delivery_id).get()
    return snapshot.exists


async def mark_delivery_processed(delivery_id: str) -> None:
    await _client().collection("processed_deliveries").document(delivery_id).set(
        {"processed_at": _now().isoformat()}
    )


@firestore.async_transactional
async def _increment_clarification_round_txn(
    transaction: firestore.AsyncTransaction, doc_ref
) -> tuple[int, bool]:
    # NOTE: a Firestore transactional callable only commits its writes if it returns normally —
    # raising inside it aborts/rolls back the transaction. So the cap flag is returned rather than
    # raised here; the (non-transactional) caller raises after the write has actually committed.
    snapshot = await doc_ref.get(transaction=transaction)
    current = snapshot.get("clarification_rounds") or 0
    new_count = current + 1
    at_cap = new_count >= MAX_CLARIFICATION_ROUNDS
    updates: dict = {"clarification_rounds": new_count, "updated_at": _now().isoformat()}
    if at_cap:
        # Per SPRINT.md Phase 2.4: the round that *reaches* the cap (the 3rd) is the one that
        # flips the ticket to manual_pickup — there is no 4th attempt to wait for.
        updates["status"] = "manual_pickup"
    transaction.update(doc_ref, updates)
    return new_count, at_cap


async def increment_clarification_round(repo: str, issue_number: int) -> int:
    """Transactionally increments `clarification_rounds`. If this increment reaches the cap, also
    flags the ticket `manual_pickup` in the same transaction and raises ClarificationCapExceeded —
    atomically, so a race between duplicate deliveries can't both cross the cap and leave the
    ticket looking like it's still in normal `intake` status."""
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    transaction = _client().transaction()
    new_count, at_cap = await _increment_clarification_round_txn(transaction, doc_ref)
    if at_cap:
        raise ClarificationCapExceeded(
            f"clarification_rounds reached cap ({MAX_CLARIFICATION_ROUNDS}) on this round"
        )
    return new_count
