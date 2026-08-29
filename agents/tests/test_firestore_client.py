"""Integration tests against the real `artisan-multiagent-ai` Firestore database — same
skip-if-no-ADC convention as test_firestore_schema.py. Exercises ticket bootstrap (Phase 2.2), the
idempotency guard (Phase 2.1), the transactional clarification-round cap (Phase 2.4), Gate 2's
transactional retry cap + escalation-history append (Phase 3.5), and Gate 3's transactional
trivial-conflict cap + PR-index pointer (Phase 4.1/4.3, MILESTONE.md)."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from google.cloud import firestore

from artisan_agents.gcp import firestore_client
from artisan_agents.gcp.firestore_client import (
    ClarificationCapExceeded,
    RetryCapExceeded,
    TrivialConflictCapExceeded,
)
from artisan_shared.firestore_schema import EscalationEntry

REPO = "403errors/artisan-demo"


@pytest.fixture(autouse=True)
def _fresh_firestore_client():
    """pytest-asyncio gives each test its own event loop, but `_client()` is process-lifetime
    lru_cached (by design — one AsyncClient/gRPC channel per Cloud Run process, not per request).
    Clear it around each test so a channel from a closed loop is never reused across tests."""
    firestore_client._client.cache_clear()
    yield
    firestore_client._client.cache_clear()


def _require_credentials() -> None:
    try:
        firestore.Client(project="artisan-multiagent-ai")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no Firestore credentials available: {exc}")


@pytest_asyncio.fixture
async def cleanup_ticket():
    issue_numbers: list[int] = []
    yield issue_numbers
    client = firestore_client._client()
    for issue_number in issue_numbers:
        doc_ref = client.collection("tickets").document(firestore_client.ticket_doc_id(REPO, issue_number))
        # Sprint 6's event log lives in a subcollection — Firestore doesn't cascade-delete, so
        # deleting the parent doc alone would leak these on every real-Firestore test run.
        async for event_doc in doc_ref.collection("events").stream():
            await event_doc.reference.delete()
        await doc_ref.delete()


@pytest_asyncio.fixture
async def cleanup_delivery():
    delivery_ids: list[str] = []
    yield delivery_ids
    client = firestore_client._client()
    for delivery_id in delivery_ids:
        await client.collection("processed_deliveries").document(delivery_id).delete()


@pytest_asyncio.fixture
async def cleanup_pr_pointer():
    pr_numbers: list[int] = []
    yield pr_numbers
    client = firestore_client._client()
    for pr_number in pr_numbers:
        await client.collection("pr_index").document(
            firestore_client.pr_pointer_doc_id(REPO, pr_number)
        ).delete()


def test_ticket_doc_id_is_deterministic_and_slug_safe() -> None:
    assert firestore_client.ticket_doc_id("403errors/artisan-demo", 7) == "403errors_artisan-demo__7"


@pytest.mark.asyncio
async def test_create_and_get_ticket_roundtrip(cleanup_ticket) -> None:
    _require_credentials()
    issue_number = 900001
    cleanup_ticket.append(issue_number)

    assert await firestore_client.get_ticket(REPO, issue_number) is None

    created = await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900001")
    assert created.status == "intake"
    assert created.clarification_rounds == 0

    fetched = await firestore_client.get_ticket(REPO, issue_number)
    assert fetched is not None
    assert fetched.jira_key == "ART-900001"


@pytest.mark.asyncio
async def test_clarification_round_cap_flips_to_manual_pickup_on_third_round(
    cleanup_ticket,
) -> None:
    _require_credentials()
    issue_number = 900002
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900002")

    assert await firestore_client.increment_clarification_round(REPO, issue_number) == 1
    assert await firestore_client.increment_clarification_round(REPO, issue_number) == 2

    with pytest.raises(ClarificationCapExceeded):
        await firestore_client.increment_clarification_round(REPO, issue_number)

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.status == "manual_pickup"
    assert ticket.clarification_rounds == 3


@pytest.mark.asyncio
async def test_claim_delivery_rejects_a_concurrent_duplicate_while_still_fresh(
    cleanup_delivery,
) -> None:
    _require_credentials()
    delivery_id = "test-delivery-900003"
    cleanup_delivery.append(delivery_id)

    assert await firestore_client.claim_delivery(delivery_id) is True
    # A second delivery of the same ID arriving while the first is still (by definition,
    # since nothing has marked it completed/failed yet) in flight must be rejected — this is
    # the exact race a naive check-then-mark-after-success guard misses.
    assert await firestore_client.claim_delivery(delivery_id) is False


@pytest.mark.asyncio
async def test_claim_delivery_is_permanently_blocked_after_completion(cleanup_delivery) -> None:
    _require_credentials()
    delivery_id = "test-delivery-900004"
    cleanup_delivery.append(delivery_id)

    assert await firestore_client.claim_delivery(delivery_id) is True
    await firestore_client.mark_delivery_completed(delivery_id)
    assert await firestore_client.claim_delivery(delivery_id) is False


@pytest.mark.asyncio
async def test_claim_delivery_is_reclaimable_after_failure(cleanup_delivery) -> None:
    _require_credentials()
    delivery_id = "test-delivery-900005"
    cleanup_delivery.append(delivery_id)

    assert await firestore_client.claim_delivery(delivery_id) is True
    await firestore_client.mark_delivery_failed(delivery_id)
    # A genuinely failed attempt must not block Pub/Sub's own retry-on-failure mechanism.
    assert await firestore_client.claim_delivery(delivery_id) is True


@pytest.mark.asyncio
async def test_claim_delivery_reclaims_a_stale_in_progress_claim(
    cleanup_delivery, monkeypatch
) -> None:
    _require_credentials()
    delivery_id = "test-delivery-900006"
    cleanup_delivery.append(delivery_id)

    assert await firestore_client.claim_delivery(delivery_id) is True
    # Simulate the owning instance having died mid-request: shrink the staleness window to 0
    # rather than sleeping in the test.
    monkeypatch.setattr(firestore_client, "DELIVERY_CLAIM_STALE_AFTER_SECONDS", 0)
    assert await firestore_client.claim_delivery(delivery_id) is True


@pytest.mark.asyncio
async def test_retry_cap_flips_to_escalated_on_third_round(cleanup_ticket) -> None:
    """Mirrors test_clarification_round_cap_flips_to_manual_pickup_on_third_round — Gate 2's
    retry cap (Phase 3.5) uses the identical commit-then-raise transactional shape."""
    _require_credentials()
    issue_number = 900004
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900004")

    assert await firestore_client.increment_retry_round(REPO, issue_number) == 1
    assert await firestore_client.increment_retry_round(REPO, issue_number) == 2

    with pytest.raises(RetryCapExceeded):
        await firestore_client.increment_retry_round(REPO, issue_number)

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.status == "escalated"
    assert ticket.retry_count == 3


@pytest.mark.asyncio
async def test_append_escalation_is_atomic_and_flips_status(cleanup_ticket) -> None:
    _require_credentials()
    issue_number = 900005
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900005")

    entry = EscalationEntry(at=datetime.now(UTC), reason="verification failed 3x", gate="2")
    await firestore_client.append_escalation(REPO, issue_number, entry)

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.status == "escalated"
    assert len(ticket.escalation_history) == 1
    assert ticket.escalation_history[0].reason == "verification failed 3x"
    assert ticket.escalation_history[0].gate == "2"


@pytest.mark.asyncio
async def test_append_trace_id_is_atomic_and_does_not_flip_status(cleanup_ticket) -> None:
    _require_credentials()
    issue_number = 900013
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900013")
    doc_id = firestore_client.ticket_doc_id(REPO, issue_number)

    await firestore_client.append_trace_id(doc_id, "a" * 32)

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.trace_ids == ["a" * 32]
    assert ticket.status == "intake"  # unlike append_escalation, must NOT flip to escalated


@pytest.mark.asyncio
async def test_trivial_conflict_attempt_first_call_succeeds_even_though_new_count_equals_cap(
    cleanup_ticket,
) -> None:
    """The critical regression test: MAX_TRIVIAL_CONFLICT_ATTEMPTS=1 means the first call's
    new_count (1) equals the cap — this must NOT raise, unlike the clarification/retry caps'
    `>=` comparison (which gate the *next* attempt after a failure, not the first one)."""
    _require_credentials()
    issue_number = 900010
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900010")

    assert await firestore_client.increment_trivial_conflict_attempt(REPO, issue_number) == 1

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.status != "escalated"
    assert ticket.trivial_conflict_attempts == 1


@pytest.mark.asyncio
async def test_trivial_conflict_attempt_second_call_raises_and_flips_to_escalated(
    cleanup_ticket,
) -> None:
    _require_credentials()
    issue_number = 900011
    cleanup_ticket.append(issue_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900011")

    await firestore_client.increment_trivial_conflict_attempt(REPO, issue_number)
    with pytest.raises(TrivialConflictCapExceeded):
        await firestore_client.increment_trivial_conflict_attempt(REPO, issue_number)

    ticket = await firestore_client.get_ticket(REPO, issue_number)
    assert ticket.status == "escalated"
    assert ticket.trivial_conflict_attempts == 2


@pytest.mark.asyncio
async def test_write_and_read_pr_pointer_roundtrips_to_ticket(
    cleanup_ticket, cleanup_pr_pointer
) -> None:
    _require_credentials()
    issue_number = 900012
    pr_number = 5012
    cleanup_ticket.append(issue_number)
    cleanup_pr_pointer.append(pr_number)
    await firestore_client.create_ticket(REPO, issue_number, jira_key="ART-900012")

    await firestore_client.write_pr_pointer(REPO, pr_number, issue_number)

    ticket = await firestore_client.get_ticket_by_pr(REPO, pr_number)
    assert ticket is not None
    assert ticket.github_issue_number == issue_number
    assert ticket.jira_key == "ART-900012"


@pytest.mark.asyncio
async def test_get_ticket_by_pr_returns_none_for_untracked_pr() -> None:
    _require_credentials()
    assert await firestore_client.get_ticket_by_pr(REPO, 999999999) is None


@pytest_asyncio.fixture
async def cleanup_repo_context():
    repos: list[str] = []
    yield repos
    client = firestore_client._client()
    for repo in repos:
        await client.collection("repo_context").document(
            firestore_client.repo_context_doc_id(repo)
        ).delete()


@pytest.mark.asyncio
async def test_get_cached_repo_context_returns_none_when_absent(cleanup_repo_context) -> None:
    _require_credentials()
    repo = "403errors/artisan-demo-repo-context-absent"
    cleanup_repo_context.append(repo)
    assert await firestore_client.get_cached_repo_context(repo) is None


@pytest.mark.asyncio
async def test_set_and_get_cached_repo_context_roundtrips(cleanup_repo_context) -> None:
    _require_credentials()
    from artisan_shared.models import RepoContext

    repo = "403errors/artisan-demo-repo-context-roundtrip"
    cleanup_repo_context.append(repo)
    context = RepoContext(
        repo=repo,
        head_sha="deadbeef",
        file_tree=["a.py", "package.json"],
        manifests={"package.json": '{"name": "demo"}'},
        languages={".py": 1, ".json": 1},
        fetched_at=datetime.now(UTC),
    )

    await firestore_client.set_repo_context(repo, context)

    fetched = await firestore_client.get_cached_repo_context(repo)
    assert fetched is not None
    assert fetched.head_sha == "deadbeef"
    assert fetched.manifests == {"package.json": '{"name": "demo"}'}


# --- WS1: mark_needs_human_review / mark_manual_pickup_directly ------------------------------
# Pure unit tests (monkeypatch update_ticket) rather than real-Firestore integration tests, since
# these two are trivial one-line delegations to update_ticket, already covered end-to-end here.


@pytest.mark.asyncio
async def test_mark_needs_human_review_updates_status(monkeypatch) -> None:
    calls = []

    async def fake_update_ticket(repo, issue_number, **fields):
        calls.append((repo, issue_number, fields))

    monkeypatch.setattr(firestore_client, "update_ticket", fake_update_ticket)

    await firestore_client.mark_needs_human_review("acme/demo", 7)

    assert calls == [("acme/demo", 7, {"status": "needs_human_review"})]


@pytest.mark.asyncio
async def test_mark_manual_pickup_directly_updates_status_and_records_reason(monkeypatch) -> None:
    calls = []

    async def fake_update_ticket(repo, issue_number, **fields):
        calls.append((repo, issue_number, fields))

    monkeypatch.setattr(firestore_client, "update_ticket", fake_update_ticket)

    await firestore_client.mark_manual_pickup_directly("acme/demo", 7, reason="not_actionable")

    assert calls == [
        (
            "acme/demo",
            7,
            {"status": "manual_pickup", "current_step": "manual_pickup:not_actionable"},
        )
    ]
