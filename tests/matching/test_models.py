import pytest
from pydantic import ValidationError

from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    IssueRetrievalResponse,
    MatchAction,
    MatchDecision,
    MatchPolicySettings,
    RepresentativeBug,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


def test_issue_candidate_requires_comparable_content() -> None:
    with pytest.raises(ValidationError):
        IssueCandidate(issue_id=1, retrieval_score=0.8)


def test_retrieval_response_rejects_duplicate_issue_ids() -> None:
    candidate = IssueCandidate(issue_id=1, title="결제 실패", retrieval_score=0.8)

    with pytest.raises(ValidationError):
        IssueRetrievalResponse(candidates=[candidate, candidate])


def test_retrieval_response_accepts_at_most_five_issues() -> None:
    candidates = [
        IssueCandidate(issue_id=index, title=f"후보 {index}", retrieval_score=0.8)
        for index in range(1, 7)
    ]

    with pytest.raises(ValidationError):
        IssueRetrievalResponse(candidates=candidates)


def test_retrieval_response_requires_score_order() -> None:
    with pytest.raises(ValidationError):
        IssueRetrievalResponse(
            candidates=[
                IssueCandidate(issue_id=1, title="후보 1", retrieval_score=0.7),
                IssueCandidate(issue_id=2, title="후보 2", retrieval_score=0.9),
            ]
        )


def test_issue_candidate_accepts_at_most_three_representative_bugs() -> None:
    representative_bugs = [
        RepresentativeBug(
            bug_id=index,
            normalized_report=NormalizedReport(
                bug_report_id=100 + index,
                observed_behavior=f"현상 {index}",
            ),
        )
        for index in range(1, 5)
    ]

    with pytest.raises(ValidationError):
        IssueCandidate(
            issue_id=1,
            title="대표 Bug가 너무 많은 후보",
            retrieval_score=0.9,
            representative_bugs=representative_bugs,
        )


def test_create_new_decision_rejects_existing_issue_id() -> None:
    with pytest.raises(ValidationError):
        MatchDecision(
            bug_id=7,
            action=MatchAction.CREATE_NEW,
            matched_issue_id=11,
            confidence=0.2,
        )


def test_policy_settings_reject_reversed_thresholds() -> None:
    with pytest.raises(ValidationError):
        MatchPolicySettings(auto_link_threshold=0.7, review_threshold=0.8)
