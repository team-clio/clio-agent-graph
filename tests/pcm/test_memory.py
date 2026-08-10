import pytest

from clio_agent_graph.context.pcm import (
    InMemoryPCM,
    KnowledgeChange,
    KnowledgeChangeSet,
    KnowledgeSearchRequest,
    SourceReference,
)
from clio_agent_graph.context.pcm.errors import (
    KnowledgeNotFoundError,
    PCMRevisionConflict,
    PCMValidationError,
)


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


async def create_knowledge(pcm: InMemoryPCM, *, project_id: str = "PROJECT-1") -> str:
    result = await pcm.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=f"EVENT-{project_id}-1",
            base_pcm_revision=0,
            changes=(create_change(),),
        ),
    )
    return result.created_knowledge_ids[0]


@pytest.mark.asyncio
async def test_commits_and_reads_new_knowledge() -> None:
    pcm = InMemoryPCM()

    knowledge_id = await create_knowledge(pcm)
    snapshot = await pcm.resolve_snapshot("PROJECT-1")
    document = await pcm.read_knowledge(snapshot=snapshot, knowledge_id=knowledge_id)

    assert snapshot.pcm_revision == 1
    assert document.knowledge_revision == 1
    assert document.valid_from_pcm_revision == 1
    assert document.sources == (document_source(),)


@pytest.mark.asyncio
async def test_old_snapshot_keeps_previous_revision_after_update() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await create_knowledge(pcm)
    old_snapshot = await pcm.resolve_snapshot("PROJECT-1")

    result = await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-PROJECT-1-2",
            base_pcm_revision=1,
            changes=(
                KnowledgeChange(
                    operation="update",
                    target_knowledge_id=knowledge_id,
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown="Owners, administrators, and delegated editors can edit.",
                    sources=(document_source("2"),),
                    reason="Revision 2 adds delegated editors.",
                ),
            ),
        ),
    )
    new_snapshot = await pcm.resolve_snapshot("PROJECT-1")

    old_document = await pcm.read_knowledge(snapshot=old_snapshot, knowledge_id=knowledge_id)
    new_document = await pcm.read_knowledge(snapshot=new_snapshot, knowledge_id=knowledge_id)

    assert result.pcm_revision == 2
    assert old_document.knowledge_revision == 1
    assert "project administrator" in old_document.body_markdown
    assert new_document.knowledge_revision == 2
    assert "delegated editors" in new_document.body_markdown


@pytest.mark.asyncio
async def test_replaying_event_returns_original_commit_without_new_revision() -> None:
    pcm = InMemoryPCM()
    change_set = KnowledgeChangeSet(
        source_event_id="EVENT-1",
        base_pcm_revision=0,
        changes=(create_change(),),
    )

    first = await pcm.apply_knowledge_changes(project_id="PROJECT-1", change_set=change_set)
    replay = await pcm.apply_knowledge_changes(project_id="PROJECT-1", change_set=change_set)
    snapshot = await pcm.resolve_snapshot("PROJECT-1")

    assert replay.commit_id == first.commit_id
    assert replay.idempotent_replay is True
    assert snapshot.pcm_revision == 1


@pytest.mark.asyncio
async def test_rejects_stale_change_set() -> None:
    pcm = InMemoryPCM()
    await create_knowledge(pcm)

    with pytest.raises(PCMRevisionConflict) as error:
        await pcm.apply_knowledge_changes(
            project_id="PROJECT-1",
            change_set=KnowledgeChangeSet(
                source_event_id="EVENT-STALE",
                base_pcm_revision=0,
                changes=(
                    KnowledgeChange(
                        operation="create",
                        logical_key="another-topic",
                        knowledge_type="architecture",
                        title="Another topic",
                        body_markdown="A new architectural fact.",
                        sources=(document_source(),),
                        reason="A source describes another topic.",
                    ),
                ),
            ),
        )

    assert error.value.expected == 0
    assert error.value.actual == 1


@pytest.mark.asyncio
async def test_search_is_scoped_to_project_and_snapshot() -> None:
    pcm = InMemoryPCM()
    project_one_id = await create_knowledge(pcm, project_id="PROJECT-1")
    await create_knowledge(pcm, project_id="PROJECT-2")
    snapshot = await pcm.resolve_snapshot("PROJECT-1")

    page = await pcm.search_knowledge(
        snapshot=snapshot,
        request=KnowledgeSearchRequest(query="saved search owner"),
    )

    assert [result.knowledge_id for result in page.results] == [project_one_id]
    assert page.project_id == "PROJECT-1"
    assert page.pcm_revision == 1


@pytest.mark.asyncio
async def test_rejects_search_query_without_searchable_text() -> None:
    pcm = InMemoryPCM()
    snapshot = await pcm.resolve_snapshot("PROJECT-1")

    with pytest.raises(PCMValidationError, match="searchable text"):
        await pcm.search_knowledge(
            snapshot=snapshot,
            request=KnowledgeSearchRequest(query="   "),
        )


@pytest.mark.asyncio
async def test_trace_sources_returns_revision_provenance() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await create_knowledge(pcm)
    snapshot = await pcm.resolve_snapshot("PROJECT-1")

    sources = await pcm.trace_knowledge_sources(
        snapshot=snapshot,
        knowledge_id=knowledge_id,
    )

    assert sources[0].source_id == "requirements"
    assert sources[0].source_revision == "1"
    assert sources[0].locator == {"heading_path": ["Saved Search", "Permissions"]}


@pytest.mark.asyncio
async def test_no_change_event_does_not_advance_pcm_revision() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await create_knowledge(pcm)

    result = await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-NO-CHANGE",
            base_pcm_revision=1,
            changes=(
                KnowledgeChange(
                    operation="no_change",
                    target_knowledge_id=knowledge_id,
                    reason="The source states the existing rule without modification.",
                ),
            ),
        ),
    )

    assert result.pcm_revision == 1
    assert result.unchanged_knowledge_ids == (knowledge_id,)


@pytest.mark.asyncio
async def test_tombstone_hides_knowledge_only_from_new_snapshots() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await create_knowledge(pcm)
    old_snapshot = await pcm.resolve_snapshot("PROJECT-1")

    await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-DELETE",
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
    new_snapshot = await pcm.resolve_snapshot("PROJECT-1")

    assert (await pcm.read_knowledge(snapshot=old_snapshot, knowledge_id=knowledge_id)).title
    with pytest.raises(KnowledgeNotFoundError):
        await pcm.read_knowledge(snapshot=new_snapshot, knowledge_id=knowledge_id)


@pytest.mark.asyncio
async def test_rejects_duplicate_logical_key_without_advancing_revision() -> None:
    pcm = InMemoryPCM()
    await create_knowledge(pcm)

    with pytest.raises(PCMValidationError, match="already exists"):
        await pcm.apply_knowledge_changes(
            project_id="PROJECT-1",
            change_set=KnowledgeChangeSet(
                source_event_id="EVENT-DUPLICATE",
                base_pcm_revision=1,
                changes=(create_change(title="Duplicate"),),
            ),
        )

    assert (await pcm.resolve_snapshot("PROJECT-1")).pcm_revision == 1


@pytest.mark.asyncio
async def test_rejects_duplicate_logical_keys_inside_atomic_change_set() -> None:
    pcm = InMemoryPCM()

    with pytest.raises(PCMValidationError, match="already exists"):
        await pcm.apply_knowledge_changes(
            project_id="PROJECT-1",
            change_set=KnowledgeChangeSet(
                source_event_id="EVENT-DUPLICATE-BATCH",
                base_pcm_revision=0,
                changes=(create_change(), create_change(title="Duplicate in batch")),
            ),
        )

    assert (await pcm.resolve_snapshot("PROJECT-1")).pcm_revision == 0
