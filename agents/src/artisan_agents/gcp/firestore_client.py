"""Firestore access for `tickets/{ticketId}` (SYSTEM_DESIGN.md §6.4) plus the top-level
`processed_deliveries/{delivery_id}` idempotency guard used before a ticket doc exists yet.

Firestore is the single source of truth per ticket (SYSTEM_DESIGN.md §7) — every gate reads and
writes through here, and caps (`clarification_rounds`) are read/incremented transactionally so a
race between duplicate Pub/Sub deliveries can't bypass a cap (cross-cutting rule 3)."""

from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from artisan_agents.config import MAX_CLARIFICATION_ROUNDS, MAX_EXECUTION_RETRIES
from artisan_shared.firestore_schema import EscalationEntry, TicketDoc
from artisan_shared.ticket_ids import ticket_doc_id

__all__ = [
    "ClarificationCapExceeded",
    "RetryCapExceeded",
    "append_escalation",
    "create_ticket",
    "get_ticket",
    "increment_clarification_round",
    "increment_retry_round",
    "is_duplicate_delivery",
    "mark_delivery_processed",
    "ticket_doc_id",
    "update_ticket",
]


class ClarificationCapExceeded(Exception):
    """Raised when a ticket has already hit MAX_CLARIFICATION_ROUNDS — the caller must stop
    attempting further automated clarification and flag the ticket for manual pickup instead."""


class RetryCapExceeded(Exception):
    """Raised when a ticket has already hit MAX_EXECUTION_RETRIES (Gate 2, SPRINT.md Phase 3.5) —
    the caller must stop retrying the plan/execute/verify loop and escalate instead."""


@lru_cache(maxsize=1)
def _client() -> firestore.AsyncClient:
    return firestore.AsyncClient()


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


@firestore.async_transactional
async def _increment_retry_round_txn(
    transaction: firestore.AsyncTransaction, doc_ref
) -> tuple[int, bool]:
    # Same commit-then-raise shape as _increment_clarification_round_txn above (see that
    # function's NOTE) — the cap flag is returned, not raised, so the write always commits.
    snapshot = await doc_ref.get(transaction=transaction)
    current = snapshot.get("retry_count") or 0
    new_count = current + 1
    at_cap = new_count >= MAX_EXECUTION_RETRIES
    updates: dict = {"retry_count": new_count, "updated_at": _now().isoformat()}
    if at_cap:
        # Per SPRINT.md Phase 3.5: the retry that *reaches* the cap is the one that flips the
        # ticket to escalated — there is no (N+1)th attempt to wait for.
        updates["status"] = "escalated"
    transaction.update(doc_ref, updates)
    return new_count, at_cap


async def increment_retry_round(repo: str, issue_number: int) -> int:
    """Transactionally increments `retry_count` (Gate 2, SPRINT.md Phase 3.5). If this increment
    reaches MAX_EXECUTION_RETRIES, also flags the ticket `escalated` in the same transaction and
    raises RetryCapExceeded — atomically, mirroring increment_clarification_round's cap shape."""
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    transaction = _client().transaction()
    new_count, at_cap = await _increment_retry_round_txn(transaction, doc_ref)
    if at_cap:
        raise RetryCapExceeded(
            f"retry_count reached cap ({MAX_EXECUTION_RETRIES}) on this attempt"
        )
    return new_count


async def append_escalation(repo: str, issue_number: int, entry: EscalationEntry) -> None:
    """Atomically appends one entry to `escalation_history` via `firestore.ArrayUnion`, rather
    than a read-modify-write — `update_ticket`'s generic `.update(fields)` is not itself
    transactional, so a naive read-then-write here could lose a concurrent escalation entry the
    same way the caps above guard against. `ArrayUnion` is a native atomic field-transform, which
    is enough for a pure append (no conditional cap logic needed, unlike the two functions above).
    Also flips `status` to `escalated` in the same write. Generic across gates (`entry.gate` is
    "1"|"2"|"3") so Gate 3 (Sprint 4) can reuse this as-is."""
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    await doc_ref.update(
        {
            "escalation_history": firestore.ArrayUnion([entry.model_dump(mode="json")]),
            "status": "escalated",
            "updated_at": _now().isoformat(),
        }
    )
