"""PCM inspect API의 읽기 전용 HTTP 계약을 검증한다."""

import httpx
import pytest

from clio_agent_graph.context.pcm import (
    InMemoryPCM,
    KnowledgeChange,
    KnowledgeChangeSet,
    SourceReference,
)
from clio_agent_graph.context.pcm.inspect_api import create_app


def document_source(revision: str = "1") -> SourceReference:
    return SourceReference(
        source_type="document",
        source_id="requirements",
        source_revision=revision,
        locator={"heading_path": ["Saved Search", "Permissions"]},
        content_hash=f"sha256:{revision}",
    )


def create_change(*, title: str = "Saved Search permissions") -> KnowledgeChange:
    return KnowledgeChange(
        operation="create",
        logical_key="saved-search-permissions",
        knowledge_type="domain_rule",
        title=title,
        body_markdown="Only the owner or a project administrator can edit a saved search.",
        sources=(document_source(),),
        reason="The requirements define edit permissions.",
    )


async def seed_knowledge(pcm: InMemoryPCM, *, project_id: str = "PROJECT-1") -> str:
    result = await pcm.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=f"EVENT-{project_id}-1",
            base_pcm_revision=0,
            changes=(create_change(),),
        ),
    )
    return result.created_knowledge_ids[0]


def make_client(pcm: InMemoryPCM) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(pcm)),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_snapshot_endpoint_reports_active_pcm_revision() -> None:
    pcm = InMemoryPCM()
    await seed_knowledge(pcm)

    async with make_client(pcm) as client:
        response = await client.get("/pcm/projects/PROJECT-1/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "PROJECT-1"
    assert body["pcm_revision"] == 1
    assert body["knowledge_index_revision"] == 1


@pytest.mark.asyncio
async def test_snapshot_of_unknown_project_starts_at_revision_zero() -> None:
    pcm = InMemoryPCM()

    async with make_client(pcm) as client:
        response = await client.get("/pcm/projects/EMPTY/snapshot")

    assert response.status_code == 200
    assert response.json()["pcm_revision"] == 0


@pytest.mark.asyncio
async def test_list_knowledge_returns_snapshot_valid_documents() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await seed_knowledge(pcm)

    async with make_client(pcm) as client:
        response = await client.get("/pcm/projects/PROJECT-1/knowledge")

    assert response.status_code == 200
    documents = response.json()
    assert len(documents) == 1
    assert documents[0]["knowledge_id"] == knowledge_id
    assert documents[0]["logical_key"] == "saved-search-permissions"
    assert documents[0]["knowledge_type"] == "domain_rule"
    assert documents[0]["title"] == "Saved Search permissions"
    assert documents[0]["knowledge_revision"] == 1
    assert documents[0]["sources"][0]["source_id"] == "requirements"
    assert documents[0]["is_tombstone"] is False


@pytest.mark.asyncio
async def test_list_knowledge_is_scoped_to_project() -> None:
    pcm = InMemoryPCM()
    await seed_knowledge(pcm, project_id="PROJECT-1")
    await seed_knowledge(pcm, project_id="PROJECT-2")

    async with make_client(pcm) as client:
        response = await client.get("/pcm/projects/PROJECT-1/knowledge")

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_read_knowledge_returns_full_document() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await seed_knowledge(pcm)

    async with make_client(pcm) as client:
        response = await client.get(f"/pcm/projects/PROJECT-1/knowledge/{knowledge_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["knowledge_id"] == knowledge_id
    assert body["body_markdown"].startswith("Only the owner")
    assert body["valid_from_pcm_revision"] == 1
    assert body["valid_until_pcm_revision"] is None


@pytest.mark.asyncio
async def test_read_missing_knowledge_returns_404() -> None:
    pcm = InMemoryPCM()
    await seed_knowledge(pcm)

    async with make_client(pcm) as client:
        response = await client.get("/pcm/projects/PROJECT-1/knowledge/kn_unknown")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_tombstoned_knowledge_is_hidden_from_list_and_detail() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await seed_knowledge(pcm)
    await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-PROJECT-1-DELETE",
            base_pcm_revision=1,
            changes=(
                KnowledgeChange(
                    operation="tombstone",
                    target_knowledge_id=knowledge_id,
                    reason="No active source supports the knowledge.",
                ),
            ),
        ),
    )

    async with make_client(pcm) as client:
        list_response = await client.get("/pcm/projects/PROJECT-1/knowledge")
        detail_response = await client.get(f"/pcm/projects/PROJECT-1/knowledge/{knowledge_id}")

    assert list_response.status_code == 200
    assert list_response.json() == []
    assert detail_response.status_code == 404
