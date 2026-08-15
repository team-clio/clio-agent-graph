"""Retrieval 업무 로직과 외부 DB·embedding provider 사이의 교체 경계."""

from typing import Protocol

from clio_agent_graph.workflows.reporting.matching.models import IssueRetrievalRequest
from clio_agent_graph.workflows.reporting.normalization.models import NormalizeReportInput
from clio_agent_graph.workflows.reporting.retrieval.models import (
    BugIndexInput,
    BugIndexResult,
    BugSearchHit,
    BugSearchQuery,
    HydratedIssue,
    RetrievalScope,
)


class EmbeddingModel(Protocol):
    """Java interface처럼 실제 provider와 테스트 Fake가 지킬 계약."""

    @property
    def model_name(self) -> str:
        """저장 embedding과 query embedding의 호환성을 확인할 모델 ID."""

    def embed(self, text: str) -> list[float]:
        """검색 문서 한 개를 의미 벡터로 바꾼다."""


class IssueRetrievalRepository(Protocol):
    """Issue Retrieval Agent가 PostgreSQL에 요구하는 읽기 계약."""

    def load_scope(
        self,
        request: IssueRetrievalRequest,
        *,
        embedding_model: str,
        embedding_dimension: int,
    ) -> RetrievalScope:
        """제외 Issue와 compatible index coverage를 계산한다."""

    def search_exact(
        self, query: BugSearchQuery, scope: RetrievalScope, *, limit: int
    ) -> list[BugSearchHit]:
        """오류 식별자가 정확히 같은 Bug를 찾는다."""

    def search_lexical(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        limit: int,
        threshold: float,
    ) -> list[BugSearchHit]:
        """pg_trgm 문자열 유사도로 Bug를 찾는다."""

    def search_vector(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        embedding: list[float],
        embedding_model: str,
        limit: int,
    ) -> list[BugSearchHit]:
        """pgvector cosine 유사도로 Bug를 찾는다."""

    def hydrate_issues(
        self,
        request: IssueRetrievalRequest,
        bug_ids: list[int],
        *,
        issue_limit: int,
    ) -> list[HydratedIssue]:
        """검색 Bug가 속한 Issue와 active snapshot을 읽는다."""


class BugIndexRepository(Protocol):
    """Retrieval snapshot과 embedding을 원자적으로 저장하는 계약."""

    def save_index(
        self,
        request: BugIndexInput,
        *,
        search_text: str,
        document_hash: str,
        embedding: list[float],
        embedding_model: str,
    ) -> BugIndexResult:
        """관계를 검증하고 멱등하게 active snapshot을 저장한다."""

    def load_backfill_batch(
        self, project_id: int, *, after_bug_id: int, limit: int
    ) -> tuple[list[tuple[int, NormalizeReportInput]], bool]:
        """정규화에 필요한 과거 Bug batch와 다음 페이지 여부를 반환한다."""
