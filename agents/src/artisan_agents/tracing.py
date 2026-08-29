"""OpenTelemetry -> Cloud Trace, one span per gate decision (SYSTEM_DESIGN.md §10). Every span
carries `ticket_id`, `gate`, and `decision` so a ticket's full history is reconstructable from
Cloud Trace alone."""

from contextlib import asynccontextmanager
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

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
):
    tracer = trace.get_tracer("artisan.orchestrator")
    with tracer.start_as_current_span(f"gate.{gate}.{decision}") as span:
        span.set_attribute("ticket_id", ticket_id)
        span.set_attribute("gate", gate)
        span.set_attribute("decision", decision)
        trace_id_hex = format(span.get_span_context().trace_id, "032x")
        yield span
    # Sprint 5: trace_ids was previously write-once-dead — this closes the loop so the dashboard's
    # drill-in view can deep-link to Cloud Trace for this exact decision.
    await firestore_client.append_trace_id(ticket_id, trace_id_hex)
