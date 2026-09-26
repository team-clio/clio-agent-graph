"""OpenTelemetry SDK를 Clio의 작은 관측 계약으로 감싼다."""

import json
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.propagators.textmap import Getter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger("clio.observability")
INSTRUMENTATION_NAME = "clio-agent-graph"
DURATION_BUCKET_BOUNDARIES_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
DURATION_HISTOGRAMS = (
    "clio.node.duration",
    "clio.model.call.duration",
    "clio.tool.call.duration",
    "clio.agent.run.duration",
    "clio.workflow.duration",
)


class _CarrierGetter(Getter[Mapping[str, str]]):
    def get(self, carrier: Mapping[str, str], key: str) -> list[str] | None:
        value = carrier.get(key)
        return [value] if value is not None else None

    def keys(self, carrier: Mapping[str, str]) -> list[str]:
        return list(carrier)


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _signal_endpoint(signal: str) -> str:
    specific = os.getenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT", "").strip()
    if specific:
        return specific
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    return f"{base}/v1/{signal}"


def _safe_attributes(attributes: Mapping[str, object] | None) -> dict[str, Any]:
    if not attributes:
        return {}
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if isinstance(value, str | bool | int | float):
            safe[key] = value
    return safe


def _duration_views() -> tuple[View, ...]:
    """짧은 노드 실행부터 긴 모델 호출까지 p95를 과대평가하지 않도록 구간을 고정한다."""
    return tuple(
        View(
            instrument_name=name,
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=DURATION_BUCKET_BOUNDARIES_SECONDS
            ),
        )
        for name in DURATION_HISTOGRAMS
    )


class ClioTelemetry:
    """Trace·metric·event를 기록하되 업무 payload는 받지 않는 adapter."""

    def __init__(self, tracer: Tracer, meter: Meter) -> None:
        self._tracer = tracer
        self._meter = meter
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._propagator = TraceContextTextMapPropagator()
        self._getter = _CarrierGetter()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
        carrier: Mapping[str, str] | None = None,
    ) -> Iterator[Span]:
        parent: Context | None = None
        if carrier:
            parent = self._propagator.extract(carrier, getter=self._getter)
        with self._tracer.start_as_current_span(
            name,
            context=parent,
            attributes=_safe_attributes(attributes),
        ) as span:
            try:
                yield span
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise

    def counter(
        self,
        name: str,
        *,
        value: int = 1,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        instrument = self._counters.get(name)
        if instrument is None:
            instrument = self._meter.create_counter(name)
            self._counters[name] = instrument
        instrument.add(value, _safe_attributes(attributes))

    def histogram(
        self,
        name: str,
        value: float,
        *,
        unit: str = "s",
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        instrument = self._histograms.get(name)
        if instrument is None:
            instrument = self._meter.create_histogram(name, unit=unit)
            self._histograms[name] = instrument
        instrument.record(value, _safe_attributes(attributes))

    def inject_current(self) -> dict[str, str]:
        carrier: dict[str, str] = {}
        self._propagator.inject(carrier)
        return carrier

    def trace_id(self) -> str | None:
        context = trace.get_current_span().get_span_context()
        if not context.is_valid:
            return None
        return trace.format_trace_id(context.trace_id)

    def event(self, name: str, **fields: object) -> None:
        payload = {"event": name, "trace_id": self.trace_id(), **_safe_attributes(fields)}
        logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _build_telemetry() -> ClioTelemetry:
    resource = Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME", INSTRUMENTATION_NAME)}
    )
    tracer_provider = TracerProvider(resource=resource)
    metric_readers = []
    if _enabled(os.getenv("CLIO_OTEL_ENABLED")):
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_signal_endpoint("traces")))
        )
        metric_readers.append(
            PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=_signal_endpoint("metrics")))
        )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
        views=_duration_views(),
    )
    return ClioTelemetry(
        tracer_provider.get_tracer(INSTRUMENTATION_NAME),
        meter_provider.get_meter(INSTRUMENTATION_NAME),
    )


@lru_cache(maxsize=1)
def get_telemetry() -> ClioTelemetry:
    """프로세스에서 공유하는 telemetry adapter를 반환한다."""

    return _build_telemetry()
