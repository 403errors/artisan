"""Writes this attempt's `ExecutionResult` onto the ticket's Firestore doc (SYSTEM_DESIGN.md §8:
"execution-sandbox: Firestore write ... only"). Uses the exact same `ticket_doc_id` scheme as the
orchestrator (`artisan_shared.ticket_ids`) so the orchestrator's later read
(`agents/gcp/cloud_run_jobs.py::trigger_execution`) lands on the same document."""

from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from artisan_execution_sandbox.config import EVENT_LOG_ENABLED, GCP_PROJECT_ID
from artisan_shared.event_log import EventSink
from artisan_shared.models import ConflictDetectionResult, ExecutionResult
from artisan_shared.ticket_ids import ticket_doc_id


@lru_cache(maxsize=1)
def _client() -> firestore.AsyncClient:
    return firestore.AsyncClient(project=GCP_PROJECT_ID)


def new_event_sink(
    ticket_id: str, *, gate: str, actor: str = "coding_agent", redact_token: str | None = None
) -> EventSink:
    """Constructs an `EventSink` bound to this module's own Firestore client instance — the
    execution-sandbox-side counterpart of `agents/gcp/firestore_client.py::new_event_sink`.
    `redact_token` should be the live GitHub installation token minted for this run, so tool
    output containing it (e.g. `cat .git/config`) gets redacted before it's ever written."""
    return EventSink(
        _client(), ticket_id, gate=gate, actor=actor, redact_token=redact_token, enabled=EVENT_LOG_ENABLED
    )


async def _update(repo: str, issue_number: int, field: str, payload) -> None:
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    await doc_ref.update(
        {
            field: payload.model_dump(mode="json"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


async def write_execution_result(repo: str, issue_number: int, result: ExecutionResult) -> None:
    await _update(repo, issue_number, "last_execution_result", result)


async def write_conflict_detection_result(
    repo: str, issue_number: int, result: ConflictDetectionResult
) -> None:
    """Gate 3, MILESTONE.md Phase 4.1/4.2."""
    await _update(repo, issue_number, "last_conflict_detection", result)


async def write_conflict_resolution_result(
    repo: str, issue_number: int, result: ExecutionResult
) -> None:
    """Gate 3, MILESTONE.md Phase 4.3 — kept in a field distinct from `last_execution_result` (Gate
    2's field) even though the type is identical, so the Sprint 5 dashboard's decision trail can
    tell the two histories apart."""
    await _update(repo, issue_number, "last_conflict_resolution", result)
