import pytest

from clio_agent_graph.analysis.errors import (
    CodeExplorerNotConfiguredError,
    JudgmentOutputError,
)
from clio_agent_graph.analysis.exploration_subgraph import (
    build_code_exploration_subgraph,
)
from clio_agent_graph.analysis.graph import (
    build_issue_analyzer_graph,
    build_issue_reanalyzer_graph,
)
from clio_agent_graph.analysis.models import (
    AnalysisDraft,
    AnalysisStatus,
    EvidenceCandidate,
    EvidenceKind,
    ExplorationDirective,
    ExplorationRequest,
    ExplorationResponse,
    Finding,
    HypothesisConfidence,
    HypothesisDisposition,
    HypothesisRevision,
    IssueAnalysis,
    RelationCandidate,
    RevisionSummary,
    RootCauseHypothesis,
)


class FakeInitialJudgmentModel:
    """첫 탐색 뒤 현재 Evidence로 최초 분석 초안을 만드는 Fake."""

    def __init__(self, questions: list[list[str]] | None = None) -> None:
        self.questions = questions or [["PaymentService를 찾아라."], []]
        self.plan_calls = 0
        self.analyze_calls = 0

    def plan(
        self,
        context,
        evidence,
        asked_questions,
        *,
        correction_feedback=None,
    ) -> ExplorationDirective:
        questions = self.questions[min(self.plan_calls, len(self.questions) - 1)]
        self.plan_calls += 1
        return ExplorationDirective(questions=questions)

    def analyze(
        self,
        context,
        evidence,
        relations,
        *,
        correction_feedback=None,
    ) -> AnalysisDraft:
        self.analyze_calls += 1
        return _draft()


class FakeRevisionJudgmentModel(FakeInitialJudgmentModel):
    """이전 H1을 현재 H1으로 유지하는 재분석 Fake."""

    def analyze(
        self,
        context,
        evidence,
        relations,
        *,
        correction_feedback=None,
    ) -> AnalysisDraft:
        self.analyze_calls += 1
        return AnalysisDraft(
            findings=_draft().findings,
            hypotheses=_draft().hypotheses,
            revision_summary=RevisionSummary(
                previous_analysis_job_id=context.previous_analysis.analysis_job_id,
                hypothesis_revisions=[
                    HypothesisRevision(
                        previous_hypothesis_id="H1",
                        disposition=HypothesisDisposition.RETAINED,
                        current_hypothesis_id="H1",
                        reason="현재 코드에서도 같은 상태 변경 흐름이 확인됩니다.",
                    )
                ],
            ),
        )


class BrokenRevisionJudgmentModel(FakeRevisionJudgmentModel):
    """존재하지 않는 이전 분석 작업을 참조하는 잘못된 재분석 Fake."""

    def analyze(
        self,
        context,
        evidence,
        relations,
        *,
        correction_feedback=None,
    ) -> AnalysisDraft:
        draft = super().analyze(
            context,
            evidence,
            relations,
            correction_feedback=correction_feedback,
        )
        return draft.model_copy(
            update={
                "revision_summary": draft.revision_summary.model_copy(
                    update={"previous_analysis_job_id": 999}
                )
            }
        )


class EvidenceAwareJudgmentModel(FakeInitialJudgmentModel):
    """테스트와 최근 변경을 지지·반박 Finding으로 사용하는 Fake."""

    def analyze(
        self,
        context,
        evidence,
        relations,
        *,
        correction_feedback=None,
    ) -> AnalysisDraft:
        self.analyze_calls += 1
        return AnalysisDraft(
            findings=[
                Finding(
                    finding_id="F1",
                    statement="서비스는 주문 상태를 변경한다.",
                    evidence_ids=["E1"],
                ),
                Finding(
                    finding_id="F2",
                    statement="관련 테스트는 정상 갱신을 기대한다.",
                    evidence_ids=["E2"],
                ),
                Finding(
                    finding_id="F3",
                    statement="최근 변경에서 캐시 무효화 호출이 제거됐다.",
                    evidence_ids=["E3"],
                ),
            ],
            hypotheses=[
                RootCauseHypothesis(
                    hypothesis_id="H1",
                    priority=1,
                    statement="최근 변경으로 조회 캐시 갱신이 누락됐을 가능성이 있다.",
                    confidence=HypothesisConfidence.HIGH,
                    supporting_finding_ids=["F1", "F3"],
                    contradicting_finding_ids=["F2"],
                )
            ],
        )


def _initial_input() -> dict[str, object]:
    return {
        "analysis_job_id": 501,
        "project_id": 3,
        "issue": {
            "issue_id": 19,
            "title": "결제 완료 후 주문 미노출",
        },
        "bugs": [
            {
                "bug_id": 72,
                "normalized_report": {
                    "bug_report_id": 351,
                    "observed_behavior": "결제 완료 후 주문이 보이지 않는다.",
                },
            }
        ],
        "trigger_bug_id": 72,
    }


def _candidate(snapshot: str = "order.markPaid();") -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_key="payment-service",
        kind=EvidenceKind.CODE,
        code_snapshot=snapshot,
        observation="주문 상태를 PAID로 변경한다.",
        file_path="src/PaymentService.java",
        symbol="PaymentService.completePayment",
    )


def _draft() -> AnalysisDraft:
    return AnalysisDraft(
        findings=[
            Finding(
                finding_id="F1",
                statement="결제 완료 흐름에서 주문 상태를 PAID로 변경한다.",
                evidence_ids=["E1"],
            )
        ],
        hypotheses=[
            RootCauseHypothesis(
                hypothesis_id="H1",
                priority=1,
                statement="상태 변경 뒤 조회 데이터 갱신이 누락됐을 가능성이 있다.",
                confidence=HypothesisConfidence.MEDIUM,
                supporting_finding_ids=["F1"],
            )
        ],
    )


def _completed_previous_analysis() -> IssueAnalysis:
    from clio_agent_graph.analysis.models import Evidence

    return IssueAnalysis(
        analysis_job_id=500,
        project_id=3,
        issue_id=19,
        status=AnalysisStatus.COMPLETED,
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.CODE,
                code_snapshot="oldImplementation();",
                observation="이전 구현이다.",
            )
        ],
        findings=[
            Finding(
                finding_id="F1",
                statement="이전 구현이 호출된다.",
                evidence_ids=["E1"],
            )
        ],
        hypotheses=[
            RootCauseHypothesis(
                hypothesis_id="H1",
                priority=1,
                statement="이전 원인 가설",
                confidence=HypothesisConfidence.LOW,
                supporting_finding_ids=["F1"],
            )
        ],
    )


def test_initial_graph_explores_and_returns_completed_analysis() -> None:
    explorer = build_code_exploration_subgraph(
        lambda _request: ExplorationResponse(candidates=[_candidate()])
    )
    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=explorer,
        judgment_model=FakeInitialJudgmentModel(),
    )

    result = graph.invoke(_initial_input())

    analysis = result["issue_analysis"]
    assert analysis.status is AnalysisStatus.COMPLETED
    assert analysis.evidence[0].evidence_id == "E1"
    assert set(result) == {"issue_analysis"}


def test_reanalysis_does_not_copy_unconfirmed_previous_evidence() -> None:
    explorer = build_code_exploration_subgraph(
        lambda _request: ExplorationResponse(candidates=[_candidate("currentCode();")])
    )
    graph = build_issue_reanalyzer_graph(
        code_exploration_subgraph=explorer,
        judgment_model=FakeRevisionJudgmentModel(),
    )
    graph_input = {
        **_initial_input(),
        "analysis_job_id": 502,
        "previous_analysis": _completed_previous_analysis(),
    }

    result = graph.invoke(graph_input)

    analysis = result["issue_analysis"]
    assert [item.code_snapshot for item in analysis.evidence] == ["currentCode();"]
    assert analysis.revision_summary.previous_analysis_job_id == 500


def test_reanalysis_rejects_wrong_previous_job_reference() -> None:
    explorer = build_code_exploration_subgraph(
        lambda _request: ExplorationResponse(candidates=[_candidate("currentCode();")])
    )
    graph = build_issue_reanalyzer_graph(
        code_exploration_subgraph=explorer,
        judgment_model=BrokenRevisionJudgmentModel(),
    )
    graph_input = {
        **_initial_input(),
        "analysis_job_id": 502,
        "previous_analysis": _completed_previous_analysis(),
    }

    with pytest.raises(JudgmentOutputError):
        graph.invoke(graph_input)


def test_duplicate_evidence_across_rounds_is_merged_once() -> None:
    model = FakeInitialJudgmentModel(questions=[["첫 질문"], ["두 번째 질문"], []])
    explorer = build_code_exploration_subgraph(
        lambda _request: ExplorationResponse(candidates=[_candidate()])
    )
    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=explorer,
        judgment_model=model,
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert len(analysis.evidence) == 1
    assert model.plan_calls == 3


def test_repeated_question_stops_exploration_early() -> None:
    model = FakeInitialJudgmentModel(questions=[["같은 질문"], ["같은 질문"]])
    calls = 0

    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        nonlocal calls
        calls += 1
        return ExplorationResponse()

    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=build_code_exploration_subgraph(explore),
        judgment_model=model,
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert calls == 1
    assert analysis.status is AnalysisStatus.INSUFFICIENT_EVIDENCE


def test_relation_candidate_is_resolved_to_final_evidence_ids() -> None:
    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        return ExplorationResponse(
            candidates=[
                _candidate(),
                EvidenceCandidate(
                    candidate_key="order-repository",
                    kind=EvidenceKind.CODE,
                    code_snapshot="repository.save(order);",
                    observation="주문을 저장한다.",
                ),
            ],
            relations=[
                RelationCandidate(
                    source_ref="payment-service",
                    target_ref="order-repository",
                    relation_type="CALLS",
                )
            ],
        )

    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=build_code_exploration_subgraph(explore),
        judgment_model=FakeInitialJudgmentModel(),
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert analysis.relations[0].source_evidence_id == "E1"
    assert analysis.relations[0].target_evidence_id == "E2"


def test_test_and_change_evidence_can_support_or_contradict_hypothesis() -> None:
    explorer = build_code_exploration_subgraph(
        lambda _request: ExplorationResponse(
            candidates=[
                _candidate(),
                EvidenceCandidate(
                    candidate_key="payment-test",
                    kind=EvidenceKind.TEST,
                    code_snapshot="assertThat(order.status()).isEqualTo(PAID);",
                    observation="테스트는 PAID 상태를 기대한다.",
                ),
                EvidenceCandidate(
                    candidate_key="recent-change",
                    kind=EvidenceKind.CHANGE,
                    code_snapshot="- cache.evict(order.id());",
                    observation="최근 변경에서 캐시 무효화 호출이 제거됐다.",
                    change_id="change-17",
                ),
            ]
        )
    )
    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=explorer,
        judgment_model=EvidenceAwareJudgmentModel(),
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert [item.kind for item in analysis.evidence] == [
        EvidenceKind.CODE,
        EvidenceKind.TEST,
        EvidenceKind.CHANGE,
    ]
    assert analysis.hypotheses[0].contradicting_finding_ids == ["F2"]


def test_evidence_is_capped_at_twenty_across_three_rounds() -> None:
    model = FakeInitialJudgmentModel(questions=[["질문 1"], ["질문 2"], ["질문 3"]])
    round_number = 0

    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        nonlocal round_number
        round_number += 1
        return ExplorationResponse(
            candidates=[
                EvidenceCandidate(
                    candidate_key=f"round-{round_number}-{index}",
                    kind=EvidenceKind.CODE,
                    code_snapshot=f"code{round_number}_{index}();",
                    observation="코드 후보다.",
                )
                for index in range(10)
            ]
        )

    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=build_code_exploration_subgraph(explore),
        judgment_model=model,
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert len(analysis.evidence) == 20
    assert "Evidence 최대 20개 제한을 적용했습니다." in analysis.warnings


def test_three_empty_rounds_return_insufficient_evidence_without_analysis_call() -> None:
    model = FakeInitialJudgmentModel(questions=[["질문 1"], ["질문 2"], ["질문 3"]])
    calls = 0

    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        nonlocal calls
        calls += 1
        return ExplorationResponse()

    graph = build_issue_analyzer_graph(
        code_exploration_subgraph=build_code_exploration_subgraph(explore),
        judgment_model=model,
    )

    analysis = graph.invoke(_initial_input())["issue_analysis"]

    assert calls == 3
    assert model.analyze_calls == 0
    assert analysis.status is AnalysisStatus.INSUFFICIENT_EVIDENCE


def test_default_code_explorer_fails_explicitly() -> None:
    graph = build_issue_analyzer_graph(judgment_model=FakeInitialJudgmentModel())

    with pytest.raises(CodeExplorerNotConfiguredError):
        graph.invoke(_initial_input())
