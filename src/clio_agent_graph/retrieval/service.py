"""Hybrid 검색 operation과 결과 조립을 담당하는 Retrieval 업무 서비스."""

import math
from collections.abc import Callable
from typing import TypeVar

from clio_agent_graph.matching.models import IssueCandidate, IssueRetrievalRequest
from clio_agent_graph.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
    RetrievalIndexNotReadyError,
    RetrievalOperationError,
)
from clio_agent_graph.retrieval.fusion import aggregate_issue_candidates, fuse_bug_hits
from clio_agent_graph.retrieval.models import (
    BugSearchHit,
    BugSearchQuery,
    FusedBugHit,
    HydratedIssue,
    RetrievalScope,
    RetrievalSettings,
)
from clio_agent_graph.retrieval.ports import EmbeddingModel, IssueRetrievalRepository
from clio_agent_graph.retrieval.query import build_search_query

T = TypeVar("T")


class IssueRetrieverService:
    """Embedding·세 검색 채널·Issue 집계를 명시적인 단계로 제공한다."""

    def __init__(
        self,
        repository: IssueRetrievalRepository,
        embedding_model: EmbeddingModel,
        *,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_model = embedding_model
        self.settings = settings if settings is not None else RetrievalSettings()

    def prepare(
        self, request: IssueRetrievalRequest
    ) -> tuple[BugSearchQuery, list[float], str, RetrievalScope]:
        """검색 질의와 query embedding을 만들고 index coverage를 확인한다."""

        query = build_search_query(request)
        model_name = self._embedding_model.model_name
        embed_query = getattr(
            self._embedding_model,
            "embed_query",
            self._embedding_model.embed,
        )
        embedding = _retry_once(lambda: embed_query(query.search_text))
        _validate_embedding(embedding)
        scope = _retry_once(
            lambda: self._repository.load_scope(
                request,
                embedding_model=model_name,
                embedding_dimension=len(embedding),
            )
        )
        if scope.indexed_bug_count != scope.eligible_bug_count:
            raise RetrievalIndexNotReadyError(
                "Compatible active index coverage is incomplete: "
                f"{scope.indexed_bug_count}/{scope.eligible_bug_count}."
            )
        return query, embedding, model_name, scope

    def search_exact(self, query: BugSearchQuery, scope: RetrievalScope) -> list[BugSearchHit]:
        """Exact 채널을 한 번 재시도하고 검증된 hit를 반환한다."""

        return _retry_once(
            lambda: self._repository.search_exact(query, scope, limit=self.settings.channel_limit)
        )

    def search_lexical(self, query: BugSearchQuery, scope: RetrievalScope) -> list[BugSearchHit]:
        """Trigram 채널을 한 번 재시도하고 검증된 hit를 반환한다."""

        return _retry_once(
            lambda: self._repository.search_lexical(
                query,
                scope,
                limit=self.settings.channel_limit,
                threshold=self.settings.lexical_threshold,
            )
        )

    def search_vector(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        embedding: list[float],
        embedding_model: str,
    ) -> list[BugSearchHit]:
        """Vector 채널을 한 번 재시도하고 검증된 hit를 반환한다."""

        return _retry_once(
            lambda: self._repository.search_vector(
                query,
                scope,
                embedding=embedding,
                embedding_model=embedding_model,
                limit=self.settings.channel_limit,
            )
        )

    def fuse(self, hits: list[BugSearchHit]) -> list[FusedBugHit]:
        """세 검색 채널 결과를 weighted RRF로 합친다."""

        return fuse_bug_hits(hits, self.settings)

    def hydrate(
        self,
        request: IssueRetrievalRequest,
        fused_hits: list[FusedBugHit],
    ) -> list[HydratedIssue]:
        """상위 Bug가 연결된 Issue와 대표 snapshot을 읽는다."""

        if not fused_hits:
            return []
        return _retry_once(
            lambda: self._repository.hydrate_issues(
                request,
                [hit.bug_id for hit in fused_hits],
                issue_limit=self.settings.hydrated_issue_limit,
            )
        )

    def aggregate(
        self, fused_hits: list[FusedBugHit], issues: list[HydratedIssue]
    ) -> list[IssueCandidate]:
        """Hydration 결과를 RM 공개 후보 계약으로 제한·정렬한다."""

        return aggregate_issue_candidates(fused_hits, issues, self.settings)


def _retry_once(operation: Callable[[], T]) -> T:
    """외부 operation만 최대 두 번 호출하고 원래 오류를 원인으로 보존한다."""

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            return operation()
        except (
            RetrievalConfigurationError,
            RetrievalDataError,
            RetrievalIndexNotReadyError,
        ):
            raise
        except Exception as error:
            last_error = error
    raise RetrievalOperationError("Retrieval operation failed after one retry.") from last_error


def _validate_embedding(embedding: list[float]) -> None:
    """비어 있거나 NaN·무한대가 든 provider 결과를 DB 호출 전에 거부한다."""

    if not embedding:
        raise RetrievalDataError("Embedding must contain at least one value.")
    if any(not math.isfinite(value) for value in embedding):
        raise RetrievalDataError("Embedding contains a non-finite value.")
