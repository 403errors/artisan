"""Writes this attempt's `ExecutionResult` onto the ticket's Firestore doc (SYSTEM_DESIGN.md §8:
"execution-sandbox: Firestore write ... only"). Uses the exact same `ticket_doc_id` scheme as the
orchestrator (`artisan_shared.ticket_ids`) so the orchestrator's later read
(`agents/gcp/cloud_run_jobs.py::trigger_execution`) lands on the same document."""

from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from artisan_execution_sandbox.config import GCP_PROJECT_ID
from artisan_shared.models import ExecutionResult
from artisan_shared.ticket_ids import ticket_doc_id


@lru_cache(maxsize=1)
def _client() -> firestore.AsyncClient:
    return firestore.AsyncClient(project=GCP_PROJECT_ID)


async def write_execution_result(repo: str, issue_number: int, result: ExecutionResult) -> None:
    doc_ref = _client().collection("tickets").document(ticket_doc_id(repo, issue_number))
    await doc_ref.update(
        {
            "last_execution_result": result.model_dump(mode="json"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
