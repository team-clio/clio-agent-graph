"""공통 IA가 상황별 Judgment 모델에 요구하는 인터페이스."""

from typing import Protocol

from clio_agent_graph.analysis.models import (
    AnalysisDraft,
    CodeRelation,
    Evidence,
    ExplorationDirective,
    JudgmentContext,
)


class JudgmentModel(Protocol):
    """탐색 질문과 최종 판단 초안을 만드는 subagent 모델 인터페이스."""

    def plan(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        asked_questions: list[str],
        *,
        correction_feedback: str | None = None,
    ) -> ExplorationDirective:
        """현재 근거를 보고 다음 코드 탐색 질문을 만든다."""

        ...

    def analyze(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        relations: list[CodeRelation],
        *,
        correction_feedback: str | None = None,
    ) -> AnalysisDraft:
        """확인된 근거만 사용해 Finding과 Hypothesis 초안을 만든다."""

        ...
