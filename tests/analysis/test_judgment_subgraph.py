import pytest

from clio_agent_graph.workflows.analysis.errors import JudgmentError
from clio_agent_graph.workflows.analysis.judgment_subgraph import build_judgment_subgraph
from clio_agent_graph.workflows.analysis.models import (
    AnalysisBug,
    AnalysisDraft,
    AnalysisIssue,
    AnalysisMode,
    Evidence,
    EvidenceKind,
    ExplorationDirective,
    Finding,
    HypothesisConfidence,
    JudgmentContext,
    JudgmentPhase,
    RootCauseHypothesis,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


class FakeJudgmentModel:
    """plan과 analyze 결과를 독립적으로 제공하는 테스트 모델."""

    def __init__(self) -> None:
        self.plan_results: list[object] = [
            ExplorationDirective(questions=["PaymentService를 찾아라."])
        ]
        self.analysis_results: list[object] = [_draft()]
        self.analysis_feedback: list[str | None] = []

    def plan(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        asked_questions: list[str],
        *,
        correction_feedback: str | None = None,
    ) -> ExplorationDirective:
        result = self.plan_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return ExplorationDirective.model_validate(result)

    def analyze(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        relations: list,
        *,
        correction_feedback: str | None = None,
    ) -> AnalysisDraft:
        self.analysis_feedback.append(correction_feedback)
        result = self.analysis_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return AnalysisDraft.model_validate(result)


def _context() -> JudgmentContext:
    return JudgmentContext(
        mode=AnalysisMode.INITIAL,
        analysis_job_id=501,
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="결제 오류"),
        bugs=[
            AnalysisBug(
                bug_id=72,
                normalized_report=NormalizedReport(
                    bug_report_id=351,
                    observed_behavior="결제 완료 후 주문이 보이지 않는다.",
                ),
            )
        ],
        trigger_bug_id=72,
    )


def _evidence() -> Evidence:
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.CODE,
        code_snapshot="order.markPaid();",
        observation="주문 상태를 변경한다.",
    )


def _draft() -> AnalysisDraft:
    return AnalysisDraft(
        findings=[
            Finding(
                finding_id="F1",
                statement="주문 상태를 변경한다.",
                evidence_ids=["E1"],
            )
        ],
        hypotheses=[
            RootCauseHypothesis(
                hypothesis_id="H1",
                priority=1,
                statement="조회 경로 갱신이 누락됐을 가능성이 있다.",
                confidence=HypothesisConfidence.MEDIUM,
                supporting_finding_ids=["F1"],
            )
        ],
    )


def _state(phase: JudgmentPhase) -> dict[str, object]:
    return {
        "judgment_context": _context(),
        "judgment_phase": phase,
        "evidence": [_evidence()] if phase is JudgmentPhase.ANALYZE else [],
        "relations": [],
        "asked_questions": [],
    }


def test_subgraph_routes_plan_phase() -> None:
    result = build_judgment_subgraph(FakeJudgmentModel()).invoke(_state(JudgmentPhase.PLAN))

    assert result["exploration_directive"].questions == ["PaymentService를 찾아라."]


def test_subgraph_routes_analyze_phase() -> None:
    result = build_judgment_subgraph(FakeJudgmentModel()).invoke(_state(JudgmentPhase.ANALYZE))

    assert result["analysis_draft"].hypotheses[0].hypothesis_id == "H1"


def test_provider_failure_is_retried_once() -> None:
    model = FakeJudgmentModel()
    model.plan_results = [
        TimeoutError("temporary"),
        ExplorationDirective(questions=[]),
    ]

    result = build_judgment_subgraph(model).invoke(_state(JudgmentPhase.PLAN))

    assert result["exploration_directive"].questions == []


def test_provider_failure_twice_fails() -> None:
    model = FakeJudgmentModel()
    model.plan_results = [TimeoutError("first"), TimeoutError("second")]

    with pytest.raises(JudgmentError):
        build_judgment_subgraph(model).invoke(_state(JudgmentPhase.PLAN))


def test_unknown_evidence_reference_is_corrected_once() -> None:
    model = FakeJudgmentModel()
    invalid = AnalysisDraft(
        findings=[
            Finding(
                finding_id="F1",
                statement="잘못된 근거 참조",
                evidence_ids=["E2"],
            )
        ],
        hypotheses=[
            RootCauseHypothesis(
                hypothesis_id="H1",
                priority=1,
                statement="가설",
                confidence=HypothesisConfidence.LOW,
                supporting_finding_ids=["F1"],
            )
        ],
    )
    model.analysis_results = [invalid, _draft()]

    result = build_judgment_subgraph(model).invoke(_state(JudgmentPhase.ANALYZE))

    assert result["analysis_draft"].findings[0].evidence_ids == ["E1"]
    assert model.analysis_feedback[0] is None
    assert "Unknown finding evidence" in (model.analysis_feedback[1] or "")
