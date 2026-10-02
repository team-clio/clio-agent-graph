"""벤치마크 모드에서만 사용하는 로그 경계와 페이지 조회 HTTP API."""

from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query

from clio_agent_graph.observability.benchmark import ToolLogStore, get_tool_log_store

app = FastAPI()


def _store() -> ToolLogStore:
    store = get_tool_log_store()
    if store is None:
        raise HTTPException(409, "Tool logs require CLIO_BENCHMARK_MODE=true")
    return store


@app.get("/benchmark/tool-calls/boundary")
def boundary() -> dict[str, Any]:
    return _store().boundary()


@app.get("/benchmark/tool-calls")
def tool_calls(
    after: Annotated[int, Query(ge=0)],
    through: Annotated[int, Query(ge=0)],
    store_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    if through < after:
        raise HTTPException(422, "through must be greater than or equal to after")
    try:
        return _store().page(after, through, limit, store_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
