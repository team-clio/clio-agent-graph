"""Clio 그래프 노드가 공유하는 상태 계약."""

from operator import or_
from typing import Annotated, Any, Literal, TypedDict

RequestType = Literal["process_report", "analyze_issue"]
MatchAction = Literal["link_existing", "create_new", "needs_review"]
QualityStatus = Literal["passed", "retry", "needs_review"]


class ClioState(TypedDict, total=False):
    """Root Graph와 서브그래프가 공유하는 실행 상태."""

    # API Server가 전달한 원본 요청과 검증 후 펼친 공통 필드.
    request: dict[str, Any]
    request_id: str
    request_type: RequestType
    project_id: str
    report_id: str
    issue_id: str

    # 병렬·중첩 그래프에서도 중복 없이 완료 노드를 합친다.
    completed_nodes: Annotated[dict[str, bool], or_]

    # Report Processing Graph의 산출물.
    normalized_report: dict[str, Any]
    issue_candidates: list[dict[str, Any]]
    match_decision: dict[str, Any]

    # Issue Analysis Graph의 산출물.
    context_snapshot: dict[str, Any]
    analysis_queries: dict[str, list[str]]
    document_evidence: list[dict[str, Any]]
    code_evidence: list[dict[str, Any]]
    history_evidence: list[dict[str, Any]]
    issue_analysis: dict[str, Any]
    resolution_plan: dict[str, Any]
    quality_result: dict[str, Any]

    # 공통 완료 상태.
    status: Literal["completed", "needs_review", "failed"]
    result: dict[str, Any]
    error: dict[str, Any] | None
