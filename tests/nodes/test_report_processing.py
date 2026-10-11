import pytest

from clio_agent_graph.workflows.orchestration.nodes import report_processing
from clio_agent_graph.workflows.reporting.matching.models import MatchAction, MatchDecision


class _StubMatcher:
    def __init__(self, decision: MatchDecision) -> None:
        self._decision = decision

    def match(self, **_: object) -> MatchDecision:
        return self._decision


def _match_reason(monkeypatch: pytest.MonkeyPatch, decision: MatchDecision) -> str:
    monkeypatch.setattr(report_processing, "build_report_matcher", lambda: _StubMatcher(decision))
    candidate = {"issue_id": 2, "title": "합성 캔들 시세", "retrieval_score": 0.9}
    result = report_processing.match_report(
        {
            "bug_id": "4",
            "normalized_report": {"bug_id": 4, "observed_behavior": "거래량이 0이다."},
            "issue_candidates": [candidate],
        }
    )
    return result["match_decision"]["reason"]


def test_review_reason_ends_each_item_and_groups_reasons_under_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = MatchDecision(
        bug_id=4,
        action=MatchAction.REVIEW,
        matched_issue_id=2,
        confidence=0.72,
        supporting_reasons=["같은 캔들 조회 endpoint를 다룬다."],
        contradictions=["입력 Bug는 거래량 0, 후보는 거래량 고정값"],
        review_reasons=[
            "같은 근본 원인인지 판단할 코드 경로",
            "후보 Issue가 5280 DAY 사례를 포함하는지 여부",
            "후보와 모순되는 중요 정보가 있습니다.",
        ],
    )

    reason = _match_reason(monkeypatch, decision)

    assert reason == (
        "근거: 같은 캔들 조회 endpoint를 다룬다. "
        "모순: 입력 Bug는 거래량 0, 후보는 거래량 고정값. "
        "검토 사유: 같은 근본 원인인지 판단할 코드 경로. "
        "후보 Issue가 5280 DAY 사례를 포함하는지 여부. "
        "후보와 모순되는 중요 정보가 있습니다."
    )


def test_review_reason_without_any_items_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = MatchDecision(
        bug_id=4, action=MatchAction.REVIEW, matched_issue_id=2, confidence=0.8
    )

    assert _match_reason(monkeypatch, decision) == "매칭 정책이 판단 근거를 남기지 않았습니다."
