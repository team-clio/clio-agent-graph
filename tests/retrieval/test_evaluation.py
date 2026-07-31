from pathlib import Path

import pytest

from clio_agent_graph.matching.models import IssueCandidate, IssueRetrievalResponse
from clio_agent_graph.retrieval.evaluation import (
    evaluate_retrieval,
    load_evaluation_cases,
)


def test_fixed_evaluation_cases_are_valid() -> None:
    cases = load_evaluation_cases(Path("evals/issue_retrieval_cases.json"))

    assert len(cases) == 2
    assert {case.expected_issue_id for case in cases} == {19}


def test_recall_at_five_and_mrr_use_candidate_order() -> None:
    cases = load_evaluation_cases(Path("evals/issue_retrieval_cases.json"))
    responses = {
        72: [30, 19, 40],
        73: [30, 31, 32, 33, 34],
    }

    def retrieve(request):
        return IssueRetrievalResponse(
            candidates=[
                IssueCandidate(
                    issue_id=issue_id,
                    title=f"Issue {issue_id}",
                    retrieval_score=1.0 - index * 0.1,
                )
                for index, issue_id in enumerate(responses[request.bug_id])
            ]
        )

    metrics = evaluate_retrieval(cases, retrieve)

    assert metrics.case_count == 2
    assert metrics.recall_at_5 == 0.5
    assert metrics.mean_reciprocal_rank == pytest.approx(0.25)


def test_empty_evaluation_set_returns_zero_without_fake_score() -> None:
    metrics = evaluate_retrieval([], lambda _request: IssueRetrievalResponse())

    assert metrics.case_count == 0
    assert metrics.recall_at_5 == 0.0
    assert metrics.mean_reciprocal_rank == 0.0
