"""Report Normalizer와 Matcher가 공유하는 독립 실행 그래프 상태 계약."""

from typing import TypedDict

from clio_agent_graph.runtime.agent_runtime import ToolCallRecord
from clio_agent_graph.workflows.reporting.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchDecision,
)
from clio_agent_graph.workflows.reporting.normalization.models import (
    NormalizedReport,
    NormalizeReportInput,
)


class ReportMatchingInput(TypedDict):
    """NM과 RM을 실행하기 위해 Clio Server가 전달하는 입력."""

    project_id: int
    bug_id: int
    bug_report: NormalizeReportInput


class ReportMatchingState(TypedDict, total=False):
    """한 번의 Report Matching 실행 동안 노드가 읽고 쓰는 내부 상태."""

    bug_report: NormalizeReportInput
    project_id: int
    bug_id: int
    normalized_report: NormalizedReport
    normalization_tool_calls: list[ToolCallRecord]
    issue_candidates: list[IssueCandidate]
    retrieval_tool_calls: list[ToolCallRecord]
    candidate_comparisons: list[CandidateComparison]
    matching_tool_calls: list[ToolCallRecord]
    match_decision: MatchDecision


class ReportMatchingOutput(TypedDict):
    """오케스트레이터가 받는 정규화 결과와 RM 제안."""

    normalized_report: NormalizedReport
    match_decision: MatchDecision
