from uuid import uuid4

from clio_agent_graph.runtime.observation_callback import RuntimeObservationCallback


class TelemetrySpy:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, object]]] = []
        self.histograms: list[tuple[str, float, dict[str, object]]] = []

    def counter(self, name: str, *, attributes: dict[str, object]) -> None:
        self.counters.append((name, attributes))

    def histogram(
        self,
        name: str,
        value: float,
        *,
        attributes: dict[str, object],
    ) -> None:
        self.histograms.append((name, value, attributes))


def test_callback_records_actual_model_and_tool_boundaries_without_payload() -> None:
    telemetry = TelemetrySpy()
    callback = RuntimeObservationCallback(
        telemetry,  # type: ignore[arg-type]
        {"model": "provider:model", "operation": "analysis"},
    )
    model_run = uuid4()
    tool_run = uuid4()

    callback.on_chat_model_start({}, [["secret prompt"]], run_id=model_run)
    callback.on_llm_end(object(), run_id=model_run)
    callback.on_tool_start(
        {"name": "read_issue_history"},
        "secret tool input",
        run_id=tool_run,
    )
    callback.on_tool_end({"secret": "result"}, run_id=tool_run)

    assert telemetry.counters == [
        (
            "clio.model.call.total",
            {"model": "provider:model", "operation": "analysis", "outcome": "success"},
        ),
        ("clio.tool.call.total", {"tool": "read_issue_history", "outcome": "success"}),
    ]
    assert {item[0] for item in telemetry.histograms} == {
        "clio.model.call.duration",
        "clio.tool.call.duration",
    }
    assert "secret prompt" not in str(telemetry.counters)
    assert "secret tool input" not in str(telemetry.counters)


def test_callback_maps_tool_failure_to_bounded_error_kind() -> None:
    telemetry = TelemetrySpy()
    callback = RuntimeObservationCallback(telemetry, {})  # type: ignore[arg-type]
    tool_run = uuid4()

    callback.on_tool_start({"name": "read_repository"}, "ignored", run_id=tool_run)
    callback.on_tool_error(ConnectionError("credential=secret"), run_id=tool_run)

    assert telemetry.counters == [
        (
            "clio.tool.call.total",
            {"tool": "read_repository", "outcome": "failure", "error_kind": "dependency"},
        )
    ]
