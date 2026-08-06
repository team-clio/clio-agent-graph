"""PostgreSQL metadata와 immutable Markdown을 사용하는 영속 PCM 구현."""

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import asyncpg

from clio_agent_graph.services.pcm.chunking import MarkdownKnowledgeChunker
from clio_agent_graph.services.pcm.embedding import (
    DeterministicLocalEmbedding,
    EmbeddingProvider,
)
from clio_agent_graph.services.pcm.errors import (
    KnowledgeNotFoundError,
    PCMRevisionConflict,
    PCMValidationError,
)
from clio_agent_graph.services.pcm.models import (
    IngestDocumentCommand,
    KnowledgeChange,
    KnowledgeChangeSet,
    KnowledgeChunk,
    KnowledgeCommitResult,
    KnowledgeDocument,
    KnowledgeSearchPage,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectContextSnapshot,
    SourceReference,
)
from clio_agent_graph.services.pcm.storage import MarkdownStore

_TOKEN_PATTERN = re.compile(r"[\w./:{}-]+", re.UNICODE)
logger = logging.getLogger(__name__)


class PostgresPCM:
    """프로세스 재시작 뒤에도 snapshot과 event 멱등성을 보존한다."""

    def __init__(
        self,
        *,
        database_url: str,
        markdown_store: MarkdownStore,
        embedding_provider: EmbeddingProvider | None = None,
        chunker: MarkdownKnowledgeChunker | None = None,
    ) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._markdown_store = markdown_store
        self._embedding_provider = embedding_provider or DeterministicLocalEmbedding()
        if self._embedding_provider.dimensions != 384:
            raise ValueError("The current pgvector schema requires 384 embedding dimensions.")
        self._chunker = chunker or MarkdownKnowledgeChunker()
        self._pool: asyncpg.Pool | None = None
        self._initialization_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._ensure_pool()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save_document_source(self, command: IngestDocumentCommand) -> str:
        storage_path = await self._markdown_store.save_document_source(command)
        pool = await self._ensure_pool()
        content_hash = f"sha256:{hashlib.sha256(command.markdown.strip().encode()).hexdigest()}"
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO pcm_document_revisions (
                    project_id, document_id, source_revision, title,
                    content_hash, storage_path, source_metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (project_id, document_id, source_revision) DO UPDATE
                SET title = EXCLUDED.title,
                    source_metadata = EXCLUDED.source_metadata
                WHERE pcm_document_revisions.content_hash = EXCLUDED.content_hash
                  AND pcm_document_revisions.storage_path = EXCLUDED.storage_path
                """,
                command.project_id,
                command.document_id,
                command.revision,
                command.title,
                content_hash,
                storage_path,
                json.dumps(command.source_metadata),
            )
        return storage_path

    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot:
        pool = await self._ensure_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT active_pcm_revision, knowledge_index_revision
                FROM pcm_projects WHERE project_id = $1
                """,
                project_id,
            )
        return ProjectContextSnapshot(
            project_id=project_id,
            pcm_revision=row["active_pcm_revision"] if row else 0,
            knowledge_index_revision=row["knowledge_index_revision"] if row else 0,
        )

    async def find_commit_by_event(
        self,
        *,
        project_id: str,
        source_event_id: str,
    ) -> KnowledgeCommitResult | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                """
                SELECT commit_result FROM pcm_source_events
                WHERE project_id = $1 AND source_event_id = $2 AND status = 'completed'
                """,
                project_id,
                source_event_id,
            )
        if value is None:
            return None
        return KnowledgeCommitResult.model_validate(_json_value(value)).model_copy(
            update={"idempotent_replay": True}
        )

    async def apply_knowledge_changes(
        self,
        *,
        project_id: str,
        change_set: KnowledgeChangeSet,
    ) -> KnowledgeCommitResult:
        pool = await self._ensure_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """
                INSERT INTO pcm_projects (project_id) VALUES ($1)
                ON CONFLICT (project_id) DO NOTHING
                """,
                project_id,
            )
            project = await connection.fetchrow(
                """
                SELECT active_pcm_revision FROM pcm_projects
                WHERE project_id = $1 FOR UPDATE
                """,
                project_id,
            )
            replay = await self._find_commit_with_connection(
                connection,
                project_id=project_id,
                source_event_id=change_set.source_event_id,
            )
            if replay is not None:
                return replay
            current_revision = int(project["active_pcm_revision"])
            if change_set.base_pcm_revision != current_revision:
                raise PCMRevisionConflict(
                    expected=change_set.base_pcm_revision,
                    actual=current_revision,
                )

            existing = await self._load_change_targets(
                connection,
                project_id=project_id,
                changes=change_set.changes,
                pcm_revision=current_revision,
            )
            material = tuple(
                change for change in change_set.changes if change.operation != "no_change"
            )
            target_revision = current_revision + 1 if material else current_revision
            commit_id = uuid4()
            documents = _plan_documents(
                project_id=project_id,
                changes=material,
                existing=existing,
                target_pcm_revision=target_revision,
            )
            storage_paths = {
                document.knowledge_id: await self._markdown_store.save_knowledge(document)
                for document in documents
            }
            result = _commit_result(
                commit_id=commit_id,
                project_id=project_id,
                change_set=change_set,
                pcm_revision=target_revision,
                documents=documents,
            )
            await connection.execute(
                """
                INSERT INTO pcm_commits (
                    commit_id, project_id, source_event_id,
                    base_pcm_revision, target_pcm_revision, change_summary
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                commit_id,
                project_id,
                change_set.source_event_id,
                current_revision,
                target_revision,
                result.model_dump_json(),
            )
            for document, change in zip(documents, material, strict=True):
                if change.operation == "create":
                    await connection.execute(
                        """
                        INSERT INTO pcm_knowledge (project_id, knowledge_id, logical_key)
                        VALUES ($1, $2, $3)
                        """,
                        project_id,
                        document.knowledge_id,
                        document.logical_key,
                    )
                else:
                    await connection.execute(
                        """
                        UPDATE pcm_knowledge_revisions
                        SET valid_until_pcm_revision = $3
                        WHERE project_id = $1 AND knowledge_id = $2
                          AND valid_until_pcm_revision IS NULL
                        """,
                        project_id,
                        document.knowledge_id,
                        target_revision,
                    )
                await self._insert_revision(
                    connection,
                    document=document,
                    storage_path=storage_paths[document.knowledge_id],
                    commit_id=commit_id,
                )
            if material:
                await connection.execute(
                    """
                    UPDATE pcm_projects
                    SET active_pcm_revision = $2,
                        updated_at = now()
                    WHERE project_id = $1
                    """,
                    project_id,
                    target_revision,
                )
            await connection.execute(
                """
                INSERT INTO pcm_source_events (
                    project_id, source_event_id, status, commit_result
                ) VALUES ($1, $2, 'completed', $3::jsonb)
                """,
                project_id,
                change_set.source_event_id,
                result.model_dump_json(),
            )
        if material:
            try:
                await self._index_documents(
                    project_id=project_id,
                    pcm_revision=target_revision,
                    documents=documents,
                )
            except Exception:
                logger.exception(
                    "PCM Knowledge commit succeeded but indexing failed",
                    extra={"project_id": project_id, "pcm_revision": target_revision},
                )
        return result

    async def read_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument:
        pool = await self._ensure_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                _SNAPSHOT_DOCUMENT_SQL + " AND kr.knowledge_id = $3",
                snapshot.project_id,
                snapshot.pcm_revision,
                knowledge_id,
            )
        if row is None or row["is_tombstone"]:
            raise KnowledgeNotFoundError(
                f"Knowledge {knowledge_id!r} is unavailable at revision {snapshot.pcm_revision}."
            )
        return await self._document_from_row(row)

    async def trace_knowledge_sources(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> tuple[SourceReference, ...]:
        return (await self.read_knowledge(snapshot=snapshot, knowledge_id=knowledge_id)).sources

    async def search_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchPage:
        tokens = _tokens(request.query)
        if not tokens:
            raise PCMValidationError("Knowledge search query must contain searchable text.")
        pool = await self._ensure_pool()
        if snapshot.knowledge_index_revision < snapshot.pcm_revision:
            fallback = await self._fallback_keyword_search(
                snapshot=snapshot,
                request=request,
                tokens=tokens,
            )
            return KnowledgeSearchPage(
                project_id=snapshot.project_id,
                pcm_revision=snapshot.pcm_revision,
                results=tuple(fallback),
                vector_search_used=False,
                keyword_search_used=True,
                vector_index_stale=True,
            )
        vector_search_used = False
        vector_rows: Sequence[asyncpg.Record] = ()
        try:
            query_embedding = await self._embedding_provider.embed_query(request.query)
            async with pool.acquire() as connection:
                vector_rows = await connection.fetch(
                    _VECTOR_SEARCH_SQL,
                    snapshot.project_id,
                    snapshot.pcm_revision,
                    _vector_literal(query_embedding),
                    request.limit * 4,
                )
            vector_search_used = True
        except Exception:
            logger.exception(
                "PCM vector query failed; continuing with keyword retrieval",
                extra={"project_id": snapshot.project_id},
            )
        async with pool.acquire() as connection:
            keyword_rows = await connection.fetch(
                _KEYWORD_SEARCH_SQL,
                snapshot.project_id,
                snapshot.pcm_revision,
                request.query,
                request.limit * 4,
            )
        fused = _reciprocal_rank_fusion(vector_rows=vector_rows, keyword_rows=keyword_rows)
        results: list[KnowledgeSearchResult] = []
        seen_knowledge: set[str] = set()
        for row, score in fused:
            if row["knowledge_id"] in seen_knowledge:
                continue
            if request.knowledge_types and row["knowledge_type"] not in request.knowledge_types:
                continue
            seen_knowledge.add(row["knowledge_id"])
            results.append(
                KnowledgeSearchResult(
                    knowledge_id=row["knowledge_id"],
                    knowledge_revision=row["knowledge_revision"],
                    knowledge_type=row["knowledge_type"],
                    title=row["title"],
                    matched_content=row["content"][:1500],
                    score=score,
                    sources=tuple(
                        SourceReference.model_validate(source)
                        for source in _json_value(row["sources"])
                    ),
                )
            )
            if len(results) == request.limit:
                break
        if not results:
            results = await self._fallback_keyword_search(
                snapshot=snapshot,
                request=request,
                tokens=tokens,
            )
        return KnowledgeSearchPage(
            project_id=snapshot.project_id,
            pcm_revision=snapshot.pcm_revision,
            results=tuple(results),
            vector_search_used=vector_search_used,
            keyword_search_used=True,
            vector_index_stale=(snapshot.knowledge_index_revision < snapshot.pcm_revision),
        )

    async def _fallback_keyword_search(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
        tokens: set[str],
    ) -> list[KnowledgeSearchResult]:
        """인덱스가 비어 있거나 지연될 때 canonical Markdown을 직접 검색한다."""

        pool = await self._ensure_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                _SNAPSHOT_DOCUMENT_SQL,
                snapshot.project_id,
                snapshot.pcm_revision,
            )
        results: list[KnowledgeSearchResult] = []
        for row in rows:
            if row["is_tombstone"]:
                continue
            if request.knowledge_types and row["knowledge_type"] not in request.knowledge_types:
                continue
            document = await self._document_from_row(row)
            overlap = tokens & _tokens(f"{document.title}\n{document.body_markdown}")
            if not overlap:
                continue
            results.append(
                KnowledgeSearchResult(
                    knowledge_id=document.knowledge_id,
                    knowledge_revision=document.knowledge_revision,
                    knowledge_type=document.knowledge_type,
                    title=document.title,
                    matched_content=document.body_markdown[:1500],
                    score=len(overlap) / len(tokens),
                    sources=document.sources,
                )
            )
        results.sort(key=lambda item: (-item.score, item.knowledge_id))
        return results[: request.limit]

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._initialization_lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=5)
                await self._apply_migrations(self._pool)
                await self._backfill_stale_indexes(self._pool)
        return self._pool

    async def _index_documents(
        self,
        *,
        project_id: str,
        pcm_revision: int,
        documents: Sequence[KnowledgeDocument],
    ) -> None:
        pool = await self._ensure_pool()
        chunks = tuple(chunk for document in documents for chunk in self._chunker.chunk(document))
        async with pool.acquire() as connection, connection.transaction():
            generation_id = await self._ensure_index_generation(connection, project_id)
            knowledge_ids = tuple(document.knowledge_id for document in documents)
            if knowledge_ids:
                await connection.execute(
                    """
                    UPDATE pcm_knowledge_chunks
                    SET valid_until_pcm_revision = $3
                    WHERE project_id = $1
                      AND knowledge_id = ANY($2::text[])
                      AND valid_until_pcm_revision IS NULL
                    """,
                    project_id,
                    list(knowledge_ids),
                    pcm_revision,
                )
            missing_embeddings: list[KnowledgeChunk] = []
            for chunk in chunks:
                await connection.execute(
                    """
                    INSERT INTO pcm_knowledge_chunks (
                        chunk_id, project_id, knowledge_id, knowledge_revision,
                        heading_path, content, content_hash, chunker_version,
                        valid_from_pcm_revision
                    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
                    ON CONFLICT (chunk_id) DO NOTHING
                    """,
                    chunk.chunk_id,
                    chunk.project_id,
                    chunk.knowledge_id,
                    chunk.knowledge_revision,
                    json.dumps(list(chunk.heading_path)),
                    chunk.content,
                    chunk.content_hash,
                    chunk.chunker_version,
                    chunk.valid_from_pcm_revision,
                )
                copied = await connection.execute(
                    """
                    INSERT INTO pcm_chunk_embeddings (
                        generation_id, chunk_id, content_hash, embedding
                    )
                    SELECT $1, $2, $3, existing.embedding
                    FROM pcm_chunk_embeddings existing
                    WHERE existing.generation_id = $1
                      AND existing.content_hash = $3
                    LIMIT 1
                    ON CONFLICT (generation_id, chunk_id) DO NOTHING
                    """,
                    generation_id,
                    chunk.chunk_id,
                    chunk.content_hash,
                )
                if copied == "INSERT 0 0":
                    missing_embeddings.append(chunk)
            if missing_embeddings:
                embeddings = await self._embedding_provider.embed_documents(
                    [chunk.content for chunk in missing_embeddings]
                )
                for chunk, embedding in zip(missing_embeddings, embeddings, strict=True):
                    await connection.execute(
                        """
                        INSERT INTO pcm_chunk_embeddings (
                            generation_id, chunk_id, content_hash, embedding
                        ) VALUES ($1, $2, $3, $4::vector)
                        ON CONFLICT (generation_id, chunk_id) DO NOTHING
                        """,
                        generation_id,
                        chunk.chunk_id,
                        chunk.content_hash,
                        _vector_literal(embedding),
                    )
            await connection.execute(
                """
                UPDATE pcm_index_generations
                SET indexed_pcm_revision = $2,
                    status = 'active',
                    activated_at = COALESCE(activated_at, now())
                WHERE generation_id = $1
                """,
                generation_id,
                pcm_revision,
            )
            await connection.execute(
                """
                UPDATE pcm_projects
                SET active_index_generation = $2,
                    knowledge_index_revision = $3,
                    updated_at = now()
                WHERE project_id = $1
                """,
                project_id,
                generation_id,
                pcm_revision,
            )

    async def _ensure_index_generation(
        self,
        connection: asyncpg.Connection,
        project_id: str,
    ) -> UUID:
        generation_id = await connection.fetchval(
            """
            SELECT generation_id FROM pcm_index_generations
            WHERE project_id = $1 AND embedding_model_id = $2 AND chunker_version = $3
            """,
            project_id,
            self._embedding_provider.model_id,
            self._chunker.version,
        )
        if generation_id is not None:
            return generation_id
        generation_id = uuid4()
        await connection.execute(
            """
            INSERT INTO pcm_index_generations (
                generation_id, project_id, embedding_model_id,
                dimensions, chunker_version, status
            ) VALUES ($1, $2, $3, $4, $5, 'building')
            """,
            generation_id,
            project_id,
            self._embedding_provider.model_id,
            self._embedding_provider.dimensions,
            self._chunker.version,
        )
        return generation_id

    async def _backfill_stale_indexes(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as connection:
            projects = await connection.fetch(
                """
                SELECT project_id, active_pcm_revision
                FROM pcm_projects
                WHERE knowledge_index_revision < active_pcm_revision
                """
            )
        for project in projects:
            try:
                async with pool.acquire() as connection:
                    rows = await connection.fetch(
                        _SNAPSHOT_DOCUMENT_SQL,
                        project["project_id"],
                        project["active_pcm_revision"],
                    )
                documents = tuple(
                    [await self._document_from_row(row) for row in rows if not row["is_tombstone"]]
                )
                await self._index_documents(
                    project_id=project["project_id"],
                    pcm_revision=project["active_pcm_revision"],
                    documents=documents,
                )
            except Exception:
                logger.exception(
                    "Failed to backfill stale PCM index",
                    extra={"project_id": project["project_id"]},
                )

    async def _apply_migrations(self, pool: asyncpg.Pool) -> None:
        migration_root = Path(__file__).with_name("migrations")
        async with pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pcm_schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await connection.execute("SELECT pg_advisory_lock(hashtext('clio_pcm_migrations'))")
            try:
                for migration in sorted(migration_root.glob("*.sql")):
                    applied = await connection.fetchval(
                        "SELECT 1 FROM pcm_schema_migrations WHERE version = $1",
                        migration.name,
                    )
                    if applied:
                        continue
                    async with connection.transaction():
                        await connection.execute(migration.read_text(encoding="utf-8"))
                        await connection.execute(
                            "INSERT INTO pcm_schema_migrations (version) VALUES ($1)",
                            migration.name,
                        )
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtext('clio_pcm_migrations'))"
                )

    async def _find_commit_with_connection(
        self,
        connection: asyncpg.Connection,
        *,
        project_id: str,
        source_event_id: str,
    ) -> KnowledgeCommitResult | None:
        value = await connection.fetchval(
            """
            SELECT commit_result FROM pcm_source_events
            WHERE project_id = $1 AND source_event_id = $2 AND status = 'completed'
            """,
            project_id,
            source_event_id,
        )
        if value is None:
            return None
        return KnowledgeCommitResult.model_validate(_json_value(value)).model_copy(
            update={"idempotent_replay": True}
        )

    async def _load_change_targets(
        self,
        connection: asyncpg.Connection,
        *,
        project_id: str,
        changes: Sequence[KnowledgeChange],
        pcm_revision: int,
    ) -> dict[str, KnowledgeDocument]:
        existing: dict[str, KnowledgeDocument] = {}
        logical_keys: set[str] = set()
        target_ids: set[str] = set()
        for change in changes:
            if change.operation == "create":
                assert change.logical_key is not None
                if change.logical_key in logical_keys or await connection.fetchval(
                    """
                    SELECT 1 FROM pcm_knowledge WHERE project_id = $1 AND logical_key = $2
                    """,
                    project_id,
                    change.logical_key,
                ):
                    raise PCMValidationError(
                        f"Knowledge logical key {change.logical_key!r} already exists."
                    )
                logical_keys.add(change.logical_key)
                continue
            assert change.target_knowledge_id is not None
            if change.target_knowledge_id in target_ids:
                raise PCMValidationError(
                    f"Knowledge {change.target_knowledge_id!r} changes more than once."
                )
            target_ids.add(change.target_knowledge_id)
            row = await connection.fetchrow(
                _SNAPSHOT_DOCUMENT_SQL + " AND kr.knowledge_id = $3",
                project_id,
                pcm_revision,
                change.target_knowledge_id,
            )
            if row is None or row["is_tombstone"]:
                raise KnowledgeNotFoundError(
                    f"Knowledge {change.target_knowledge_id!r} is not active."
                )
            existing[change.target_knowledge_id] = await self._document_from_row(row)
        return existing

    async def _insert_revision(
        self,
        connection: asyncpg.Connection,
        *,
        document: KnowledgeDocument,
        storage_path: str,
        commit_id: UUID,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO pcm_knowledge_revisions (
                project_id, knowledge_id, knowledge_revision, knowledge_type,
                title, storage_path, body_content_hash,
                valid_from_pcm_revision, valid_until_pcm_revision,
                sources, related_knowledge_ids, is_tombstone, created_by_commit_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, NULL,
                $9::jsonb, $10::jsonb, $11, $12
            )
            """,
            document.project_id,
            document.knowledge_id,
            document.knowledge_revision,
            document.knowledge_type,
            document.title,
            storage_path,
            f"sha256:{hashlib.sha256(document.body_markdown.encode()).hexdigest()}",
            document.valid_from_pcm_revision,
            json.dumps([source.model_dump(mode="json") for source in document.sources]),
            json.dumps(list(document.related_knowledge_ids)),
            document.is_tombstone,
            commit_id,
        )

    async def _document_from_row(self, row: asyncpg.Record) -> KnowledgeDocument:
        markdown = await self._markdown_store.read(row["storage_path"])
        return KnowledgeDocument(
            project_id=row["project_id"],
            knowledge_id=row["knowledge_id"],
            logical_key=row["logical_key"],
            knowledge_type=row["knowledge_type"],
            title=row["title"],
            body_markdown=_markdown_body(markdown),
            knowledge_revision=row["knowledge_revision"],
            valid_from_pcm_revision=row["valid_from_pcm_revision"],
            valid_until_pcm_revision=row["valid_until_pcm_revision"],
            sources=tuple(
                SourceReference.model_validate(source) for source in _json_value(row["sources"])
            ),
            related_knowledge_ids=tuple(_json_value(row["related_knowledge_ids"])),
            is_tombstone=row["is_tombstone"],
        )


_SNAPSHOT_DOCUMENT_SQL = """
SELECT kr.*, k.logical_key
FROM pcm_knowledge_revisions kr
JOIN pcm_knowledge k
  ON k.project_id = kr.project_id AND k.knowledge_id = kr.knowledge_id
WHERE kr.project_id = $1
  AND kr.valid_from_pcm_revision <= $2
  AND (
      kr.valid_until_pcm_revision IS NULL
      OR kr.valid_until_pcm_revision > $2
  )
"""

_INDEXED_CHUNK_SELECT = """
SELECT c.chunk_id, c.knowledge_id, c.knowledge_revision, c.content,
       kr.knowledge_type, kr.title, kr.sources
FROM pcm_knowledge_chunks c
JOIN pcm_knowledge_revisions kr
  ON kr.project_id = c.project_id
 AND kr.knowledge_id = c.knowledge_id
 AND kr.knowledge_revision = c.knowledge_revision
"""

_KEYWORD_SEARCH_SQL = (
    _INDEXED_CHUNK_SELECT
    + """
WHERE c.project_id = $1
  AND c.valid_from_pcm_revision <= $2
  AND (c.valid_until_pcm_revision IS NULL OR c.valid_until_pcm_revision > $2)
  AND (
      c.search_vector @@ plainto_tsquery('simple', $3)
      OR similarity(c.content, $3) > 0.08
  )
ORDER BY (
    ts_rank_cd(c.search_vector, plainto_tsquery('simple', $3))
    + similarity(c.content, $3)
) DESC, c.chunk_id
LIMIT $4
"""
)

_VECTOR_SEARCH_SQL = (
    _INDEXED_CHUNK_SELECT
    + """
JOIN pcm_chunk_embeddings e ON e.chunk_id = c.chunk_id
JOIN pcm_projects p
  ON p.project_id = c.project_id
 AND p.active_index_generation = e.generation_id
WHERE c.project_id = $1
  AND c.valid_from_pcm_revision <= $2
  AND (c.valid_until_pcm_revision IS NULL OR c.valid_until_pcm_revision > $2)
  AND (1 - (e.embedding <=> $3::vector)) >= 0.05
ORDER BY e.embedding <=> $3::vector, c.chunk_id
LIMIT $4
"""
)


def _plan_documents(
    *,
    project_id: str,
    changes: Sequence[KnowledgeChange],
    existing: dict[str, KnowledgeDocument],
    target_pcm_revision: int,
) -> tuple[KnowledgeDocument, ...]:
    documents: list[KnowledgeDocument] = []
    for change in changes:
        if change.operation == "create":
            assert change.logical_key is not None
            knowledge_id = _knowledge_id(project_id, change.logical_key)
            logical_key = change.logical_key
            knowledge_revision = 1
            previous = None
        else:
            assert change.target_knowledge_id is not None
            previous = existing[change.target_knowledge_id]
            knowledge_id = previous.knowledge_id
            logical_key = previous.logical_key
            knowledge_revision = previous.knowledge_revision + 1
        is_tombstone = change.operation == "tombstone"
        documents.append(
            KnowledgeDocument(
                project_id=project_id,
                knowledge_id=knowledge_id,
                logical_key=logical_key,
                knowledge_type=change.knowledge_type or _previous(previous).knowledge_type,
                title=change.title or _previous(previous).title,
                body_markdown="" if is_tombstone else change.body_markdown or "",
                knowledge_revision=knowledge_revision,
                valid_from_pcm_revision=target_pcm_revision,
                sources=change.sources,
                related_knowledge_ids=change.related_knowledge_ids,
                is_tombstone=is_tombstone,
            )
        )
    return tuple(documents)


def _commit_result(
    *,
    commit_id: UUID,
    project_id: str,
    change_set: KnowledgeChangeSet,
    pcm_revision: int,
    documents: Sequence[KnowledgeDocument],
) -> KnowledgeCommitResult:
    material = tuple(change for change in change_set.changes if change.operation != "no_change")
    return KnowledgeCommitResult(
        commit_id=str(commit_id),
        project_id=project_id,
        source_event_id=change_set.source_event_id,
        base_pcm_revision=change_set.base_pcm_revision,
        pcm_revision=pcm_revision,
        created_knowledge_ids=tuple(
            document.knowledge_id
            for document, change in zip(documents, material, strict=True)
            if change.operation == "create"
        ),
        updated_knowledge_ids=tuple(
            document.knowledge_id
            for document, change in zip(documents, material, strict=True)
            if change.operation == "update"
        ),
        tombstoned_knowledge_ids=tuple(
            document.knowledge_id
            for document, change in zip(documents, material, strict=True)
            if change.operation == "tombstone"
        ),
        unchanged_knowledge_ids=tuple(
            change.target_knowledge_id
            for change in change_set.changes
            if change.operation == "no_change" and change.target_knowledge_id
        ),
    )


def _knowledge_id(project_id: str, logical_key: str) -> str:
    return f"kn_{uuid5(NAMESPACE_URL, f'{project_id}:{logical_key}').hex}"


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(value)}


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in vector) + "]"


def _reciprocal_rank_fusion(
    *,
    vector_rows: Sequence[asyncpg.Record],
    keyword_rows: Sequence[asyncpg.Record],
    rank_constant: int = 60,
) -> list[tuple[asyncpg.Record, float]]:
    fused: dict[str, tuple[asyncpg.Record, float]] = {}
    for rows in (vector_rows, keyword_rows):
        for rank, row in enumerate(rows, start=1):
            previous = fused.get(row["chunk_id"])
            score = (previous[1] if previous else 0.0) + 1 / (rank_constant + rank)
            fused[row["chunk_id"]] = (previous[0] if previous else row, score)
    return sorted(fused.values(), key=lambda item: (-item[1], item[0]["chunk_id"]))


def _markdown_body(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        raise PCMValidationError("Stored Knowledge Markdown has no front matter.")
    _, separator, body = markdown[4:].partition("---\n")
    if not separator:
        raise PCMValidationError("Stored Knowledge Markdown front matter is incomplete.")
    return body.strip()


def _previous(document: KnowledgeDocument | None) -> KnowledgeDocument:
    if document is None:
        raise PCMValidationError("Existing Knowledge is required.")
    return document
