"""Report Normalizer와 Matcher가 공유하는 독립 실행 그래프 상태 계약."""

from typing import TypedDict

from clio_agent_graph.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchDecision,
)
from clio_agent_graph.normalization.models import NormalizedReport, NormalizeReportInput


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
    issue_candidates: list[IssueCandidate]
    candidate_comparisons: list[CandidateComparison]
    match_decision: MatchDecision


class ReportMatchingOutput(TypedDict):
    """오케스트레이터가 받는 정규화 결과와 RM 제안."""

    normalized_report: NormalizedReport
    match_decision: MatchDecision
