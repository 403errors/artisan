"""Firestore access for `tickets/{ticketId}` (SYSTEM_DESIGN.md §6.4) plus the top-level
`processed_deliveries/{delivery_id}` idempotency guard used before a ticket doc exists yet.

Firestore is the single source of truth per ticket (SYSTEM_DESIGN.md §7) — every gate reads and
writes through here, and caps (`clarification_rounds`) are read/incremented transactionally so a
race between duplicate Pub/Sub deliveries can't bypass a cap (cross-cutting rule 3).

The delivery guard itself is a claim, not a flag: `claim_delivery` must be called — and must
succeed — *before* any side effect runs, not after, since Gate 2 can take minutes and Pub/Sub's own
ack-deadline-driven redelivery can easily arrive while the first attempt is still in flight. A
`processed_deliveries/{delivery_id}` doc's `status` moves in_progress -> completed (permanent
dedupe) or in_progress -> failed (reclaimable immediately, so Pub/Sub's own retry-on-failure still
works); an in_progress claim older than DELIVERY_CLAIM_STALE_AFTER_SECONDS is also reclaimable, so a
crashed instance can't block a delivery forever."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from google.cloud import firestore

from artisan_agents.config import (
    DELIVERY_CLAIM_STALE_AFTER_SECONDS,
    EVENT_LOG_ENABLED,
    MAX_CLARIFICATION_ROUNDS,
    MAX_EXECUTION_RETRIES,
    MAX_TRIVIAL_CONFLICT_ATTEMPTS,
)
from artisan_agents.event_context import current_sink
from artisan_shared.event_log import EventSink
from artisan_shared.firestore_schema import EscalationEntry, TicketDoc
from artisan_shared.models import RepoContext
from artisan_shared.ticket_ids import pr_pointer_doc_id, repo_context_doc_id, ticket_doc_id

__all__ = [
    "ClarificationCapExceeded",
    "RetryCapExceeded",
    "TrivialConflictCapExceeded",
    "append_escalation",
    "append_trace_id",
    "claim_delivery",
    "claim_semantic_conflict_escalation",
    "create_ticket",
    "get_cached_repo_context",
    "get_ticket",
    "get_ticket_by_pr",
    "increment_clarification_round",
    "increment_retry_round",
    "increment_trivial_conflict_attempt",
    "mark_delivery_completed",
    "mark_delivery_failed",
    "mark_manual_pickup_directly",
    "mark_needs_human_review",
    "new_event_sink",
    "set_repo_context",
    "ticket_doc_id",
    "update_ticket",
    "write_pr_pointer",
]


class ClarificationCapExceeded(Exception):
    """Raised when a ticket has already hit MAX_CLARIFICATION_ROUNDS — the caller must stop
    attempting further automated clarification and flag the ticket for manual pickup instead."""


class RetryCapExceeded(Exception):
    """Raised when a ticket has already hit MAX_EXECUTION_RETRIES (Gate 2, MILESTONE.md Phase 3.5) —
    the caller must stop retrying the plan/execute/verify loop and escalate instead."""


class TrivialConflictCapExceeded(Exception):
    """Raised when a ticket has already used its one allowed trivial-conflict-resolution attempt
    (Gate 3, MILESTONE.md Phase 4.3, MAX_TRIVIAL_CONFLICT_ATTEMPTS=1) — the caller must escalate
    instead of attempting a second resolution."""


@lru_cache(maxsize=1)
def _client() -> firestore.AsyncClient:
    return firestore.AsyncClient()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_event_sink(ticket_id: str, *, gate: str, actor: str = "orchestrator") -> EventSink:
    """Constructs an `EventSink` bound to this module's own Firestore client instance, scoped to
    one ticket/gate. The entry point for `dispatch.evaluate_intake`/`gate2.start_gate2`/
    `gate3.start_gate3` to install as the ambient sink (`event_context.set_sink`) at the top of
    each gate's entry function."""
    return EventSink(_client(), ticket_id, gate=gate, actor=actor, enabled=EVENT_LOG_ENABLED)


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
    if fields.get("current_step"):
        # Historizes what's otherwise a last-write-wins field — every gate calls update_ticket
        # inline with current_step=... at each sub-step transition, so this one hook covers all of
        # them with no call-site changes.
        await current_sink().emit(type="step_changed", summary=str(fields["current_step"]))
    fields["updated_at"] = _now().isoformat()
    await _client().collection("tickets").document(ticket_doc_id(repo, issue_number)).update(fields)


async def mark_needs_human_review(repo: str, issue_number: int) -> None:
    """Flags a ticket `needs_human_review` (WS1's sus-image gate, dispatch.py's evaluate_intake) —
    a plain (non-transactional) write, since this is a one-shot classification made before the
    Intake Agent ever runs, not a racing-caps scenario like the increment_* helpers below."""
    await update_ticket(repo, issue_number, status="needs_human_review")


async def mark_manual_pickup_directly(repo: str, issue_number: int, reason: str) -> None:
    """Flags a ticket `manual_pickup` directly (WS1's not_actionable intake verdict,
    dispatch.py's evaluate_intake) — bypasses the clarification-round cap entirely since there's no
    round to count here. `reason` is recorded on the existing `current_step` field (prefixed) rather
    than a new schema field, mirroring `update_ticket`'s existing "display-only progress hint"
    convention (see TicketDoc.current_step's docstring)."""
    await update_ticket(
        repo, issue_number, status="manual_pickup", current_step=f"manual_pickup:{reason}"
    )


@firestore.async_transactional
async def _claim_delivery_txn(transaction: firestore.AsyncTransaction, doc_ref) -> bool:
    snapshot = await doc_ref.get(transaction=transaction)
    now = _now()
    if snapshot.exists:
        data = snapshot.to_dict()
        status = data.get("status")
        if status == "completed":
            return False
        if status == "in_progress":
            claimed_at = datetime.fromisoformat(data["claimed_at"])
            if now - claimed_at < timedelta(seconds=DELIVERY_CLAIM_STALE_AFTER_SECONDS):
                return False
            # else: stale in_progress claim (owning instance likely died mid-request) — reclaim.
        # status == "failed", or a stale in_progress claim — reclaimable either way.
    transaction.set(doc_ref, {"status": "in_progress", "claimed_at": now.isoformat()})
    return True


async def claim_delivery(delivery_id: str) -> bool:
    """Atomically claims a Pub/Sub delivery for processing before any side effect runs
    (cross-cutting rule 5). Returns True if the caller should proceed with handle_event, False if
    another still-fresh attempt already owns this delivery ID or it was already fully completed —
    the two cases a real concurrent-duplicate delivery and a genuinely-already-done delivery need
    to be told apart from a delivery that's safe to retry (failed, or stale in_progress)."""
    doc_ref = _client().collection("processed_deliveries").document(delivery_id)
    transaction = _client().transaction()
    return await _claim_delivery_txn(transaction, doc_ref)


async def mark_delivery_completed(delivery_id: str) -> None:
    await _client().collection("processed_deliveries").document(delivery_id).set(
        {"status": "completed", "completed_at": _now().isoformat()}, merge=True
    )


async def mark_delivery_failed(delivery_id: str) -> None:
    await _client().collection("processed_deliveries").document(delivery_id).set(
        {"status": "failed", "failed_at": _now().isoformat()}, merge=True
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
        # Per MILESTONE.md Phase 2.4: the round that *reaches* the cap (the 3rd) is the one that
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
        # Per MILESTONE.md Phase 3.5: the retry that *reaches* the cap is the one that flips the
        # ticket to escalated — there is no (N+1)th attempt to wait for.
        updates["status"] = "escalated"
    transaction.update(doc_ref, updates)
    return new_count, at_cap


async def increment_retry_round(repo: str, issue_number: int) -> int:
    """Transactionally increments `retry_count` (Gate 2, MILESTONE.md Phase 3.5). If this increment
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


@firestore.async_transactional
async def _increment_trivial_conflict_attempt_txn(
    transaction: firestore.AsyncTransaction, doc_ref
) -> tuple[int, bool]:
    # Same commit-then-raise shape as the other two cap functions above (see
    # _increment_clarification_round_txn's NOTE) — but the comparison is deliberately `>`, not
    # `>=`. Unlike the clarification/retry caps (which gate the *next* attempt after a failure, so
    # attempt 1 is always free), MAX_TRIVIAL_CONFLICT_ATTEMPTS=1 is claimed *before* the one
    # allowed attempt runs (mirroring claim_delivery's claim-before-side-effect philosophy) — the
    # first call's new_count (1) must NOT trip the cap, or trivial-conflict resolution would never
    # run at all.
    snapshot = await doc_ref.get(transaction=transaction)
    current = snapshot.get("trivial_conflict_attempts") or 0
    new_count = current + 1
    at_cap = new_count > MAX_TRIVIAL_CONFLICT_ATTEMPTS
    updates: dict = {"trivial_conflict_attempts": new_count, "updated_at": _now().isoformat()}
    if at_cap:
        updates["status"] = "escalated"
    transaction.update(doc_ref, updates)
    return new_count, at_cap


async def increment_trivial_conflict_attempt(repo: str, issue_number: int) -> int:
    """Transactionally claims this ticket's one allowed trivial-conflict-resolution attempt (Gate
    3, MILESTONE.md Phase 4.3) BEFORE the attempt runs. Raises TrivialConflictCapExceeded, atomically
    flipping the ticket to `escalated` in the same transaction, if the cap was already used."""
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    transaction = _client().transaction()
    new_count, at_cap = await _increment_trivial_conflict_attempt_txn(transaction, doc_ref)
    if at_cap:
        raise TrivialConflictCapExceeded(
            f"trivial_conflict_attempts already used the cap ({MAX_TRIVIAL_CONFLICT_ATTEMPTS})"
        )
    return new_count


@firestore.async_transactional
async def _claim_semantic_conflict_escalation_txn(
    transaction: firestore.AsyncTransaction, doc_ref
) -> bool:
    snapshot = await doc_ref.get(transaction=transaction)
    if snapshot.get("semantic_conflict_escalated"):
        return False
    transaction.update(
        doc_ref, {"semantic_conflict_escalated": True, "updated_at": _now().isoformat()}
    )
    return True


async def claim_semantic_conflict_escalation(repo: str, issue_number: int) -> bool:
    """Transactionally claims this ticket's one-and-only semantic-conflict escalation (Gate 3,
    MILESTONE.md Sprint 4 close-out gap, closed Sprint 6). Returns True the first time (caller
    should post the GitHub/Jira escalation comments), False on every subsequent call for the same
    ticket (caller must skip — a repeat `opened`/`synchronize` delivery must not re-post
    duplicate maintainer-facing comments)."""
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    transaction = _client().transaction()
    return await _claim_semantic_conflict_escalation_txn(transaction, doc_ref)


async def write_pr_pointer(repo: str, pr_number: int, issue_number: int) -> None:
    """Writes `pr_index/{repo}__{pr_number} -> {ticket_doc_id}` (Gate 3, MILESTONE.md Phase 4.1) —
    called once, when a PR is opened (gate2.py's `_open_pr_and_sync`), so a later `pull_request`
    webhook resolves straight to the owning ticket without a Firestore query."""
    await _client().collection("pr_index").document(pr_pointer_doc_id(repo, pr_number)).set(
        {"ticket_doc_id": ticket_doc_id(repo, issue_number)}
    )


async def get_ticket_by_pr(repo: str, pr_number: int) -> TicketDoc | None:
    """Resolves a `pull_request` webhook's PR number to its ticket doc via the pr_index pointer —
    a direct `.get()`, never a query. Returns None for any PR Artisan doesn't track (Gate 3 never
    operates on repo state it doesn't own — PRD.md §5)."""
    pointer = await _client().collection("pr_index").document(pr_pointer_doc_id(repo, pr_number)).get()
    if not pointer.exists:
        return None
    snapshot = await _client().collection("tickets").document(pointer.get("ticket_doc_id")).get()
    if not snapshot.exists:
        return None
    return TicketDoc.model_validate(snapshot.to_dict())


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
    await current_sink().emit(type="escalated", gate=entry.gate, summary=entry.reason)


async def get_cached_repo_context(repo: str) -> RepoContext | None:
    """Reads the top-level `repo_context/{repo_sanitized}` doc (WS3) — mirrors `get_ticket_by_pr`'s
    "small top-level collection, direct `.get()`" shape rather than a per-ticket subcollection,
    since a repo's context is shared across every ticket in that repo."""
    snapshot = await _client().collection("repo_context").document(repo_context_doc_id(repo)).get()
    if not snapshot.exists:
        return None
    return RepoContext.model_validate(snapshot.to_dict())


async def set_repo_context(repo: str, context: RepoContext) -> None:
    """Overwrites the cached `RepoContext` for `repo` (WS3) — same `mode="json"` dict-write
    convention as `create_ticket`/`update_ticket` above, so datetimes/etc. round-trip through
    Firestore the same way ticket docs do."""
    await _client().collection("repo_context").document(repo_context_doc_id(repo)).set(
        context.model_dump(mode="json")
    )


async def append_trace_id(ticket_id: str, trace_id: str, label: str) -> None:
    """Atomically appends one `{trace_id, label}` entry to `trace_ids` via `firestore.ArrayUnion`,
    mirroring append_escalation's shape. Called from tracing.gate_span on span exit, which already
    holds the computed ticket doc id — takes it directly rather than (repo, issue_number) since
    every call site already has it. Deliberately does NOT flip `status` — this is a pure
    observability record, unlike append_escalation."""
    doc_ref = _client().collection("tickets").document(ticket_id)
    await doc_ref.update(
        {
            "trace_ids": firestore.ArrayUnion([{"trace_id": trace_id, "label": label}]),
            "updated_at": _now().isoformat(),
        }
    )
