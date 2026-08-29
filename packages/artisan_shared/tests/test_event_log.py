"""Unit tests for `EventSink`/`NoOpEventSink`. No real Firestore client — a hand-rolled fake
stands in for `firestore.AsyncClient`'s `.collection("tickets").document(id).collection("events")`
chain, since these are pure translation/plumbing tests, not integration tests."""

import itertools

import pytest
from artisan_shared.event_log import EventSink, NoOpEventSink


class _FakeDocRef:
    def __init__(self, store: dict, doc_id: str) -> None:
        self._store = store
        self.id = doc_id

    async def set(self, data: dict) -> None:
        self._store[self.id] = data

    async def update(self, data: dict) -> None:
        self._store[self.id].update(data)


# Firestore's real auto-id `.document()` is unique per call regardless of how many
# `.collection(...)` wrapper objects sit between it and the client — the fake needs the same
# property, so the counter lives at module scope rather than on a per-call wrapper instance.
_auto_ids = itertools.count(1)


class _FakeEventsCollection:
    def __init__(self, store: dict) -> None:
        self._store = store

    def document(self, doc_id: str | None = None) -> _FakeDocRef:
        if doc_id is None:
            doc_id = f"auto-{next(_auto_ids)}"
        return _FakeDocRef(self._store, doc_id)


class _FakeTicketDocRef:
    def __init__(self, events_store: dict) -> None:
        self._events_store = events_store

    def collection(self, name: str) -> _FakeEventsCollection:
        assert name == "events"
        return _FakeEventsCollection(self._events_store)


class _FakeTicketsCollection:
    def __init__(self, events_store: dict) -> None:
        self._events_store = events_store

    def document(self, ticket_id: str) -> _FakeTicketDocRef:
        return _FakeTicketDocRef(self._events_store)


class FakeFirestoreClient:
    """Enough of the Firestore `AsyncClient` surface for `EventSink`."""

    def __init__(self) -> None:
        self.events: dict = {}

    def collection(self, name: str) -> _FakeTicketsCollection:
        assert name == "tickets"
        return _FakeTicketsCollection(self.events)


@pytest.mark.asyncio
async def test_emit_writes_an_event_and_returns_its_id() -> None:
    client = FakeFirestoreClient()
    sink = EventSink(client, "ticket-1", gate="2", actor="orchestrator")

    doc_id = await sink.emit(type="gate_started", summary="Gate 2 started")

    assert doc_id is not None
    stored = client.events[doc_id]
    assert stored["type"] == "gate_started"
    assert stored["summary"] == "Gate 2 started"
    assert stored["gate"] == "2"
    assert stored["actor"] == "orchestrator"
    assert stored["seq"] == 0
    assert stored["truncated"] is False


@pytest.mark.asyncio
async def test_seq_increments_across_calls_on_the_same_sink() -> None:
    client = FakeFirestoreClient()
    sink = EventSink(client, "ticket-1")

    first = await sink.emit(type="gate_started", summary="a")
    second = await sink.emit(type="gate_started", summary="b")

    assert client.events[first]["seq"] == 0
    assert client.events[second]["seq"] == 1


@pytest.mark.asyncio
async def test_child_sink_shares_run_id_and_seq_counter() -> None:
    client = FakeFirestoreClient()
    parent = EventSink(client, "ticket-1", gate="2", actor="orchestrator")
    child = parent.child(gate="3", actor="coding_agent")

    id1 = await parent.emit(type="gate_started", summary="a")
    id2 = await child.emit(type="tool_call", summary="b")

    assert client.events[id1]["run_id"] == client.events[id2]["run_id"]
    assert client.events[id1]["seq"] == 0
    assert client.events[id2]["seq"] == 1
    assert client.events[id2]["gate"] == "3"
    assert client.events[id2]["actor"] == "coding_agent"


@pytest.mark.asyncio
async def test_emit_truncates_and_redacts_before_writing() -> None:
    client = FakeFirestoreClient()
    sink = EventSink(client, "ticket-1", redact_token="secret-token-123")

    doc_id = await sink.emit(
        type="tool_call",
        summary="ran with secret-token-123",
        detail="a" * 5000,
    )

    stored = client.events[doc_id]
    assert "secret-token-123" not in stored["summary"]
    assert stored["truncated"] is True
    assert len(stored["detail"]) < 5000


@pytest.mark.asyncio
async def test_patch_attaches_a_tool_result_to_an_existing_event() -> None:
    client = FakeFirestoreClient()
    sink = EventSink(client, "ticket-1")
    doc_id = await sink.emit(type="tool_call", summary="read_file(a.txt)", tool_name="read_file")

    await sink.patch(doc_id, tool_result_summary="file contents here")

    assert client.events[doc_id]["tool_result_summary"] == "file contents here"


@pytest.mark.asyncio
async def test_patch_is_a_noop_for_a_missing_doc_id() -> None:
    client = FakeFirestoreClient()
    sink = EventSink(client, "ticket-1")
    await sink.patch(None, tool_result_summary="x")  # must not raise


@pytest.mark.asyncio
async def test_emit_never_raises_even_if_the_client_is_broken() -> None:
    class BrokenClient:
        def collection(self, name: str):
            raise RuntimeError("boom")

    sink = EventSink(BrokenClient(), "ticket-1")
    result = await sink.emit(type="error", summary="x")

    assert result is None


@pytest.mark.asyncio
async def test_noop_sink_never_touches_a_client() -> None:
    sink = NoOpEventSink()
    doc_id = await sink.emit(type="gate_started", summary="a")
    await sink.patch("whatever", tool_result_summary="x")

    assert doc_id is None
