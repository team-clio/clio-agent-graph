"""Root graph와 각 workflow가 공유하는 명시적인 상태 계약."""

from operator import or_
from typing import Annotated, Any, Literal, TypedDict

RequestType = Literal[
    "process_report",
    "analyze_issue",
    "document_added",
    "document_deleted",
    "repository_added",
    "repository_removed",
    "repository_changed",
]
MatchAction = Literal["link_existing", "create_new", "needs_review"]
QualityStatus = Literal["passed", "retry", "needs_review"]


class RequestState(TypedDict, total=False):
    """요청 검증과 root routing에 필요한 공통 상태."""

    request: dict[str, Any]
    request_id: str
    request_type: RequestType
    project_id: str
    bug_id: str
    workflow_run_id: int
    workflow_replayed: bool
    issue_id: str
    document_id: str
    document_title: str
    document_markdown: str
    source_metadata: dict[str, Any]
    repository_id: str
    repository_source_uri: str
    branch: str
    revision: str
    before_commit: str
    after_commit: str

    completed_nodes: Annotated[dict[str, bool], or_]


class ReportProcessingState(TypedDict, total=False):
    """리포트 정규화와 기존 이슈 매칭 상태."""

    normalized_report: dict[str, Any]
    issue_candidates: list[dict[str, Any]]
    match_decision: dict[str, Any]


class IssueAnalysisState(TypedDict, total=False):
    """고정 snapshot을 사용하는 이슈 분석 상태."""

    context_snapshot: dict[str, Any]
    analysis_queries: dict[str, list[str]]
    document_evidence: list[dict[str, Any]]
    code_evidence: list[dict[str, Any]]
    history_evidence: list[dict[str, Any]]
    bug_context: dict[str, Any]
    issue_analysis: dict[str, Any]
    analysis_error: str
    resolution_plan: dict[str, Any]
    risk_assessment: dict[str, Any] | None
    quality_result: dict[str, Any]
    quality_attempt: int


class MemorySyncState(TypedDict, total=False):
    """문서 및 repository 동기화 상태."""

    document_sync: dict[str, Any]
    repository_sync: dict[str, Any]
    code_change: dict[str, Any]


class ResultState(TypedDict, total=False):
    """모든 workflow가 root graph에 반환하는 공통 결과."""

    status: Literal["completed", "needs_review", "failed"]
    result: dict[str, Any]
    error: dict[str, Any] | None


class IssueWorkflowState(RequestState, IssueAnalysisState, ResultState, total=False):
    """직접 이슈 분석 subgraph의 상태."""


class ReportWorkflowState(
    RequestState,
    ReportProcessingState,
    IssueAnalysisState,
    ResultState,
    total=False,
):
    """리포트 매칭과 선택적 이슈 분석 subgraph의 상태."""


class MemoryWorkflowState(RequestState, MemorySyncState, ResultState, total=False):
    """PCM 및 repository 동기화 subgraph의 상태."""


class ClioState(
    RequestState,
    ReportProcessingState,
    IssueAnalysisState,
    MemorySyncState,
    ResultState,
    total=False,
):
    """Root graph가 subgraph 사이에서 운반하는 전체 상태의 합성 타입."""
