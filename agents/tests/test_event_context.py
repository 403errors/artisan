"""Unit tests for the ambient event-sink ContextVar."""

from artisan_agents import event_context
from artisan_shared.event_log import EventSink, NoOpEventSink


def test_current_sink_defaults_to_a_noop_sink() -> None:
    assert isinstance(event_context.current_sink(), NoOpEventSink)


def test_set_sink_installs_the_given_sink() -> None:
    sink = EventSink(client=None, ticket_id="t1", enabled=False)
    event_context.set_sink(sink)
    assert event_context.current_sink() is sink
