import pytest

from clio_agent_graph.matching.errors import (
    IssueRetrievalError,
    IssueRetrievalNotConfiguredError,
)
from clio_agent_graph.matching.models import (
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.matching.retrieval_subgraph import (
    build_issue_retrieval_subgraph,
)
from clio_agent_graph.normalization.models import NormalizedReport


def _input() -> dict[str, object]:
    return {
        "project_id": 3,
        "bug_id": 72,
        "normalized_report": NormalizedReport(
            bug_report_id=351,
            observed_behavior="결제 시 500 오류가 발생한다.",
        ),
    }


def test_placeholder_fails_instead_of_returning_no_candidates() -> None:
    graph = build_issue_retrieval_subgraph()

    with pytest.raises(IssueRetrievalNotConfiguredError):
        graph.invoke(_input())


def test_fake_retriever_receives_identifiers_and_returns_candidates() -> None:
    def retrieve(request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        assert request.project_id == 3
        assert request.bug_id == 72
        return IssueRetrievalResponse(
            candidates=[
                IssueCandidate(
                    issue_id=19,
                    title="결제 승인 실패",
                    retrieval_score=0.91,
                )
            ]
        )

    result = build_issue_retrieval_subgraph(retrieve).invoke(_input())

    assert [candidate.issue_id for candidate in result["issue_candidates"]] == [19]


def test_retriever_is_retried_once_then_succeeds() -> None:
    attempts = 0

    def retrieve(_request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary failure")
        return IssueRetrievalResponse()

    result = build_issue_retrieval_subgraph(retrieve).invoke(_input())

    assert attempts == 2
    assert result["issue_candidates"] == []


def test_bug_id_allows_retriever_to_exclude_an_already_linked_issue() -> None:
    all_candidates = [
        IssueCandidate(issue_id=19, title="이미 연결된 Issue", retrieval_score=0.95),
        IssueCandidate(issue_id=20, title="검토할 Issue", retrieval_score=0.88),
    ]
    linked_issue_ids_by_bug = {72: {19}}

    def retrieve(request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        excluded_ids = linked_issue_ids_by_bug.get(request.bug_id, set())
        return IssueRetrievalResponse(
            candidates=[
                candidate for candidate in all_candidates if candidate.issue_id not in excluded_ids
            ]
        )

    result = build_issue_retrieval_subgraph(retrieve).invoke(_input())

    assert [candidate.issue_id for candidate in result["issue_candidates"]] == [20]


def test_retriever_fails_after_one_retry() -> None:
    attempts = 0

    def retrieve(_request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("still unavailable")

    with pytest.raises(IssueRetrievalError):
        build_issue_retrieval_subgraph(retrieve).invoke(_input())

    assert attempts == 2
