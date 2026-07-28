"""NM부터 시작해 후속 에이전트가 확장할 LangGraph 상태 계약."""

from typing import TypedDict

from clio_agent_graph.normalization.models import NormalizedReport, NormalizeReportInput


class ClioInput(TypedDict):
    """현재 공개 그래프가 받는 원본 BugReport 입력."""

    bug_report: NormalizeReportInput


class ClioState(TypedDict, total=False):
    """한 번의 Clio 실행 동안 노드가 읽고 쓰는 내부 상태."""

    # TypedDict는 실행 중 dict이지만 key별 값의 타입을 정적 분석 도구에 알려준다.
    bug_report: NormalizeReportInput
    normalized_report: NormalizedReport


class ClioOutput(TypedDict):
    """현재 공개 그래프가 반환하는 NM 결과."""

    normalized_report: NormalizedReport
