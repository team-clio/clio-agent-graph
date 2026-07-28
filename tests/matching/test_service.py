import pytest

from clio_agent_graph.matching.errors import IssueMatchError, IssueMatchOutputError
from clio_agent_graph.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchAction,
    MatchComparisonDraft,
    RepresentativeBug,
)
from clio_agent_graph.matching.service import ReportMatcher
from clio_agent_graph.normalization.models import (
    AffectedSurface,
    ErrorSignals,
    NormalizedReport,
)


class FakeMatchModel:
    """호출별 응답이나 예외를 순서대로 반환하는 테스트용 비교 모델."""

    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[str | None] = []

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        self.calls.append(correction_feedback)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return MatchComparisonDraft.model_validate(result)


def _report(*, with_surface: bool = True) -> NormalizedReport:
    return NormalizedReport(
        bug_report_id=351,
        observed_behavior="결제 승인 요청 시 500 오류가 발생한다.",
        affected_surface=AffectedSurface(feature="결제") if with_surface else {},
        error_signals=ErrorSignals(
            error_type="PaymentException",
            error_codes=["PAY-500"],
            stack_frames=["PaymentService.approve"],
        ),
    )


def _candidate(issue_id: int, *, same_signal: bool = True) -> IssueCandidate:
    signals = (
        ErrorSignals(
            error_type="PaymentException",
            error_codes=["PAY-500"],
            stack_frames=["PaymentService.approve"],
        )
        if same_signal
        else ErrorSignals(error_type="TimeoutException", error_codes=["TIMEOUT"])
    )
    return IssueCandidate(
        issue_id=issue_id,
        title="결제 승인 실패",
        retrieval_score=0.9,
        representative_bugs=[
            RepresentativeBug(
                bug_id=100 + issue_id,
                normalized_report=NormalizedReport(
                    bug_report_id=200 + issue_id,
                    observed_behavior="결제 승인 요청이 실패한다.",
                    affected_surface=AffectedSurface(feature="결제"),
                    error_signals=signals,
                ),
            )
        ],
    )


def _draft(*comparisons: CandidateComparison) -> MatchComparisonDraft:
    return MatchComparisonDraft(comparisons=list(comparisons))


def _comparison(
    issue_id: int,
    confidence: float,
    *,
    contradictions: list[str] | None = None,
) -> CandidateComparison:
    return CandidateComparison(
        issue_id=issue_id,
        confidence=confidence,
        supporting_reasons=["발생 현상과 오류 흐름이 일치합니다."],
        contradictions=contradictions or [],
    )


def test_no_candidates_creates_new_without_calling_model() -> None:
    model = FakeMatchModel()

    decision = ReportMatcher(model).match(bug_id=72, report=_report(), candidates=[])

    assert decision.action is MatchAction.CREATE_NEW
    assert decision.matched_issue_id is None
    assert model.calls == []


def test_strong_duplicate_is_auto_linked() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(_draft(_comparison(19, 0.97)))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.AUTO_LINK
    assert decision.matched_issue_id == 19


def test_different_error_signal_blocks_auto_link() -> None:
    candidate = _candidate(19, same_signal=False)
    model = FakeMatchModel(_draft(_comparison(19, 0.97)))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.REVIEW
    assert "정확히 일치하는 강한 오류 신호가 없습니다." in decision.review_reasons


def test_contradiction_blocks_auto_link() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(_draft(_comparison(19, 0.98, contradictions=["발생 환경이 다릅니다."])))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.REVIEW


def test_missing_affected_surface_blocks_auto_link() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(_draft(_comparison(19, 0.98)))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(with_surface=False),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.REVIEW
    assert "입력 Bug의 영향 영역이 없습니다." in decision.review_reasons


def test_close_top_candidates_are_sent_to_review() -> None:
    candidates = [_candidate(19), _candidate(20)]
    model = FakeMatchModel(_draft(_comparison(19, 0.98), _comparison(20, 0.90)))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=candidates,
    )

    assert decision.action is MatchAction.REVIEW
    assert decision.matched_issue_id == 19


def test_low_confidence_candidate_creates_new() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(_draft(_comparison(19, 0.69)))

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.CREATE_NEW
    assert decision.matched_issue_id is None


def test_unknown_candidate_id_is_corrected_once() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(
        _draft(_comparison(999, 0.9)),
        _draft(_comparison(19, 0.9)),
    )

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.REVIEW
    assert model.calls[0] is None
    assert "do not match" in (model.calls[1] or "")


def test_invalid_output_twice_fails() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(
        _draft(_comparison(999, 0.9)),
        _draft(_comparison(998, 0.9)),
    )

    with pytest.raises(IssueMatchOutputError):
        ReportMatcher(model).match(
            bug_id=72,
            report=_report(),
            candidates=[candidate],
        )

    assert len(model.calls) == 2


def test_provider_failure_is_retried_once() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(
        TimeoutError("temporary"),
        _draft(_comparison(19, 0.9)),
    )

    decision = ReportMatcher(model).match(
        bug_id=72,
        report=_report(),
        candidates=[candidate],
    )

    assert decision.action is MatchAction.REVIEW
    assert model.calls == [None, None]


def test_provider_failure_twice_fails() -> None:
    candidate = _candidate(19)
    model = FakeMatchModel(TimeoutError("first"), TimeoutError("second"))

    with pytest.raises(IssueMatchError):
        ReportMatcher(model).match(
            bug_id=72,
            report=_report(),
            candidates=[candidate],
        )

    assert len(model.calls) == 2
