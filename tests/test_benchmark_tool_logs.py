"""벤치마크 전용 Tool 로그와 실제 callback/API 연결 회귀 테스트."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import ToolMessage
from test_runtime_observation_callback import TelemetrySpy

from clio_agent_graph.observability.benchmark import ToolLogStore
from clio_agent_graph.observability.benchmark_api import app
from clio_agent_graph.runtime.observation_callback import RuntimeObservationCallback


def test_disabled_mode_does_not_create_logs_or_serialize_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "false")
    path = tmp_path / "tools.sqlite3"
    monkeypatch.setenv("CLIO_BENCHMARK_LOG_PATH", str(path))
    callback = RuntimeObservationCallback(TelemetrySpy(), {})
    call = uuid4()
    callback.on_tool_start({"name": "read"}, "input", run_id=call)
    callback.on_tool_end(object(), run_id=call)
    assert not path.exists()
    assert TestClient(app).get("/benchmark/tool-calls/boundary").status_code == 409
    assert not path.exists()


def test_callback_preserves_arguments_output_errors_and_period_pages(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "true")
    monkeypatch.setenv("CLIO_BENCHMARK_LOG_PATH", str(tmp_path / "tools.sqlite3"))
    api = TestClient(app)
    start = api.get("/benchmark/tool-calls/boundary").json()
    callback = RuntimeObservationCallback(TelemetrySpy(), {"operation": "analysis"})
    success, failure, running = uuid4(), uuid4(), uuid4()
    callback.on_tool_start({"name": "read"}, "fallback", run_id=success, inputs={"path": "a.py"})
    callback.on_tool_end(ToolMessage(content="source", tool_call_id="model-call"), run_id=success)
    callback.on_tool_start({"name": "search"}, "query", run_id=failure, parent_run_id=success)
    callback.on_tool_error(ValueError("invalid query"), run_id=failure)
    callback.on_tool_start({"name": "pending"}, "input", run_id=running)
    end = api.get("/benchmark/tool-calls/boundary").json()
    later = uuid4()
    callback.on_tool_start({"name": "later"}, "excluded", run_id=later)
    response = api.get(
        "/benchmark/tool-calls",
        params={
            "store_id": start["store_id"],
            "after": start["sequence"],
            "through": end["sequence"],
            "limit": 2,
        },
    ).json()
    records = response["items"]
    assert records[0]["arguments"] == {"path": "a.py"}
    assert records[0]["output"]["content"] == "source"
    assert records[0]["duration_seconds"] >= 0
    assert records[1]["error"] == {"type": "ValueError", "message": "invalid query"}
    assert records[1]["parent_call_id"] == str(success)
    page = api.get(
        "/benchmark/tool-calls",
        params={
            "store_id": start["store_id"],
            "after": response["next_cursor"],
            "through": end["sequence"],
            "limit": 2,
        },
    ).json()
    assert [record["status"] for record in page["items"]] == ["running"]
    assert page["next_cursor"] is None
    reopened = ToolLogStore(Path(tmp_path / "tools.sqlite3"))
    assert len(reopened.page(start["sequence"], end["sequence"], 100)["items"]) == 3


def test_parallel_callbacks_keep_every_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "true")
    path = tmp_path / "tools.sqlite3"
    monkeypatch.setenv("CLIO_BENCHMARK_LOG_PATH", str(path))
    callback = RuntimeObservationCallback(TelemetrySpy(), {})

    def invoke(index):
        call = uuid4()
        callback.on_tool_start({"name": "read"}, str(index), run_id=call)
        callback.on_tool_end({"value": index}, run_id=call)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(invoke, range(30)))
    records = ToolLogStore(path).page(0, 100, 100)["items"]
    assert len(records) == 30
    assert {record["output"]["value"] for record in records} == set(range(30))
    assert all(record["status"] == "success" for record in records)


async def _invoke_async_tool(callback):
    from langchain_core.tools import tool

    @tool
    async def read_sample(path: str) -> dict:
        """테스트 파일을 조회한다."""
        return {"path": path, "content": "async result"}

    return await read_sample.ainvoke({"path": "sample.py"}, config={"callbacks": [callback]})


def test_real_async_tool_callback_preserves_payload(monkeypatch, tmp_path) -> None:
    import asyncio

    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "true")
    path = tmp_path / "tools.sqlite3"
    monkeypatch.setenv("CLIO_BENCHMARK_LOG_PATH", str(path))
    callback = RuntimeObservationCallback(TelemetrySpy(), {"operation": "async"})
    result = asyncio.run(_invoke_async_tool(callback))
    records = ToolLogStore(path).page(0, 100, 100)["items"]
    assert len(records) == 1
    assert records[0]["arguments"] == {"path": "sample.py"}
    assert records[0]["output"] == result
    assert records[0]["status"] == "success"


def test_api_rejects_replaced_log_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "true")
    path = tmp_path / "tools.sqlite3"
    monkeypatch.setenv("CLIO_BENCHMARK_LOG_PATH", str(path))
    api = TestClient(app)
    start = api.get("/benchmark/tool-calls/boundary").json()
    path.unlink()
    result = api.get(
        "/benchmark/tool-calls",
        params={
            "after": 0,
            "through": 0,
            "store_id": start["store_id"],
        },
    )
    assert result.status_code == 409
