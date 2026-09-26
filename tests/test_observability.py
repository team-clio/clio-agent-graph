import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from clio_agent_graph.observability import ClioTelemetry, TelemetryEnvelope
from clio_agent_graph.observability.telemetry import (
    DURATION_BUCKET_BOUNDARIES_SECONDS,
    DURATION_HISTOGRAMS,
    _duration_views,
)


def _telemetry() -> tuple[ClioTelemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return (
        ClioTelemetry(
            provider.get_tracer("test"),
            MeterProvider().get_meter("test"),
        ),
        exporter,
    )


def test_telemetry_envelope_accepts_valid_w3c_context() -> None:
    envelope = TelemetryEnvelope(
        traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    )

    assert envelope.carrier() == {"traceparent": envelope.traceparent}


@pytest.mark.parametrize(
    "traceparent",
    [
        "invalid",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
    ],
)
def test_telemetry_envelope_rejects_invalid_context(traceparent: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryEnvelope(traceparent=traceparent)


def test_child_span_continues_remote_trace() -> None:
    telemetry, exporter = _telemetry()
    carrier = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}

    with telemetry.span("clio.workflow", carrier=carrier):
        propagated = telemetry.inject_current()

    span = exporter.get_finished_spans()[0]
    assert format(span.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert propagated["traceparent"].startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")


def test_attributes_ignore_payload_shaped_values() -> None:
    telemetry, exporter = _telemetry()

    with telemetry.span(
        "clio.node",
        attributes={"node": "search_code", "payload": {"secret": "value"}},
    ):
        pass

    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes["node"] == "search_code"
    assert "payload" not in attributes


def test_duration_histograms_use_seconds_scale_buckets() -> None:
    views = _duration_views()

    assert len(views) == len(DURATION_HISTOGRAMS)
    assert DURATION_BUCKET_BOUNDARIES_SECONDS[:5] == (0.005, 0.01, 0.025, 0.05, 0.1)
    assert DURATION_BUCKET_BOUNDARIES_SECONDS[-2:] == (10.0, 30.0)
