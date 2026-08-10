"""RM 도메인이 후보 비교 모델에 요구하는 최소 인터페이스."""

from typing import Protocol

from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    MatchComparisonDraft,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


class IssueMatchModel(Protocol):
    """입력 Bug와 기존 Issue 후보들을 비교하는 모델 인터페이스.

    Protocol은 Java의 interface처럼 구현체가 제공해야 할 메서드 모양만 정의한다.
    """

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        """후보별 일치 근거와 모순을 구조화해서 반환한다."""

        ...
