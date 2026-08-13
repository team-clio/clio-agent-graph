from clio_agent_graph.workflows.reporting.matching.retrieval_subgraph import (
    build_issue_retrieval_subgraph,
)
from clio_agent_graph.workflows.reporting.normalization.models import ErrorSignals, NormalizedReport
from clio_agent_graph.workflows.reporting.retrieval.models import (
    BugSearchHit,
    HydratedIssue,
    RetrievalScope,
    SearchChannel,
    StoredRepresentativeBug,
)


class FakeEmbeddingModel:
    model_name = "fake:semantic"

    def embed(self, _text: str) -> list[float]:
        return [0.1, 0.2]


class FakeRepository:
    def load_scope(self, request, *, embedding_model, embedding_dimension):
        assert request.project_id == 3
        assert request.bug_id == 72
        assert embedding_model == "fake:semantic"
        assert embedding_dimension == 2
        return RetrievalScope(
            excluded_issue_ids=[18],
            eligible_bug_count=2,
            indexed_bug_count=2,
        )

    def search_exact(self, query, scope, *, limit):
        assert scope.excluded_issue_ids == [18]
        assert limit == 50
        return [
            BugSearchHit(
                bug_id=101,
                channel=SearchChannel.EXACT,
                rank=1,
                raw_score=1.0,
                matched_signals=["error_type 일치", "error_code 일치"],
                exact_signal_count=2,
            )
        ]

    def search_lexical(self, _query, _scope, *, limit, threshold):
        assert limit == 50
        assert threshold == 0.1
        return [
            BugSearchHit(
                bug_id=101,
                channel=SearchChannel.LEXICAL,
                rank=1,
                raw_score=0.8,
            )
        ]

    def search_vector(self, _query, _scope, *, embedding, embedding_model, limit):
        assert embedding == [0.1, 0.2]
        assert embedding_model == "fake:semantic"
        assert limit == 50
        return [
            BugSearchHit(
                bug_id=102,
                channel=SearchChannel.VECTOR,
                rank=1,
                raw_score=0.9,
            )
        ]

    def hydrate_issues(self, request, bug_ids, *, issue_limit):
        assert request.project_id == 3
        assert bug_ids == [101, 102]
        assert issue_limit == 20
        return [
            HydratedIssue(
                issue_id=19,
                title="결제 승인 실패",
                status="RESOLVED",
                bugs=[
                    StoredRepresentativeBug(
                        bug_id=101,
                        normalized_report=NormalizedReport(
                            bug_id=401,
                            observed_behavior="결제 승인 실패",
                            error_signals=ErrorSignals(
                                error_type="PaymentException",
                                error_codes=["PAY-500"],
                            ),
                        ),
                    ),
                    StoredRepresentativeBug(
                        bug_id=102,
                        normalized_report=NormalizedReport(
                            bug_id=402,
                            observed_behavior="승인 과정 오류",
                        ),
                    ),
                ],
            )
        ]


def test_hybrid_subgraph_runs_three_channels_and_aggregates_issue() -> None:
    graph = build_issue_retrieval_subgraph(
        repository=FakeRepository(), embedding_model=FakeEmbeddingModel()
    )

    result = graph.invoke(
        {
            "project_id": 3,
            "bug_id": 72,
            "normalized_report": NormalizedReport(
                bug_id=351,
                observed_behavior="결제 승인 시 오류",
                error_signals=ErrorSignals(
                    error_type="PaymentException",
                    error_codes=["PAY-500"],
                ),
            ),
        }
    )

    assert len(result["issue_candidates"]) == 1
    candidate = result["issue_candidates"][0]
    assert candidate.issue_id == 19
    assert candidate.status == "RESOLVED"
    assert [bug.bug_id for bug in candidate.representative_bugs] == [101, 102]
