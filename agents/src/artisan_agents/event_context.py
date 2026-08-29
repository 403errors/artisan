"""Ambient event-sink context for the orchestrator. Set once per Pub/Sub delivery
(`dispatch.handle_event`) so every function down the call chain — `tracing.gate_span`,
`firestore_client.update_ticket`/`append_escalation`, `_run_agent.run_structured`, etc. — can emit
without threading a `sink` parameter through every signature.

`asyncio.gather`-based fan-out (`gate2._run_domain_experts`) inherits this correctly: Python copies
the current `Context` into each new `Task` at creation. Each FastAPI request already runs in its
own asyncio Task, so a `set_sink` call in one request's `handle_event` never leaks into another
request — no explicit reset needed."""

from contextvars import ContextVar

from artisan_shared.event_log import EventSink, NoOpEventSink

_current_sink: ContextVar[EventSink] = ContextVar("artisan_event_sink", default=NoOpEventSink())


def set_sink(sink: EventSink) -> None:
    _current_sink.set(sink)


def current_sink() -> EventSink:
    return _current_sink.get()
