import pytest
from pydantic import ValidationError

from clio_agent_graph.workflows.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    AnalysisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    HypothesisConfidence,
    InitialAnalysisInput,
    IssueAnalysis,
    ReanalysisInput,
    RootCauseHypothesis,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


def _bug(bug_id: int = 72) -> AnalysisBug:
    return AnalysisBug(
        bug_id=bug_id,
        normalized_report=NormalizedReport(
            bug_id=300 + bug_id,
            observed_behavior="결제 완료 후 주문이 보이지 않는다.",
        ),
    )


def _evidence(snapshot: str = "order.markPaid();") -> Evidence:
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.CODE,
        code_snapshot=snapshot,
        observation="주문 상태를 PAID로 변경한다.",
    )


def test_trigger_bug_must_be_in_context() -> None:
    with pytest.raises(ValidationError):
        InitialAnalysisInput(
            workflow_run_id=1,
            project_id=3,
            issue=AnalysisIssue(issue_id=19, title="결제 오류"),
            bugs=[_bug()],
            trigger_bug_id=99,
        )


def test_snapshot_accepts_exactly_ten_lines() -> None:
    snapshot = "\n".join(f"line {index}" for index in range(10))

    assert _evidence(snapshot).code_snapshot == snapshot


def test_snapshot_rejects_eleven_lines() -> None:
    snapshot = "\n".join(f"line {index}" for index in range(11))

    with pytest.raises(ValidationError):
        _evidence(snapshot)


def test_completed_analysis_validates_reference_chain() -> None:
    analysis = IssueAnalysis(
        workflow_run_id=501,
        project_id=3,
        issue_id=19,
        status=AnalysisStatus.COMPLETED,
        evidence=[_evidence()],
        findings=[
            Finding(
                finding_id="F1",
                statement="주문 상태 변경이 수행된다.",
                evidence_ids=["E1"],
            )
        ],
        hypotheses=[
            RootCauseHypothesis(
                hypothesis_id="H1",
                priority=1,
                statement="상태 변경 뒤 조회 경로가 갱신되지 않을 가능성이 있다.",
                confidence=HypothesisConfidence.MEDIUM,
                supporting_finding_ids=["F1"],
            )
        ],
    )

    assert analysis.hypotheses[0].supporting_finding_ids == ["F1"]


def test_unknown_evidence_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown finding evidence"):
        IssueAnalysis(
            workflow_run_id=501,
            project_id=3,
            issue_id=19,
            status=AnalysisStatus.COMPLETED,
            evidence=[_evidence()],
            findings=[
                Finding(
                    finding_id="F1",
                    statement="근거가 없는 사실",
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


def test_finding_cannot_reference_symbol_missing_from_its_evidence() -> None:
    with pytest.raises(ValidationError, match="Unknown finding symbol"):
        IssueAnalysis(
            workflow_run_id=501,
            project_id=3,
            issue_id=19,
            status=AnalysisStatus.COMPLETED,
            evidence=[_evidence()],
            findings=[
                Finding(
                    finding_id="F1",
                    statement="존재하지 않는 심볼을 언급한다.",
                    evidence_ids=["E1"],
                    referenced_symbols=["UnknownService.run"],
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


def test_insufficient_result_contains_no_analysis_facts() -> None:
    result = IssueAnalysis(
        workflow_run_id=501,
        project_id=3,
        issue_id=19,
        status=AnalysisStatus.INSUFFICIENT_EVIDENCE,
    )

    assert result.evidence == []


def test_reanalysis_requires_a_new_job_id() -> None:
    previous = IssueAnalysis(
        workflow_run_id=501,
        project_id=3,
        issue_id=19,
        status=AnalysisStatus.INSUFFICIENT_EVIDENCE,
    )

    with pytest.raises(ValidationError, match="new workflow_run_id"):
        ReanalysisInput(
            workflow_run_id=501,
            project_id=3,
            issue=AnalysisIssue(issue_id=19, title="결제 오류"),
            bugs=[_bug()],
            trigger_bug_id=72,
            previous_analysis_result_id=900,
            previous_analysis=previous,
        )
