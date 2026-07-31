"""PostgreSQL Hybrid 검색과 snapshot 저장을 담당할 adapter."""

import os
from typing import Any

from clio_agent_graph.matching.models import IssueRetrievalRequest
from clio_agent_graph.normalization.models import NormalizeReportInput
from clio_agent_graph.retrieval.errors import RetrievalConfigurationError
from clio_agent_graph.retrieval.models import (
    BugIndexInput,
    BugIndexResult,
    BugSearchHit,
    BugSearchQuery,
    HydratedIssue,
    RetrievalScope,
)


class PostgresRetrievalRepository:
    """SQLAlchemy engine을 최초 DB operation까지 만들지 않는 PostgreSQL adapter."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._engine: Any | None = None

    def load_scope(
        self,
        request: IssueRetrievalRequest,
        *,
        embedding_model: str,
        embedding_dimension: int,
    ) -> RetrievalScope:
        """실제 SQL 구현은 schema migration과 함께 다음 커밋에서 추가한다."""

        raise NotImplementedError

    def search_exact(
        self, query: BugSearchQuery, scope: RetrievalScope, *, limit: int
    ) -> list[BugSearchHit]:
        """오류 식별자 exact 검색을 실행한다."""

        raise NotImplementedError

    def search_lexical(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        limit: int,
        threshold: float,
    ) -> list[BugSearchHit]:
        """pg_trgm 검색을 실행한다."""

        raise NotImplementedError

    def search_vector(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        embedding: list[float],
        embedding_model: str,
        limit: int,
    ) -> list[BugSearchHit]:
        """pgvector cosine 검색을 실행한다."""

        raise NotImplementedError

    def hydrate_issues(
        self,
        request: IssueRetrievalRequest,
        bug_ids: list[int],
        *,
        issue_limit: int,
    ) -> list[HydratedIssue]:
        """Issue와 active Bug snapshot을 조회한다."""

        raise NotImplementedError

    def save_index(
        self,
        request: BugIndexInput,
        *,
        search_text: str,
        document_hash: str,
        embedding: list[float],
        embedding_model: str,
    ) -> BugIndexResult:
        """새 snapshot과 embedding을 트랜잭션으로 저장한다."""

        raise NotImplementedError

    def load_backfill_batch(
        self, project_id: int, *, after_bug_id: int, limit: int
    ) -> tuple[list[tuple[int, NormalizeReportInput]], bool]:
        """과거 Bug를 최신 occurrence와 함께 읽는다."""

        raise NotImplementedError

    def _get_engine(self) -> Any:
        """DB URL을 확인하고 SQLAlchemy engine을 지연 생성한다."""

        if self._engine is None:
            database_url = self._database_url or os.getenv("CLIO_DATABASE_URL")
            if database_url is None or not database_url.strip():
                raise RetrievalConfigurationError("CLIO_DATABASE_URL is not configured.")
            from sqlalchemy import create_engine

            self._engine = create_engine(
                database_url.strip(),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
        return self._engine
