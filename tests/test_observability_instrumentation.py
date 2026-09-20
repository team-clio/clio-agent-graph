from langchain_core.runnables import RunnableLambda
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clio_agent_graph.observability.instrumentation import observe_node, observe_workflow
from clio_agent_graph.observability.telemetry import ClioTelemetry


def _telemetry() -> tuple[ClioTelemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return (
        ClioTelemetry(provider.get_tracer("test"), MeterProvider().get_meter("test")),
        exporter,
    )


def test_observed_workflow_continues_dispatched_trace(monkeypatch) -> None:
    telemetry, exporter = _telemetry()
    monkeypatch.setattr(
        "clio_agent_graph.observability.instrumentation.get_telemetry", lambda: telemetry
    )
    workflow = observe_workflow(
        "analyze_issue",
        RunnableLambda(observe_node("search_code", lambda _state: {"result": {}})),
    )

    workflow.invoke(
        {
            "request_type": "analyze_issue",
            "telemetry": {
                "traceparent": ("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
            },
        }
    )

    spans = {span.name: span for span in exporter.get_finished_spans()}
    workflow_span = spans["clio.workflow.analyze_issue"]
    node_span = spans["clio.node.search_code"]
    assert format(workflow_span.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert node_span.parent.span_id == workflow_span.context.span_id


def test_invalid_envelope_starts_a_new_trace(monkeypatch) -> None:
    telemetry, exporter = _telemetry()
    monkeypatch.setattr(
        "clio_agent_graph.observability.instrumentation.get_telemetry", lambda: telemetry
    )
    workflow = observe_workflow("analyze_issue", RunnableLambda(lambda state: state))

    result = workflow.invoke(
        {"request_type": "analyze_issue", "telemetry": {"traceparent": "invalid"}}
    )

    assert result["request_type"] == "analyze_issue"
    assert exporter.get_finished_spans()[0].context.is_valid
