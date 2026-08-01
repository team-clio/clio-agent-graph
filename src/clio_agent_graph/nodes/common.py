"""Root Graph에서 사용하는 결정적 공통 노드."""

from typing import Literal

from clio_agent_graph.requests import (
    AnalyzeIssueRequest,
    CodeChangeRequest,
    DocumentSyncRequest,
    ProcessReportRequest,
    RepositorySyncRequest,
    graph_request_adapter,
)
from clio_agent_graph.state import ClioState


def validate_request(state: ClioState) -> dict[str, object]:
    """판별 공용체로 요청을 검증하고 라우팅 필드를 상태에 펼친다."""

    request = graph_request_adapter.validate_python(state.get("request"))
    update: dict[str, object] = {
        "request": request.model_dump(),
        "request_id": request.request_id,
        "request_type": request.request_type,
        "project_id": request.project_id,
        "completed_nodes": {"validate_request": True},
        "error": None,
    }
    if isinstance(request, ProcessReportRequest):
        update["report_id"] = request.payload.report_id
    elif isinstance(request, AnalyzeIssueRequest):
        update["issue_id"] = request.payload.issue_id
    elif isinstance(request, DocumentSyncRequest):
        update.update(
            {"document_id": request.payload.document_id, "revision": request.payload.revision}
        )
    elif isinstance(request, RepositorySyncRequest):
        update.update(
            {
                "repository_id": request.payload.repository_id,
                "branch": request.payload.branch,
                "revision": request.payload.commit,
            }
        )
    elif isinstance(request, CodeChangeRequest):
        update.update(
            {
                "repository_id": request.payload.repository_id,
                "branch": request.payload.branch,
                "before_commit": request.payload.before_commit,
                "after_commit": request.payload.after_commit,
            }
        )
    return update


def route_request(state: ClioState) -> dict[str, object]:
    """검증된 요청을 라우팅할 준비를 마친다."""

    return {"completed_nodes": {"route_request": True}}


def select_subgraph(
    state: ClioState,
) -> Literal[
    "report_processing",
    "issue_analysis",
    "document_sync",
    "repository_sync",
    "code_change_sync",
]:
    """검증된 type을 서브그래프 이름으로 결정적으로 매핑한다."""

    routes = {
        "process_report": "report_processing",
        "analyze_issue": "issue_analysis",
        "document_added": "document_sync",
        "document_deleted": "document_sync",
        "repository_added": "repository_sync",
        "repository_removed": "repository_sync",
        "repository_changed": "code_change_sync",
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
