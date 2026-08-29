"""Pure-unit tests for `firestore_client`'s event-log emission (Sprint 6): `update_ticket` emits
`step_changed` when `current_step` is written, `append_escalation` emits `escalated`. `_client()`
is mocked here — unlike test_firestore_client.py, this file never touches the real
`artisan-multiagent-ai` database."""

from datetime import UTC, datetime

import pytest
from artisan_agents import event_context
from artisan_agents.gcp import firestore_client
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import EscalationEntry

REPO = "acme/demo"
ISSUE_NUMBER = 1


class _FakeDocRef:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    async def update(self, fields: dict) -> None:
        self.updates.append(fields)


class _FakeCollection:
    def __init__(self, doc_ref: _FakeDocRef) -> None:
        self._doc_ref = doc_ref

    def document(self, doc_id: str) -> _FakeDocRef:
        return self._doc_ref


class _FakeClient:
    def __init__(self, doc_ref: _FakeDocRef) -> None:
        self._doc_ref = doc_ref

    def collection(self, name: str) -> _FakeCollection:
        assert name == "tickets"
        return _FakeCollection(self._doc_ref)


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


@pytest.fixture
def fake_client(monkeypatch):
    doc_ref = _FakeDocRef()
    client = _FakeClient(doc_ref)
    monkeypatch.setattr(firestore_client, "_client", lambda: client)
    return doc_ref


@pytest.fixture
def recording_sink():
    sink = _RecordingSink()
    event_context.set_sink(sink)
    return sink


@pytest.mark.asyncio
async def test_update_ticket_emits_step_changed_when_current_step_is_set(
    fake_client, recording_sink
) -> None:
    await firestore_client.update_ticket(REPO, ISSUE_NUMBER, current_step="planning (attempt 1)")

    assert len(recording_sink.events) == 1
    assert recording_sink.events[0] == {
        "type": "step_changed",
        "summary": "planning (attempt 1)",
    }


@pytest.mark.asyncio
async def test_update_ticket_does_not_emit_when_current_step_is_absent(
    fake_client, recording_sink
) -> None:
    await firestore_client.update_ticket(REPO, ISSUE_NUMBER, status="in_progress")

    assert recording_sink.events == []


@pytest.mark.asyncio
async def test_update_ticket_does_not_emit_when_current_step_is_none(
    fake_client, recording_sink
) -> None:
    await firestore_client.update_ticket(REPO, ISSUE_NUMBER, current_step=None)

    assert recording_sink.events == []


@pytest.mark.asyncio
async def test_append_escalation_emits_escalated_with_the_entrys_gate_and_reason(
    fake_client, recording_sink
) -> None:
    entry = EscalationEntry(at=datetime.now(UTC), reason="tests kept failing", gate="2")

    await firestore_client.append_escalation(REPO, ISSUE_NUMBER, entry)

    assert len(recording_sink.events) == 1
    assert recording_sink.events[0] == {
        "type": "escalated",
        "gate": "2",
        "summary": "tests kept failing",
    }
