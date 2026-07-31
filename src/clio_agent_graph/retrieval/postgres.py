"""SQLAlchemy Core로 구현한 PostgreSQL Hybrid 검색·색인 adapter."""

import json
import os
from typing import Any

from sqlalchemy import Engine, create_engine, text

from clio_agent_graph.matching.models import IssueRetrievalRequest
from clio_agent_graph.normalization.models import NormalizedReport, NormalizeReportInput
from clio_agent_graph.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
)
from clio_agent_graph.retrieval.models import (
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
    ) -> None:
        self._database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._statement_timeout_seconds = statement_timeout_seconds
        self._engine: Engine | None = None

    def load_scope(
        self,
        request: IssueRetrievalRequest,
        *,
        embedding_model: str,
        embedding_dimension: int,
    ) -> RetrievalScope:
        """제외 Issue와 eligible corpus의 compatible index coverage를 계산한다."""

        params = {
            "project_id": request.project_id,
            "bug_id": request.bug_id,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
        }
        with self._get_engine().connect() as connection:
            excluded = (
                connection.execute(
                    text(
                        """
                    SELECT ib.issue_id
                    FROM issue_bugs ib
                    JOIN issues i ON i.id = ib.issue_id
                    WHERE ib.bug_id = :bug_id
                      AND i.project_id = :project_id
                    ORDER BY ib.issue_id
                    """
                    ),
                    params,
                )
                .scalars()
                .all()
            )
            counts = (
                connection.execute(
                    text(
                        """
                    WITH eligible AS (
                        SELECT DISTINCT ib.bug_id
                        FROM issue_bugs ib
                        JOIN issues i ON i.id = ib.issue_id
                        JOIN bugs b ON b.id = ib.bug_id
                        WHERE i.project_id = :project_id
                          AND b.project_id = :project_id
                          AND ib.bug_id <> :bug_id
                          AND NOT (ib.issue_id = ANY(CAST(:excluded_issue_ids AS bigint[])))
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
                    {**params, "excluded_issue_ids": list(excluded)},
                )
                .mappings()
                .one()
            )
        return RetrievalScope(
            excluded_issue_ids=list(excluded),
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
                SELECT DISTINCT d.id, d.bug_id, b.occurrence_count,
                       d.error_type, d.error_codes, d.stack_frames
                FROM bug_retrieval_documents d
                JOIN bugs b ON b.id = d.bug_id
                JOIN issue_bugs ib ON ib.bug_id = d.bug_id
                JOIN issues i ON i.id = ib.issue_id
                WHERE d.project_id = :project_id
                  AND b.project_id = :project_id
                  AND i.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
                  AND NOT (ib.issue_id = ANY(CAST(:excluded_issue_ids AS bigint[])))
            ), scored AS (
                SELECT *,
                    (:error_type IS NOT NULL AND error_type = CAST(:error_type AS text))
                        AS type_match,
                    (error_codes && CAST(:error_codes AS text[])) AS code_match,
                    (stack_frames && CAST(:stack_frames AS text[])) AS frame_match
                FROM eligible
            )
            SELECT bug_id, occurrence_count, type_match, code_match, frame_match,
                   ((CASE WHEN type_match THEN 1 ELSE 0 END) +
                    (CASE WHEN code_match THEN 3 ELSE 0 END) +
                    (CASE WHEN frame_match THEN 2 ELSE 0 END)) AS exact_score
            FROM scored
            WHERE type_match OR code_match OR frame_match
            ORDER BY exact_score DESC, occurrence_count DESC, bug_id ASC
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
                SELECT DISTINCT d.id, d.bug_id, d.search_text, b.occurrence_count
                FROM bug_retrieval_documents d
                JOIN bugs b ON b.id = d.bug_id
                JOIN issue_bugs ib ON ib.bug_id = d.bug_id
                JOIN issues i ON i.id = ib.issue_id
                WHERE d.project_id = :project_id
                  AND b.project_id = :project_id
                  AND i.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
                  AND NOT (ib.issue_id = ANY(CAST(:excluded_issue_ids AS bigint[])))
            ), scored AS (
                SELECT bug_id, occurrence_count,
                       GREATEST(
                           similarity(search_text, :search_text),
                           word_similarity(:search_text, search_text)
                       ) AS lexical_score
                FROM eligible
            )
            SELECT bug_id, lexical_score
            FROM scored
            WHERE lexical_score >= :threshold
            ORDER BY lexical_score DESC, occurrence_count DESC, bug_id ASC
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
                SELECT DISTINCT d.id, d.bug_id, b.occurrence_count, e.embedding
                FROM bug_retrieval_documents d
                JOIN bug_embeddings e ON e.retrieval_document_id = d.id
                JOIN bugs b ON b.id = d.bug_id
                JOIN issue_bugs ib ON ib.bug_id = d.bug_id
                JOIN issues i ON i.id = ib.issue_id
                WHERE d.project_id = :project_id
                  AND b.project_id = :project_id
                  AND i.project_id = :project_id
                  AND d.active
                  AND d.bug_id <> :bug_id
                  AND NOT (ib.issue_id = ANY(CAST(:excluded_issue_ids AS bigint[])))
                  AND e.embedding_model = :embedding_model
                  AND e.embedding_dimension = :embedding_dimension
            )
            SELECT bug_id,
                   GREATEST(0.0, LEAST(1.0,
                       1.0 - (embedding <=> CAST(:embedding AS vector))
                   )) AS vector_score
            FROM eligible
            ORDER BY embedding <=> CAST(:embedding AS vector), occurrence_count DESC, bug_id ASC
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
        """검색 순위가 높은 Bug가 속한 Issue와 active snapshot을 복원한다."""

        if not bug_ids:
            return []
        with self._get_engine().connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    WITH excluded AS (
                        SELECT ib.issue_id
                        FROM issue_bugs ib
                        JOIN issues i ON i.id = ib.issue_id
                        WHERE ib.bug_id = :current_bug_id
                          AND i.project_id = :project_id
                    ), candidate_issues AS (
                        SELECT ib.issue_id,
                               MIN(array_position(
                                   CAST(:bug_ids AS bigint[]), ib.bug_id
                               )) AS best_rank
                        FROM issue_bugs ib
                        JOIN issues i ON i.id = ib.issue_id
                        JOIN bugs b ON b.id = ib.bug_id
                        WHERE i.project_id = :project_id
                          AND b.project_id = :project_id
                          AND ib.bug_id = ANY(CAST(:bug_ids AS bigint[]))
                          AND ib.issue_id NOT IN (SELECT issue_id FROM excluded)
                        GROUP BY ib.issue_id
                        ORDER BY best_rank, ib.issue_id
                        LIMIT :issue_limit
                    )
                    SELECT ci.best_rank, i.id AS issue_id, i.title, i.summary, i.status,
                           b.id AS bug_id, b.occurrence_count, d.normalized_report
                    FROM candidate_issues ci
                    JOIN issues i ON i.id = ci.issue_id
                    JOIN issue_bugs ib ON ib.issue_id = i.id
                    JOIN bugs b ON b.id = ib.bug_id
                    JOIN bug_retrieval_documents d ON d.bug_id = b.id AND d.active
                    WHERE b.id = ANY(CAST(:bug_ids AS bigint[]))
                    ORDER BY ci.best_rank, i.id,
                             array_position(CAST(:bug_ids AS bigint[]), b.id), b.id
                    """
                    ),
                    {
                        "project_id": request.project_id,
                        "current_bug_id": request.bug_id,
                        "bug_ids": bug_ids,
                        "issue_limit": issue_limit,
                    },
                )
                .mappings()
                .all()
            )
        by_issue: dict[int, HydratedIssue] = {}
        for row in rows:
            issue_id = int(row["issue_id"])
            issue = by_issue.get(issue_id)
            if issue is None:
                issue = HydratedIssue(
                    issue_id=issue_id,
                    title=row["title"],
                    summary=row["summary"],
                    status=row["status"],
                )
                by_issue[issue_id] = issue
            issue.bugs.append(
                StoredRepresentativeBug(
                    bug_id=int(row["bug_id"]),
                    normalized_report=NormalizedReport.model_validate(row["normalized_report"]),
                    occurrence_count=int(row["occurrence_count"]),
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
        with self._get_engine().begin() as connection:
            # 같은 Bug의 동시 indexing 두 건이 version과 active 제약을 경합하지 않게 한다.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:bug_id)"), {"bug_id": request.bug_id}
            )
            valid = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM bugs b
                        JOIN bug_occurrences bo ON bo.bug_id = b.id
                        WHERE b.id = :bug_id
                          AND b.project_id = :project_id
                          AND bo.id = :bug_report_id
                    )
                    """
                ),
                {
                    "bug_id": request.bug_id,
                    "project_id": request.project_id,
                    "bug_report_id": request.normalized_report.bug_report_id,
                },
            ).scalar_one()
            if not valid:
                raise RetrievalDataError(
                    "project_id, bug_id and normalized_report.bug_report_id are not linked."
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
                            project_id, bug_id, bug_report_id, document_version,
                            document_hash, normalized_report, search_text,
                            error_type, error_codes, stack_frames, active
                        ) VALUES (
                            :project_id, :bug_id, :bug_report_id, :document_version,
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
                            "bug_report_id": request.normalized_report.bug_report_id,
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
        """Bug ID cursor 뒤의 최신 occurrence를 limit+1개 읽어 다음 page 여부를 계산한다."""

        with self._get_engine().connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT b.id AS bug_id, b.title, b.description, b.source,
                           b.error_type, b.normalized_message, b.top_application_frame,
                           occurrence.id AS bug_report_id, occurrence.raw_payload,
                           occurrence.occurred_at
                    FROM bugs b
                    JOIN LATERAL (
                        SELECT bo.id, bo.raw_payload, bo.occurred_at
                        FROM bug_occurrences bo
                        WHERE bo.bug_id = b.id
                        ORDER BY bo.occurred_at DESC, bo.id DESC
                        LIMIT 1
                    ) occurrence ON true
                    WHERE b.project_id = :project_id
                      AND b.id > :after_bug_id
                    ORDER BY b.id
                    LIMIT :fetch_limit
                    """
                    ),
                    {
                        "project_id": project_id,
                        "after_bug_id": after_bug_id,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        has_more = len(rows) > limit
        result: list[tuple[int, NormalizeReportInput]] = []
        for row in rows[:limit]:
            stack_trace = [row["top_application_frame"]] if row["top_application_frame"] else []
            result.append(
                (
                    int(row["bug_id"]),
                    NormalizeReportInput(
                        bug_report_id=int(row["bug_report_id"]),
                        title=row["title"],
                        description=row["description"],
                        source=row["source"],
                        error_type=row["error_type"],
                        message=row["normalized_message"],
                        stack_trace=stack_trace,
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
        bug_report_id=request.normalized_report.bug_report_id,
        document_id=int(document["id"]),
        document_version=int(document["document_version"]),
        document_hash=document_hash,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        status=status,
    )
