"""SQLAlchemy Core로 구현한 PostgreSQL Hybrid 검색·색인 adapter."""

import json
import os
from typing import Any

from sqlalchemy import Engine, create_engine, text

from clio_agent_graph.context.clio_server import ClioServer, ClioServerClient
from clio_agent_graph.workflows.reporting.matching.models import IssueRetrievalRequest
from clio_agent_graph.workflows.reporting.normalization.models import (
    NormalizedReport,
    NormalizeReportInput,
)
from clio_agent_graph.workflows.reporting.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
)
from clio_agent_graph.workflows.reporting.retrieval.models import (
    BugIndexInput,
    BugIndexResult,
    BugSearchHit,
    BugSearchQuery,
    HydratedIssue,
    IndexStatus,
    RetrievalScope,
    SearchChannel,
    StoredRepresentativeBug,
)


class PostgresRetrievalRepository:
    """도메인 테이블은 읽고 Python 소유 RAG 테이블만 쓰는 adapter."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connect_timeout_seconds: int = 5,
        statement_timeout_seconds: int = 5,
        clio_server: ClioServer | None = None,
    ) -> None:
        self._database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._statement_timeout_seconds = statement_timeout_seconds
        self._clio_server = clio_server or ClioServerClient.from_env()
        self._engine: Engine | None = None

    def load_scope(
        self,
        request: IssueRetrievalRequest,
        *,
        embedding_model: str,
        embedding_dimension: int,
    ) -> RetrievalScope:
        """Agent 소유 corpus의 compatible index coverage를 계산한다."""

        params = {
            "project_id": request.project_id,
            "bug_id": request.bug_id,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
        }
        with self._get_engine().connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                    WITH eligible AS (
                        SELECT DISTINCT d.bug_id
                        FROM bug_retrieval_documents d
                        WHERE d.project_id = :project_id
                          AND d.bug_id <> :bug_id
                          AND d.active
                    )
                    SELECT
                        COUNT(*) AS eligible_bug_count,
                        COUNT(*) FILTER (
                            WHERE EXISTS (
                                SELECT 1
                                FROM bug_retrieval_documents d
                                JOIN bug_embeddings e ON e.retrieval_document_id = d.id
                                WHERE d.bug_id = eligible.bug_id
                                  AND d.project_id = :project_id
                                  AND d.active
                                  AND e.embedding_model = :embedding_model
                                  AND e.embedding_dimension = :embedding_dimension
                            )
                        ) AS indexed_bug_count
                    FROM eligible
                    """
                    ),
                    params,
                )
                .mappings()
                .one()
            )
        return RetrievalScope(
            excluded_issue_ids=[],
            eligible_bug_count=int(counts["eligible_bug_count"]),
            indexed_bug_count=int(counts["indexed_bug_count"]),
        )

    def search_exact(
        self, query: BugSearchQuery, scope: RetrievalScope, *, limit: int
    ) -> list[BugSearchHit]:
        """오류 type·code·stack frame의 exact category 일치로 순위를 만든다."""

        rows = self._execute_search(
            """
            WITH eligible AS (
                SELECT DISTINCT d.id, d.bug_id, d.error_type, d.error_codes, d.stack_frames
                FROM bug_retrieval_documents d
                WHERE d.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
            ), scored AS (
                SELECT *,
                    (CAST(:error_type AS text) IS NOT NULL
                     AND error_type = CAST(:error_type AS text))
                        AS type_match,
                    (error_codes && CAST(:error_codes AS text[])) AS code_match,
                    (stack_frames && CAST(:stack_frames AS text[])) AS frame_match
                FROM eligible
            )
            SELECT bug_id, type_match, code_match, frame_match,
                   ((CASE WHEN type_match THEN 1 ELSE 0 END) +
                    (CASE WHEN code_match THEN 3 ELSE 0 END) +
                    (CASE WHEN frame_match THEN 2 ELSE 0 END)) AS exact_score
            FROM scored
            WHERE type_match OR code_match OR frame_match
            ORDER BY exact_score DESC, bug_id ASC
            LIMIT :limit
            """,
            query,
            scope,
            {
                "error_type": query.error_type,
                "error_codes": query.error_codes,
                "stack_frames": query.stack_frames,
                "limit": limit,
            },
        )
        hits: list[BugSearchHit] = []
        for rank, row in enumerate(rows, start=1):
            reasons: list[str] = []
            if row["type_match"]:
                reasons.append("오류 유형이 정확히 일치한다.")
            if row["code_match"]:
                reasons.append("오류 코드가 정확히 일치한다.")
            if row["frame_match"]:
                reasons.append("stack frame이 정확히 일치한다.")
            hits.append(
                BugSearchHit(
                    bug_id=int(row["bug_id"]),
                    channel=SearchChannel.EXACT,
                    rank=rank,
                    raw_score=float(row["exact_score"]) / 6.0,
                    matched_signals=reasons,
                    exact_signal_count=sum(
                        bool(row[name]) for name in ("type_match", "code_match", "frame_match")
                    ),
                )
            )
        return hits

    def search_lexical(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        limit: int,
        threshold: float,
    ) -> list[BugSearchHit]:
        """전체 문장과 부분 표현을 함께 보는 pg_trgm 검색을 실행한다."""

        rows = self._execute_search(
            """
            WITH eligible AS (
                SELECT DISTINCT d.id, d.bug_id, d.search_text
                FROM bug_retrieval_documents d
                WHERE d.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
            ), scored AS (
                SELECT bug_id,
                       GREATEST(
                           similarity(search_text, :search_text),
                           word_similarity(:search_text, search_text)
                       ) AS lexical_score
                FROM eligible
            )
            SELECT bug_id, lexical_score
            FROM scored
            WHERE lexical_score >= :threshold
            ORDER BY lexical_score DESC, bug_id ASC
            LIMIT :limit
            """,
            query,
            scope,
            {"search_text": query.search_text, "threshold": threshold, "limit": limit},
        )
        return [
            BugSearchHit(
                bug_id=int(row["bug_id"]),
                channel=SearchChannel.LEXICAL,
                rank=rank,
                raw_score=float(row["lexical_score"]),
                matched_signals=["정규화된 현상과 문자열 표현이 유사하다."],
            )
            for rank, row in enumerate(rows, start=1)
        ]

    def search_vector(
        self,
        query: BugSearchQuery,
        scope: RetrievalScope,
        *,
        embedding: list[float],
        embedding_model: str,
        limit: int,
    ) -> list[BugSearchHit]:
        """동일 model·dimension의 active 문서만 cosine 유사도로 검색한다."""

        rows = self._execute_search(
            """
            WITH eligible AS (
                SELECT DISTINCT d.id, d.bug_id, e.embedding
                FROM bug_retrieval_documents d
                JOIN bug_embeddings e ON e.retrieval_document_id = d.id
                WHERE d.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
                  AND e.embedding_model = :embedding_model
                  AND e.embedding_dimension = :embedding_dimension
            )
            SELECT bug_id,
                   GREATEST(0.0, LEAST(1.0,
                       1.0 - (embedding <=> CAST(:embedding AS vector))
                   )) AS vector_score
            FROM eligible
            ORDER BY embedding <=> CAST(:embedding AS vector), bug_id ASC
            LIMIT :limit
            """,
            query,
            scope,
            {
                "embedding": _vector_literal(embedding),
                "embedding_model": embedding_model,
                "embedding_dimension": len(embedding),
                "limit": limit,
            },
        )
        return [
            BugSearchHit(
                bug_id=int(row["bug_id"]),
                channel=SearchChannel.VECTOR,
                rank=rank,
                raw_score=float(row["vector_score"]),
                matched_signals=["정규화된 현상의 의미 벡터가 유사하다."],
            )
            for rank, row in enumerate(rows, start=1)
        ]

    def hydrate_issues(
        self,
        request: IssueRetrievalRequest,
        bug_ids: list[int],
        *,
        issue_limit: int,
    ) -> list[HydratedIssue]:
        """Spring에서 lifecycle 연결을 읽고 Agent snapshot과 결합한다."""

        if not bug_ids:
            return []
        links = self._clio_server.candidate_bug_links(
            request.project_id, [request.bug_id, *bug_ids]
        )
        current_issue_ids = {
            int(link["issue_id"]) for link in links if int(link["bug_id"]) == request.bug_id
        }
        links_by_bug = {
            int(link["bug_id"]): link
            for link in links
            if int(link["bug_id"]) != request.bug_id
            and int(link["issue_id"]) not in current_issue_ids
        }
        linked_bug_ids = [bug_id for bug_id in bug_ids if bug_id in links_by_bug]
        if not linked_bug_ids:
            return []
        with self._get_engine().connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT d.bug_id, d.normalized_report
                    FROM bug_retrieval_documents d
                    WHERE d.project_id = :project_id
                      AND d.active
                      AND d.bug_id = ANY(CAST(:bug_ids AS bigint[]))
                    ORDER BY array_position(CAST(:bug_ids AS bigint[]), d.bug_id), d.bug_id
                    """
                    ),
                    {
                        "project_id": request.project_id,
                        "bug_ids": linked_bug_ids,
                    },
                )
                .mappings()
                .all()
            )
        by_issue: dict[int, HydratedIssue] = {}
        for row in rows:
            link = links_by_bug[int(row["bug_id"])]
            issue_id = int(link["issue_id"])
            issue = by_issue.get(issue_id)
            if issue is None:
                if len(by_issue) == issue_limit:
                    continue
                issue = HydratedIssue(
                    issue_id=issue_id,
                    title=link.get("issue_title"),
                    summary=link.get("issue_summary"),
                    status=link.get("issue_status"),
                )
                by_issue[issue_id] = issue
            issue.bugs.append(
                StoredRepresentativeBug(
                    bug_id=int(row["bug_id"]),
                    normalized_report=NormalizedReport.model_validate(row["normalized_report"]),
                    occurrence_count=1,
                )
            )
        return list(by_issue.values())

    def save_index(
        self,
        request: BugIndexInput,
        *,
        search_text: str,
        document_hash: str,
        embedding: list[float],
        embedding_model: str,
    ) -> BugIndexResult:
        """같은 snapshot은 재사용하고 새 snapshot은 active 상태를 원자적으로 전환한다."""

        signals = request.normalized_report.error_signals
        if request.normalized_report.bug_id != request.bug_id:
            raise RetrievalDataError("normalized_report.bug_id must match bug_id.")
        source_bug = self._clio_server.load_bug(str(request.project_id), str(request.bug_id))
        if int(source_bug["bug_id"]) != request.bug_id:
            raise RetrievalDataError("Spring returned a different Bug identifier.")
        with self._get_engine().begin() as connection:
            # 같은 Bug의 동시 indexing 두 건이 version과 active 제약을 경합하지 않게 한다.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:bug_id)"), {"bug_id": request.bug_id}
            )
            active = (
                connection.execute(
                    text(
                        """
                    SELECT id, document_version, document_hash
                    FROM bug_retrieval_documents
                    WHERE bug_id = :bug_id AND active
                    FOR UPDATE
                    """
                    ),
                    {"bug_id": request.bug_id},
                )
                .mappings()
                .one_or_none()
            )
            if active is not None and active["document_hash"] == document_hash:
                existing_dimension = connection.execute(
                    text(
                        """
                        SELECT embedding_dimension
                        FROM bug_embeddings
                        WHERE retrieval_document_id = :document_id
                          AND embedding_model = :embedding_model
                        """
                    ),
                    {
                        "document_id": active["id"],
                        "embedding_model": embedding_model,
                    },
                ).scalar_one_or_none()
                if existing_dimension is not None:
                    if int(existing_dimension) != len(embedding):
                        raise RetrievalDataError(
                            "Stored embedding dimension differs for the same model ID."
                        )
                    return _index_result(
                        request,
                        active,
                        document_hash,
                        embedding_model,
                        len(embedding),
                        IndexStatus.UNCHANGED,
                    )
                document = active
            else:
                next_version = connection.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(document_version), 0) + 1
                        FROM bug_retrieval_documents
                        WHERE bug_id = :bug_id
                        """
                    ),
                    {"bug_id": request.bug_id},
                ).scalar_one()
                connection.execute(
                    text(
                        "UPDATE bug_retrieval_documents SET active = false "
                        "WHERE bug_id = :bug_id AND active"
                    ),
                    {"bug_id": request.bug_id},
                )
                document = (
                    connection.execute(
                        text(
                            """
                        INSERT INTO bug_retrieval_documents (
                            project_id, bug_id, document_version,
                            document_hash, normalized_report, search_text,
                            error_type, error_codes, stack_frames, active
                        ) VALUES (
                            :project_id, :bug_id, :document_version,
                            :document_hash, CAST(:normalized_report AS jsonb), :search_text,
                            :error_type, CAST(:error_codes AS text[]),
                            CAST(:stack_frames AS text[]), true
                        )
                        RETURNING id, document_version, document_hash
                        """
                        ),
                        {
                            "project_id": request.project_id,
                            "bug_id": request.bug_id,
                            "document_version": int(next_version),
                            "document_hash": document_hash,
                            "normalized_report": json.dumps(
                                request.normalized_report.model_dump(mode="json"),
                                ensure_ascii=False,
                            ),
                            "search_text": search_text,
                            "error_type": _normalize_signal(signals.error_type),
                            "error_codes": _normalized_signals(signals.error_codes),
                            "stack_frames": _normalized_signals(signals.stack_frames),
                        },
                    )
                    .mappings()
                    .one()
                )

            connection.execute(
                text(
                    """
                    INSERT INTO bug_embeddings (
                        retrieval_document_id, embedding, embedding_model, embedding_dimension
                    ) VALUES (
                        :document_id, CAST(:embedding AS vector),
                        :embedding_model, :embedding_dimension
                    )
                    """
                ),
                {
                    "document_id": document["id"],
                    "embedding": _vector_literal(embedding),
                    "embedding_model": embedding_model,
                    "embedding_dimension": len(embedding),
                },
            )
            return _index_result(
                request,
                document,
                document_hash,
                embedding_model,
                len(embedding),
                IndexStatus.CREATED,
            )

    def load_backfill_batch(
        self, project_id: int, *, after_bug_id: int, limit: int
    ) -> tuple[list[tuple[int, NormalizeReportInput]], bool]:
        """Spring internal API에서 Bug 원문 batch를 읽는다."""

        rows = self._clio_server.list_bugs(
            str(project_id), after_bug_id=after_bug_id, limit=limit + 1
        )
        has_more = len(rows) > limit
        result: list[tuple[int, NormalizeReportInput]] = []
        for row in rows[:limit]:
            result.append(
                (
                    int(row["bug_id"]),
                    NormalizeReportInput(
                        bug_id=int(row["bug_id"]),
                        title=row["title"],
                        description=row["description"],
                        source=row["source"],
                        error_type=row["error_type"],
                        message=row["message"],
                        stack_trace=row.get("stack_trace", []),
                        occurred_at=row["occurred_at"],
                        raw_payload=row["raw_payload"] or {},
                    ),
                )
            )
        return result, has_more

    def _execute_search(
        self,
        sql: str,
        query: BugSearchQuery,
        scope: RetrievalScope,
        extra: dict[str, object],
    ) -> list[dict[str, Any]]:
        """모든 검색 SQL에 project·현재 Bug·제외 Issue 조건을 같은 방식으로 전달한다."""

        params = {
            "project_id": query.project_id,
            "bug_id": query.bug_id,
            "excluded_issue_ids": scope.excluded_issue_ids,
            **extra,
        }
        with self._get_engine().connect() as connection:
            return [dict(row) for row in connection.execute(text(sql), params).mappings().all()]

    def _get_engine(self) -> Engine:
        """DB URL을 확인하고 SQLAlchemy engine을 최초 operation에서 생성한다."""

        if self._engine is None:
            database_url = self._database_url or os.getenv("CLIO_DATABASE_URL")
            if database_url is None or not database_url.strip():
                raise RetrievalConfigurationError("CLIO_DATABASE_URL is not configured.")
            self._engine = create_engine(
                normalize_database_url(database_url),
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": self._connect_timeout_seconds,
                    "options": f"-c statement_timeout={self._statement_timeout_seconds * 1000}",
                },
            )
        return self._engine


def normalize_database_url(database_url: str) -> str:
    """일반 PostgreSQL URL도 설치한 psycopg3 driver를 명시하도록 바꾼다."""

    value = database_url.strip()
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    return value


def _vector_literal(embedding: list[float]) -> str:
    """pgvector가 이해하는 안전한 숫자 배열 literal을 만든다."""

    return "[" + ",".join(format(float(value), ".17g") for value in embedding) + "]"


def _normalize_signal(value: str | None) -> str | None:
    """색인 exact signal을 query와 같은 규칙으로 정규화한다."""

    if value is None:
        return None
    return " ".join(value.casefold().split()) or None


def _normalized_signals(values: list[str]) -> list[str]:
    """exact signal 목록을 정규화하고 순서를 유지해 중복 제거한다."""

    result: list[str] = []
    for value in values:
        normalized = _normalize_signal(value)
        if normalized is not None and normalized not in result:
            result.append(normalized)
    return result


def _index_result(
    request: BugIndexInput,
    document: Any,
    document_hash: str,
    embedding_model: str,
    embedding_dimension: int,
    status: IndexStatus,
) -> BugIndexResult:
    """DB row와 공개 색인 결과의 식별자를 한곳에서 조립한다."""

    return BugIndexResult(
        project_id=request.project_id,
        bug_id=request.bug_id,
        document_id=int(document["id"]),
        document_version=int(document["document_version"]),
        document_hash=document_hash,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        status=status,
    )
