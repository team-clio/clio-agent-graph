"""LangChain callback으로 실제 LLM·Tool 호출 경계를 계측한다."""

import time
from threading import Lock
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from clio_agent_graph.observability.telemetry import ClioTelemetry


class RuntimeObservationCallback(BaseCallbackHandler):
    """입출력 payload를 보지 않고 호출 이름·결과·지연만 기록한다."""

    def __init__(self, telemetry: ClioTelemetry, model_attributes: dict[str, object]) -> None:
        self._telemetry = telemetry
        self._model_attributes = model_attributes
        self._model_runs: dict[UUID, float] = {}
        self._tool_runs: dict[UUID, tuple[str, float]] = {}
        self._lock = Lock()

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._start_model(run_id)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._start_model(run_id)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish_model(run_id, "success")

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish_model(run_id, "failure", _error_kind(error))

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name")
        safe_name = name if isinstance(name, str) and name else "unknown"
        with self._lock:
            self._tool_runs[run_id] = (safe_name, time.perf_counter())

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish_tool(run_id, "success")

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish_tool(run_id, "failure", _error_kind(error))

    def _start_model(self, run_id: UUID) -> None:
        with self._lock:
            self._model_runs.setdefault(run_id, time.perf_counter())

    def _finish_model(
        self,
        run_id: UUID,
        outcome: str,
        error_kind: str | None = None,
    ) -> None:
        with self._lock:
            started = self._model_runs.pop(run_id, None)
        if started is None:
            return
        attributes = {**self._model_attributes, "outcome": outcome}
        if error_kind:
            attributes["error_kind"] = error_kind
        self._telemetry.counter("clio.model.call.total", attributes=attributes)
        self._telemetry.histogram(
            "clio.model.call.duration",
            time.perf_counter() - started,
            attributes=attributes,
        )

    def _finish_tool(
        self,
        run_id: UUID,
        outcome: str,
        error_kind: str | None = None,
    ) -> None:
        with self._lock:
            entry = self._tool_runs.pop(run_id, None)
        if entry is None:
            return
        name, started = entry
        attributes: dict[str, object] = {"tool": name, "outcome": outcome}
        if error_kind:
            attributes["error_kind"] = error_kind
        self._telemetry.counter("clio.tool.call.total", attributes=attributes)
        self._telemetry.histogram(
            "clio.tool.call.duration",
            time.perf_counter() - started,
            attributes=attributes,
        )


def _error_kind(error: BaseException) -> str:
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "validation" in name or isinstance(error, ValueError):
        return "validation"
    if "connection" in name or "repository" in name:
        return "dependency"
    return "unexpected"
