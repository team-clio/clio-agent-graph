"""NM부터 시작해 후속 에이전트가 확장할 LangGraph 상태 계약."""

from typing import TypedDict

from clio_agent_graph.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchDecision,
)
from clio_agent_graph.normalization.models import NormalizedReport, NormalizeReportInput


class ClioInput(TypedDict):
    """NM과 RM을 실행하기 위해 Clio Server가 전달하는 입력."""

    project_id: int
    bug_id: int
    bug_report: NormalizeReportInput


class ClioState(TypedDict, total=False):
    """한 번의 Clio 실행 동안 노드가 읽고 쓰는 내부 상태."""

    # TypedDict는 실행 중 dict이지만 key별 값의 타입을 정적 분석 도구에 알려준다.
    bug_report: NormalizeReportInput
    project_id: int
    bug_id: int
    normalized_report: NormalizedReport
    issue_candidates: list[IssueCandidate]
    candidate_comparisons: list[CandidateComparison]
    match_decision: MatchDecision


class ClioOutput(TypedDict):
    """오케스트레이터가 받는 정규화 결과와 RM 제안."""

    normalized_report: NormalizedReport
    match_decision: MatchDecision
