"""OpenTelemetry -> Cloud Trace, one span per gate decision (SYSTEM_DESIGN.md §10). Every span
carries `ticket_id`, `gate`, and `decision` so a ticket's full history is reconstructable from
Cloud Trace alone."""

from contextlib import asynccontextmanager
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from artisan_agents.event_context import current_sink
from artisan_agents.gcp import firestore_client

_configured = False


def setup_tracing() -> None:
    """Idempotent: safe to call at every app startup without double-registering the exporter."""
    global _configured
    if _configured:
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


@asynccontextmanager
async def gate_span(
    ticket_id: str,
    gate: Literal["1", "2", "3"],
    decision: Literal["proceed", "ask", "retry", "escalate"],
    *,
    label: str | None = None,
):
    """`label` names which specific decision point this span is for (e.g. "Gate 2: verification
    passed") — plain (gate, decision) isn't enough on its own since a gate can reach the same
    `decision` value from more than one call site (e.g. Gate 2's routing "proceed" vs. its
    verification-passed "proceed"). Defaults to the generic `f"Gate {gate}: {decision}"` when the
    caller has nothing more specific to say."""
    resolved_label = label or f"Gate {gate}: {decision}"
    tracer = trace.get_tracer("artisan.orchestrator")
    with tracer.start_as_current_span(f"gate.{gate}.{decision}") as span:
        span.set_attribute("ticket_id", ticket_id)
        span.set_attribute("gate", gate)
        span.set_attribute("decision", decision)
        trace_id_hex = format(span.get_span_context().trace_id, "032x")
        yield span
    # Sprint 6 Phase 6.1 fix: root-caused live (docs/CONTEXT.md Milestone 10) — provider
    # registration was already correct (confirmed via a live diagnostic build: our TracerProvider
    # wins, gate_span runs on it), so the gap was BatchSpanProcessor's async batching (default
    # 5s schedule delay) racing Cloud Run's request-scoped/scale-to-zero lifecycle: nothing forced
    # a flush before the instance could be frozen. force_flush() here makes each gate span export
    # synchronously instead of trusting the batch timer to fire before the container is paused. A
    # short timeout keeps this from blocking the gate decision if Cloud Trace is ever slow/down.
    # `force_flush` only exists on a real TracerProvider — if setup_tracing() was never called
    # (e.g. in tests that never start the app), get_tracer_provider() returns OpenTelemetry's
    # default no-op ProxyTracerProvider, which has nothing to flush.
    force_flush = getattr(trace.get_tracer_provider(), "force_flush", None)
    if force_flush is not None:
        force_flush(timeout_millis=5000)
    # Sprint 5: trace_ids was previously write-once-dead — this closes the loop so the dashboard's
    # drill-in view can deep-link to Cloud Trace for this exact decision.
    await firestore_client.append_trace_id(ticket_id, trace_id_hex, resolved_label)
    # Sprint 6: every gate_span call site becomes a `gate_decision` event for free — the dashboard's
    # activity feed reads these directly rather than round-tripping through Cloud Trace.
    await current_sink().emit(
        type="gate_decision",
        gate=gate,
        summary=f"Gate {gate}: {decision}",
    )
