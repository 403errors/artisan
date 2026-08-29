"""Unit tests for `tracing.gate_span`'s event-log emission (Sprint 6) — `append_trace_id`'s own
behavior is exercised elsewhere (test_firestore_client.py, real-Firestore integration); this file
only checks that every `gate_span` call also emits a `gate_decision` event on the ambient sink."""

import pytest

from artisan_agents import event_context, tracing
from artisan_shared.event_log import NoOpEventSink


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"


@pytest.fixture(autouse=True)
def _stub_append_trace_id(monkeypatch):
    async def _noop(ticket_id: str, trace_id: str, label: str) -> None:
        return None

    monkeypatch.setattr(tracing.firestore_client, "append_trace_id", _noop)


@pytest.fixture
def recording_sink():
    sink = _RecordingSink()
    event_context.set_sink(sink)
    return sink


@pytest.mark.asyncio
async def test_gate_span_emits_a_gate_decision_event(recording_sink) -> None:
    async with tracing.gate_span("ticket-1", "2", "proceed"):
        pass

    assert len(recording_sink.events) == 1
    event = recording_sink.events[0]
    assert event["type"] == "gate_decision"
    assert event["gate"] == "2"
    assert "proceed" in event["summary"]


@pytest.mark.asyncio
async def test_gate_span_records_explicit_label_when_given(monkeypatch) -> None:
    recorded = []

    async def _record(ticket_id: str, trace_id: str, label: str) -> None:
        recorded.append(label)

    monkeypatch.setattr(tracing.firestore_client, "append_trace_id", _record)

    async with tracing.gate_span("ticket-1", "2", "proceed", label="Gate 2: routing decided"):
        pass
    async with tracing.gate_span("ticket-1", "2", "proceed"):
        pass

    assert recorded == ["Gate 2: routing decided", "Gate 2: proceed"]


@pytest.mark.asyncio
async def test_gate_span_still_emits_for_every_decision_kind(recording_sink) -> None:
    for decision in ("proceed", "ask", "retry", "escalate"):
        async with tracing.gate_span("ticket-1", "1", decision):
            pass

    assert [e["summary"] for e in recording_sink.events] == [
        "Gate 1: proceed",
        "Gate 1: ask",
        "Gate 1: retry",
        "Gate 1: escalate",
    ]
