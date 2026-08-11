import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from clio_agent_graph.context.pcm.models import (
    KnowledgeChange,
    KnowledgeChangeSet,
    KnowledgeSearchRequest,
    SourceReference,
)
from clio_agent_graph.context.pcm.postgres import PostgresPCM
from clio_agent_graph.context.pcm.storage import MarkdownStore

pytestmark = pytest.mark.postgres


class FakeEmbeddingProvider:
    model_id = "fake-test-embedding"
    dimensions = 384

    async def embed_documents(self, texts: object) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, *([0.0] * 383)]


class FailingEmbeddingProvider:
    model_id = "failing-test-embedding"
    dimensions = 384

    async def embed_documents(self, texts: object) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")

    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")


def postgres_url() -> str:
    url = os.getenv("CLIO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set CLIO_TEST_POSTGRES_URL to run PostgreSQL integration tests.")
    return url


async def cleanup_project(project_id: str) -> None:
    connection = await asyncpg.connect(postgres_url())
    try:
        async with connection.transaction():
            await connection.execute(
                """
                DELETE FROM pcm_chunk_embeddings
                WHERE chunk_id IN (
                    SELECT chunk_id FROM pcm_knowledge_chunks WHERE project_id = $1
                )
                """,
                project_id,
            )
            for table in (
                "pcm_knowledge_chunks",
                "pcm_knowledge_revisions",
                "pcm_knowledge",
                "pcm_source_events",
                "pcm_document_revisions",
                "pcm_index_generations",
                "pcm_commits",
                "pcm_projects",
            ):
                await connection.execute(f"DELETE FROM {table} WHERE project_id = $1", project_id)
    finally:
        await connection.close()


async def reset_project_index(project_id: str) -> None:
    connection = await asyncpg.connect(postgres_url())
    try:
        async with connection.transaction():
            await connection.execute(
                """
                DELETE FROM pcm_chunk_embeddings
                WHERE chunk_id IN (
                    SELECT chunk_id FROM pcm_knowledge_chunks WHERE project_id = $1
                )
                """,
                project_id,
            )
            await connection.execute(
                "DELETE FROM pcm_knowledge_chunks WHERE project_id = $1",
                project_id,
            )
            await connection.execute(
                "DELETE FROM pcm_index_generations WHERE project_id = $1",
                project_id,
            )
            await connection.execute(
                """
                UPDATE pcm_projects
                SET knowledge_index_revision = 0, active_index_generation = NULL
                WHERE project_id = $1
                """,
                project_id,
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_persists_snapshot_markdown_and_event_across_adapter_restart(
    tmp_path: Path,
) -> None:
    project_id = f"TEST-{uuid4()}"
    source_event_id = f"EVENT-{uuid4()}"
    first = PostgresPCM(
        database_url=postgres_url(),
        markdown_store=MarkdownStore(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    )
    result = await first.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=source_event_id,
            base_pcm_revision=0,
            changes=(
                KnowledgeChange(
                    operation="create",
                    logical_key="saved-search-permissions",
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown="Only owners can edit a saved search.",
                    sources=(
                        SourceReference(
                            source_type="document",
                            source_id="requirements",
                            source_revision="1",
                            locator={"heading_path": ["Permissions"]},
                        ),
                    ),
                    reason="The document defines edit permissions.",
                ),
            ),
        ),
    )
    await first.close()

    restored = PostgresPCM(
        database_url=postgres_url(),
        markdown_store=MarkdownStore(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    )
    snapshot = await restored.resolve_snapshot(project_id)
    document = await restored.read_knowledge(
        snapshot=snapshot,
        knowledge_id=result.created_knowledge_ids[0],
    )
    replay = await restored.find_commit_by_event(
        project_id=project_id,
        source_event_id=source_event_id,
    )
    search = await restored.search_knowledge(
        snapshot=snapshot,
        request=KnowledgeSearchRequest(query="saved search owner permission"),
    )

    assert snapshot.pcm_revision == 1
    assert snapshot.knowledge_index_revision == 1
    assert document.body_markdown == "Only owners can edit a saved search."
    assert document.sources[0].source_revision == "1"
    assert replay is not None and replay.idempotent_replay is True
    assert search.vector_search_used is True
    assert search.keyword_search_used is True
    assert search.vector_index_stale is False
    assert search.results[0].knowledge_id == document.knowledge_id
    assert len(list(tmp_path.rglob("*.md"))) == 1

    old_snapshot = snapshot
    update = await restored.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=f"EVENT-{uuid4()}",
            base_pcm_revision=1,
            changes=(
                KnowledgeChange(
                    operation="update",
                    target_knowledge_id=document.knowledge_id,
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown="Owners and administrators can edit a saved search.",
                    sources=(
                        SourceReference(
                            source_type="document",
                            source_id="requirements",
                            source_revision="2",
                            locator={"heading_path": ["Permissions"]},
                        ),
                    ),
                    reason="Revision 2 expands edit permissions.",
                ),
            ),
        ),
    )
    new_snapshot = await restored.resolve_snapshot(project_id)
    old_document = await restored.read_knowledge(
        snapshot=old_snapshot,
        knowledge_id=document.knowledge_id,
    )
    new_document = await restored.read_knowledge(
        snapshot=new_snapshot,
        knowledge_id=document.knowledge_id,
    )
    new_search = await restored.search_knowledge(
        snapshot=new_snapshot,
        request=KnowledgeSearchRequest(query="administrator edit permissions"),
    )

    assert update.pcm_revision == 2
    assert old_document.body_markdown == "Only owners can edit a saved search."
    assert new_document.body_markdown == "Owners and administrators can edit a saved search."
    assert new_snapshot.knowledge_index_revision == 2
    assert new_search.results[0].knowledge_revision == 2
    assert len(list(tmp_path.rglob("*.md"))) == 2
    await restored.close()

    await reset_project_index(project_id)
    backfilled = PostgresPCM(
        database_url=postgres_url(),
        markdown_store=MarkdownStore(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
    )
    backfilled_snapshot = await backfilled.resolve_snapshot(project_id)
    backfilled_search = await backfilled.search_knowledge(
        snapshot=backfilled_snapshot,
        request=KnowledgeSearchRequest(query="administrators edit permissions"),
    )

    assert backfilled_snapshot.knowledge_index_revision == 2
    assert backfilled_search.results[0].knowledge_revision == 2
    await backfilled.close()

    degraded = PostgresPCM(
        database_url=postgres_url(),
        markdown_store=MarkdownStore(tmp_path),
        embedding_provider=FailingEmbeddingProvider(),
    )
    degraded_snapshot = await degraded.resolve_snapshot(project_id)
    keyword_only = await degraded.search_knowledge(
        snapshot=degraded_snapshot,
        request=KnowledgeSearchRequest(query="administrators edit saved search"),
    )

    assert keyword_only.vector_search_used is False
    assert keyword_only.keyword_search_used is True
    assert keyword_only.results[0].knowledge_id == document.knowledge_id

    degraded_commit = await degraded.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=f"EVENT-{uuid4()}",
            base_pcm_revision=2,
            changes=(
                KnowledgeChange(
                    operation="update",
                    target_knowledge_id=document.knowledge_id,
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown="Delegated editors can now edit a saved search.",
                    sources=(
                        SourceReference(
                            source_type="document",
                            source_id="requirements",
                            source_revision="3",
                            locator={"heading_path": ["Permissions"]},
                        ),
                    ),
                    reason="Revision 3 adds delegated editors.",
                ),
            ),
        ),
    )
    stale_snapshot = await degraded.resolve_snapshot(project_id)
    stale_search = await degraded.search_knowledge(
        snapshot=stale_snapshot,
        request=KnowledgeSearchRequest(query="delegated editors"),
    )

    assert degraded_commit.pcm_revision == 3
    assert stale_snapshot.knowledge_index_revision == 2
    assert stale_search.vector_index_stale is True
    assert stale_search.vector_search_used is False
    assert stale_search.results[0].knowledge_revision == 3
    await degraded.close()
    await cleanup_project(project_id)
