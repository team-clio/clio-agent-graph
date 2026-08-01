"""Root Graph에서 사용하는 결정적 공통 노드."""

from typing import Literal

from clio_agent_graph.requests import (
    AnalyzeIssueRequest,
    ProcessReportRequest,
    graph_request_adapter,
)
from clio_agent_graph.state import ClioState


def validate_request(state: ClioState) -> dict[str, object]:
    """판별 공용체로 요청을 검증하고 라우팅 필드를 상태에 펼친다."""

    request = graph_request_adapter.validate_python(state.get("request"))
    update: dict[str, object] = {
        "request": request.model_dump(),
        "request_id": request.request_id,
        "request_type": request.type,
        "project_id": request.project_id,
        "completed_nodes": {"validate_request": True},
        "error": None,
    }
    if isinstance(request, ProcessReportRequest):
        update["report_id"] = request.payload.report_id
    elif isinstance(request, AnalyzeIssueRequest):
        update["issue_id"] = request.payload.issue_id
    return update


def route_request(state: ClioState) -> Literal["report_processing", "issue_analysis"]:
    """검증된 type을 서브그래프 이름으로 결정적으로 매핑한다."""

    routes = {
        "process_report": "report_processing",
        "analyze_issue": "issue_analysis",
    }
    return routes[state["request_type"]]


def finalize_request(state: ClioState) -> dict[str, object]:
    """서브그래프의 상태를 공통 완료 결과로 정리한다."""

    status = state.get("status", "completed")
    result = state.get(
        "result",
        {
            "request_id": state["request_id"],
            "request_type": state["request_type"],
        },
    )
    return {
        "status": status,
        "result": result,
        "completed_nodes": {"finalize_request": True},
    }
