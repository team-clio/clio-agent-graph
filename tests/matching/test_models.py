import pytest
from pydantic import ValidationError

from clio_agent_graph.matching.models import (
    IssueCandidate,
    IssueRetrievalResponse,
    MatchAction,
    MatchDecision,
    MatchPolicySettings,
)


def test_issue_candidate_requires_comparable_content() -> None:
    with pytest.raises(ValidationError):
        IssueCandidate(issue_id=1, retrieval_score=0.8)


def test_retrieval_response_rejects_duplicate_issue_ids() -> None:
    candidate = IssueCandidate(issue_id=1, title="결제 실패", retrieval_score=0.8)

    with pytest.raises(ValidationError):
        IssueRetrievalResponse(candidates=[candidate, candidate])


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
