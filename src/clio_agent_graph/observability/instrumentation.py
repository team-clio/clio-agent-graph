"""Graph node와 Runnable에 공통 trace·metric 경계를 적용한다."""

import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import ValidationError

from clio_agent_graph.observability.context import TelemetryEnvelope
from clio_agent_graph.observability.telemetry import ClioTelemetry, get_telemetry

Node = Callable[[dict[str, Any]], dict[str, object] | Awaitable[dict[str, object]]]


def _attributes(state: Mapping[str, object], *, node: str | None = None) -> dict[str, object]:
    values: dict[str, object] = {}
    if node:
        values["clio.node"] = node
    for source, target in (
        ("request_type", "clio.request.type"),
        ("request_id", "clio.request.id"),
        ("workflow_run_id", "clio.workflow.run_id"),
    ):
        value = state.get(source)
        if isinstance(value, str | int):
            values[target] = value
    return values


def _carrier(state: Mapping[str, object], telemetry: ClioTelemetry) -> dict[str, str] | None:
    value = state.get("telemetry")
    if not isinstance(value, Mapping):
        return None
    try:
        envelope = TelemetryEnvelope.model_validate(dict(value))
    except ValidationError:
        telemetry.counter(
            "clio.telemetry.context.invalid.total",
            attributes={"outcome": "rejected"},
        )
        telemetry.event("telemetry.context.rejected", outcome="new_trace")
        return None
    return envelope.carrier()


def _error_kind(error: Exception) -> str:
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "limit" in name or "recursion" in name:
        return "limit"
    if "validation" in name or isinstance(error, ValueError):
        return "validation"
    if "repository" in name or "server" in name or "connection" in name:
        return "dependency"
    return "unexpected"


def _record_node_result(
    telemetry: ClioTelemetry,
    name: str,
    result: Mapping[str, object],
) -> None:
    if name == "quality_gate":
        quality = result.get("quality_result")
        if isinstance(quality, Mapping):
            outcome = quality.get("status")
            if isinstance(outcome, str):
                telemetry.counter(
                    "clio.quality_gate.total",
                    attributes={"outcome": outcome},
                )
                if outcome == "retry":
                    telemetry.counter("clio.quality_gate.retry.total")
                elif outcome == "needs_review":
                    telemetry.counter(
                        "clio.analysis.needs_review.total",
                        attributes={"reason": "quality_gate"},
                    )
            reasons = quality.get("reasons")
            if isinstance(reasons, list):
                for reason in reasons:
                    if isinstance(reason, str) and "citation" in reason.lower():
                        telemetry.counter(
                            "clio.citation.rejected.total",
                            attributes={"reason": _citation_reason(reason)},
                        )
    if name == "mark_analysis_for_review":
        telemetry.counter(
            "clio.analysis.needs_review.total",
            attributes={"reason": "quality_or_limit"},
        )


def _citation_reason(reason: str) -> str:
    lowered = reason.lower()
    if "revision" in lowered or "commit" in lowered:
        return "snapshot_mismatch"
    if "not available" in lowered:
        return "outside_snapshot"
    return "missing_or_invalid"


def observe_node(name: str, node: Node) -> Node:
    """Node의 업무 입출력을 기록하지 않고 실행 결과와 지연만 계측한다."""

    if inspect.iscoroutinefunction(node):

        async def async_observed(state: dict[str, Any]) -> dict[str, object]:
            telemetry = get_telemetry()
            started = time.perf_counter()
            try:
                with telemetry.span(f"clio.node.{name}", attributes=_attributes(state, node=name)):
                    result = await node(state)
                    _record_node_result(telemetry, name, result)
            except Exception as error:
                telemetry.counter(
                    "clio.node.failure.total",
                    attributes={"node": name, "error_kind": _error_kind(error)},
                )
                raise
            finally:
                telemetry.histogram(
                    "clio.node.duration",
                    time.perf_counter() - started,
                    attributes={"node": name},
                )
            telemetry.counter("clio.node.total", attributes={"node": name, "outcome": "success"})
            return result

        return async_observed

    def observed(state: dict[str, Any]) -> dict[str, object]:
        telemetry = get_telemetry()
        started = time.perf_counter()
        try:
            with telemetry.span(f"clio.node.{name}", attributes=_attributes(state, node=name)):
                result = node(state)
                assert not inspect.isawaitable(result)
                _record_node_result(telemetry, name, result)
        except Exception as error:
            telemetry.counter(
                "clio.node.failure.total",
                attributes={"node": name, "error_kind": _error_kind(error)},
            )
            raise
        finally:
            telemetry.histogram(
                "clio.node.duration",
                time.perf_counter() - started,
                attributes={"node": name},
            )
        telemetry.counter("clio.node.total", attributes={"node": name, "outcome": "success"})
        return result

    return observed


def observe_workflow(name: str, runnable: Runnable[Any, dict[str, object]]) -> RunnableLambda:
    """비동기 dispatch carrier를 parent로 사용해 workflow 전체를 계측한다."""

    def invoke(state: dict[str, Any]) -> dict[str, object]:
        return _invoke_workflow(name, runnable, state)

    async def ainvoke(state: dict[str, Any]) -> dict[str, object]:
        telemetry = get_telemetry()
        started = time.perf_counter()
        attributes = _attributes(state)
        outcome = "success"
        try:
            with telemetry.span(
                f"clio.workflow.{name}",
                attributes=attributes,
                carrier=_carrier(state, telemetry),
            ):
                telemetry.event("workflow.started", request_type=state.get("request_type", name))
                return await runnable.ainvoke(state)
        except Exception as error:
            outcome = "failure"
            telemetry.counter(
                "clio.workflow.failure.total",
                attributes={"request_type": name, "error_kind": _error_kind(error)},
            )
            raise
        finally:
            _finish_workflow(telemetry, name, outcome, started)

    return RunnableLambda(invoke, ainvoke)


def _invoke_workflow(
    name: str,
    runnable: Runnable[Any, dict[str, object]],
    state: dict[str, Any],
) -> dict[str, object]:
    telemetry = get_telemetry()
    started = time.perf_counter()
    outcome = "success"
    try:
        with telemetry.span(
            f"clio.workflow.{name}",
            attributes=_attributes(state),
            carrier=_carrier(state, telemetry),
        ):
            telemetry.event("workflow.started", request_type=state.get("request_type", name))
            return runnable.invoke(state)
    except Exception as error:
        outcome = "failure"
        telemetry.counter(
            "clio.workflow.failure.total",
            attributes={"request_type": name, "error_kind": _error_kind(error)},
        )
        raise
    finally:
        _finish_workflow(telemetry, name, outcome, started)


def _finish_workflow(
    telemetry: ClioTelemetry,
    name: str,
    outcome: str,
    started: float,
) -> None:
    attributes = {"request_type": name, "outcome": outcome}
    telemetry.counter("clio.workflow.total", attributes=attributes)
    telemetry.histogram(
        "clio.workflow.duration",
        time.perf_counter() - started,
        attributes=attributes,
    )
    telemetry.event("workflow.completed", request_type=name, outcome=outcome)
