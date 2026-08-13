import pytest

from clio_agent_graph.workflows.reporting.matching.errors import IssueRetrievalNotConfiguredError
from clio_agent_graph.workflows.reporting.matching.graph import build_report_matching_graph
from clio_agent_graph.workflows.reporting.matching.models import (
    CandidateComparison,
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
    MatchAction,
    MatchComparisonDraft,
    RepresentativeBug,
)
from clio_agent_graph.workflows.reporting.matching.retrieval_subgraph import (
    build_issue_retrieval_subgraph,
)
from clio_agent_graph.workflows.reporting.normalization.models import (
    AffectedSurface,
    ErrorSignals,
    NormalizationDraft,
    NormalizedReport,
)


class FakeNormalizationModel:
    """외부 API 없이 그래프 배선을 검증하는 NM 모델."""

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        assert "결제 버튼을 누르면" in report_text
        assert correction_feedback is None
        return NormalizationDraft(
            observed_behavior="결제 버튼 클릭 시 500 오류가 발생한다.",
            affected_surface=AffectedSurface(feature="결제"),
            error_signals=ErrorSignals(
                error_type="PaymentException",
                error_codes=["PAY-500"],
                stack_frames=["PaymentService.approve"],
            ),
        )


class FakeIssueMatchModel:
    """후보 하나를 높은 신뢰도로 같은 Issue라고 비교하는 RM 모델."""

    def __init__(self) -> None:
        self.calls = 0

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        self.calls += 1
        assert report.bug_id == 351
        assert correction_feedback is None
        return MatchComparisonDraft(
            comparisons=[
                CandidateComparison(
                    issue_id=candidates[0].issue_id,
                    confidence=0.97,
                    supporting_reasons=["현상과 강한 오류 신호가 일치합니다."],
                )
            ]
        )


def _graph_input() -> dict[str, object]:
    return {
        "project_id": 3,
        "bug_id": 72,
        "bug_report": {
            "bug_id": 351,
            "title": "결제 실패",
            "description": "결제 버튼을 누르면 500 오류가 발생합니다.",
        },
    }


def _retrieval_with_one_candidate():
    def retrieve(request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        assert request.project_id == 3
        assert request.bug_id == 72
        return IssueRetrievalResponse(
            candidates=[
                IssueCandidate(
                    issue_id=19,
                    title="결제 승인 실패",
                    retrieval_score=0.96,
                    representative_bugs=[
                        RepresentativeBug(
                            bug_id=41,
                            normalized_report=NormalizedReport(
                                bug_id=201,
                                observed_behavior="결제 승인 요청이 실패한다.",
                                affected_surface=AffectedSurface(feature="결제"),
                                error_signals=ErrorSignals(
                                    error_type="PaymentException",
                                    error_codes=["PAY-500"],
                                ),
                            ),
                        )
                    ],
                )
            ]
        )

    return build_issue_retrieval_subgraph(retrieve)


def test_graph_normalizes_and_auto_links_a_bug() -> None:
    graph = build_report_matching_graph(
        FakeNormalizationModel(),
        retrieval_subgraph=_retrieval_with_one_candidate(),
        match_model=FakeIssueMatchModel(),
    )

    result = graph.invoke(_graph_input())

    normalized_report = result["normalized_report"]
    assert isinstance(normalized_report, NormalizedReport)
    assert normalized_report.bug_id == 351
    assert result["match_decision"].action is MatchAction.AUTO_LINK
    assert result["match_decision"].matched_issue_id == 19
    assert set(result) == {"normalized_report", "match_decision"}


def test_graph_skips_match_model_when_retrieval_returns_no_candidates() -> None:
    match_model = FakeIssueMatchModel()
    retrieval = build_issue_retrieval_subgraph(lambda _request: IssueRetrievalResponse())
    graph = build_report_matching_graph(
        FakeNormalizationModel(),
        retrieval_subgraph=retrieval,
        match_model=match_model,
    )

    result = graph.invoke(_graph_input())

    assert result["match_decision"].action is MatchAction.CREATE_NEW
    assert match_model.calls == 0


def test_default_graph_fails_when_retrieval_agent_is_not_configured() -> None:
    graph = build_report_matching_graph(
        FakeNormalizationModel(),
        match_model=FakeIssueMatchModel(),
    )

    with pytest.raises(IssueRetrievalNotConfiguredError):
        graph.invoke(_graph_input())


def test_graph_contains_nm_rag_and_rm_nodes() -> None:
    graph = build_report_matching_graph(
        FakeNormalizationModel(),
        retrieval_subgraph=_retrieval_with_one_candidate(),
        match_model=FakeIssueMatchModel(),
    )

    node_names = set(graph.get_graph().nodes)

    assert node_names == {
        "__start__",
        "normalize_report",
        "issue_retrieval_subgraph",
        "judge_issue_match",
        "apply_match_policy",
        "__end__",
    }
