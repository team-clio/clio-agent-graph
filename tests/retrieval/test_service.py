import pytest

from clio_agent_graph.matching.models import IssueRetrievalRequest
from clio_agent_graph.normalization.models import NormalizedReport
from clio_agent_graph.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalIndexNotReadyError,
    RetrievalOperationError,
)
from clio_agent_graph.retrieval.models import RetrievalScope, RetrievalSettings
from clio_agent_graph.retrieval.service import IssueRetrieverService


class FakeEmbeddingModel:
    model_name = "fake:semantic"

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def embed(self, _text: str) -> list[float]:
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("temporary provider failure")
        return [0.1, 0.2, 0.3]


class ScopeRepository:
    def __init__(self, scope: RetrievalScope) -> None:
        self.scope = scope
        self.scope_calls = 0

    def load_scope(self, *_args, **_kwargs) -> RetrievalScope:
        self.scope_calls += 1
        return self.scope


def _request() -> IssueRetrievalRequest:
    return IssueRetrievalRequest(
        project_id=3,
        bug_id=72,
        normalized_report=NormalizedReport(
            bug_report_id=351,
            observed_behavior="결제 시 오류가 발생한다.",
        ),
    )


def test_prepare_retries_embedding_once() -> None:
    model = FakeEmbeddingModel(failures=1)
    repository = ScopeRepository(RetrievalScope(eligible_bug_count=0, indexed_bug_count=0))
    service = IssueRetrieverService(repository, model)

    _query, embedding, model_name, scope = service.prepare(_request())

    assert embedding == [0.1, 0.2, 0.3]
    assert model_name == "fake:semantic"
    assert scope.eligible_bug_count == 0
    assert model.calls == 2


def test_prepare_prefers_query_specific_embedding() -> None:
    class QueryAwareModel(FakeEmbeddingModel):
        def embed(self, _text: str) -> list[float]:
            raise AssertionError("document embedding must not be used for a query")

        def embed_query(self, text: str) -> list[float]:
            assert "observed_behavior" in text
            return [0.4, 0.5]

    repository = ScopeRepository(RetrievalScope(eligible_bug_count=0, indexed_bug_count=0))

    _query, embedding, _model_name, _scope = IssueRetrieverService(
        repository, QueryAwareModel()
    ).prepare(_request())

    assert embedding == [0.4, 0.5]


def test_prepare_fails_after_second_provider_error() -> None:
    model = FakeEmbeddingModel(failures=2)
    repository = ScopeRepository(RetrievalScope(eligible_bug_count=0, indexed_bug_count=0))

    with pytest.raises(RetrievalOperationError):
        IssueRetrieverService(repository, model).prepare(_request())

    assert model.calls == 2
    assert repository.scope_calls == 0


def test_incomplete_coverage_is_not_treated_as_no_candidates() -> None:
    repository = ScopeRepository(RetrievalScope(eligible_bug_count=3, indexed_bug_count=2))

    with pytest.raises(RetrievalIndexNotReadyError, match="2/3"):
        IssueRetrieverService(repository, FakeEmbeddingModel()).prepare(_request())


def test_configuration_error_is_not_retried() -> None:
    class MissingConfigurationModel:
        @property
        def model_name(self) -> str:
            raise RetrievalConfigurationError("missing model")

        def embed(self, _text: str) -> list[float]:
            raise AssertionError("must not be called")

    repository = ScopeRepository(RetrievalScope(eligible_bug_count=0, indexed_bug_count=0))

    with pytest.raises(RetrievalConfigurationError):
        IssueRetrieverService(repository, MissingConfigurationModel()).prepare(_request())

    assert repository.scope_calls == 0


def test_settings_keep_public_top_k_limits() -> None:
    settings = RetrievalSettings()

    assert settings.channel_limit == 50
    assert settings.hydrated_issue_limit == 20
    assert settings.final_issue_limit == 5
    assert settings.representative_bug_limit == 3
