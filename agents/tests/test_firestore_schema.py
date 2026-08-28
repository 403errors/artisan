"""Integration test against the real `artisan-multiagent-ai` Firestore database (Phase 1.5 DoD:
schema-validation fixture matching SYSTEM_DESIGN.md §6.4). Skips if no GCP credentials are
available, so it doesn't break `uv run pytest` in an environment without ADC."""

from datetime import UTC, datetime

import pytest
from google.cloud import firestore

from artisan_agents.firestore_schema import TicketDoc

PROJECT_ID = "artisan-multiagent-ai"


def _client() -> firestore.Client:
    try:
        return firestore.Client(project=PROJECT_ID)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no Firestore credentials available: {exc}")


def test_ticket_doc_roundtrips_through_real_firestore() -> None:
    client = _client()
    now = datetime.now(UTC)
    doc = TicketDoc(
        github_issue_number=1,
        github_repo="403errors/artisan-demo",
        jira_key="ART-1",
        status="intake",
        created_at=now,
        updated_at=now,
    )

    ref = client.collection("tickets").document("scaffold-smoke-test")
    try:
        ref.set(doc.model_dump(mode="json"))
        fetched = ref.get()
        assert fetched.exists
        roundtripped = TicketDoc.model_validate(fetched.to_dict())
        assert roundtripped.jira_key == "ART-1"
        assert roundtripped.status == "intake"
    finally:
        ref.delete()
