"""OpenTelemetry -> Cloud Trace, one span per gate decision (SYSTEM_DESIGN.md §10). Every span
carries `ticket_id`, `gate`, and `decision` so a ticket's full history is reconstructable from
Cloud Trace alone."""

from contextlib import contextmanager
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

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


@contextmanager
def gate_span(
    ticket_id: str, gate: Literal["1", "2", "3"], decision: Literal["proceed", "ask", "escalate"]
):
    tracer = trace.get_tracer("artisan.orchestrator")
    with tracer.start_as_current_span(f"gate.{gate}.{decision}") as span:
        span.set_attribute("ticket_id", ticket_id)
        span.set_attribute("gate", gate)
        span.set_attribute("decision", decision)
        yield span
