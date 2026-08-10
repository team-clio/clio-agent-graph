import pytest

from clio_agent_graph.context.pcm import (
    InMemoryPCM,
    KnowledgeChange,
    KnowledgeChangeSet,
    SourceReference,
)
from clio_agent_graph.context.pcm.errors import KnowledgeNotFoundError
from clio_agent_graph.context.tools.pcm import PCMToolContext, PCMToolFactory


def source(revision: str) -> SourceReference:
    return SourceReference(
        source_type="document",
        source_id="requirements",
        source_revision=revision,
        locator={"heading_path": ["Permissions"]},
    )


async def create_knowledge(pcm: InMemoryPCM, project_id: str) -> str:
    result = await pcm.apply_knowledge_changes(
        project_id=project_id,
        change_set=KnowledgeChangeSet(
            source_event_id=f"EVENT-{project_id}-1",
            base_pcm_revision=0,
            changes=(
                KnowledgeChange(
                    operation="create",
                    logical_key="saved-search-permissions",
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown="Only owners can edit a saved search.",
                    sources=(source("1"),),
                    reason="The source defines a durable permission rule.",
                ),
            ),
        ),
    )
    return result.created_knowledge_ids[0]


@pytest.mark.asyncio
async def test_tools_hide_project_and_snapshot_from_agent_input() -> None:
    pcm = InMemoryPCM()
    await create_knowledge(pcm, "PROJECT-1")
    snapshot = await pcm.resolve_snapshot("PROJECT-1")
    tools = PCMToolFactory(pcm).create_tools(
        PCMToolContext(project_id="PROJECT-1", request_id="REQ-1", snapshot=snapshot)
    )

    assert [tool.name for tool in tools] == [
        "search_project_knowledge",
        "read_project_knowledge",
        "trace_knowledge_sources",
    ]
    for pcm_tool in tools:
        properties = pcm_tool.args_schema.model_json_schema()["properties"]
        assert "project_id" not in properties
        assert "snapshot" not in properties
        assert "pcm_revision" not in properties


@pytest.mark.asyncio
async def test_tools_keep_read_consistency_at_bound_snapshot() -> None:
    pcm = InMemoryPCM()
    knowledge_id = await create_knowledge(pcm, "PROJECT-1")
    old_snapshot = await pcm.resolve_snapshot("PROJECT-1")
    tools = PCMToolFactory(pcm).create_tools(
        PCMToolContext(project_id="PROJECT-1", request_id="REQ-1", snapshot=old_snapshot)
    )

    await pcm.apply_knowledge_changes(
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
                    body_markdown="Owners and administrators can edit a saved search.",
                    sources=(source("2"),),
                    reason="Revision 2 expands edit permissions.",
                ),
            ),
        ),
    )

    search = await tools[0].ainvoke({"query": "saved search owners"})
    document = await tools[1].ainvoke({"knowledge_id": knowledge_id})
    provenance = await tools[2].ainvoke({"knowledge_id": knowledge_id})

    assert search["pcm_revision"] == 1
    assert search["results"][0]["knowledge_revision"] == 1
    assert document["knowledge_revision"] == 1
    assert document["body_markdown"] == "Only owners can edit a saved search."
    assert provenance["pcm_revision"] == 1
    assert provenance["sources"][0]["source_revision"] == "1"


@pytest.mark.asyncio
async def test_bound_tools_cannot_read_another_project() -> None:
    pcm = InMemoryPCM()
    await create_knowledge(pcm, "PROJECT-1")
    foreign_id = await create_knowledge(pcm, "PROJECT-2")
    snapshot = await pcm.resolve_snapshot("PROJECT-1")
    read_tool = PCMToolFactory(pcm).create_tools(
        PCMToolContext(project_id="PROJECT-1", request_id="REQ-1", snapshot=snapshot)
    )[1]

    with pytest.raises(KnowledgeNotFoundError):
        await read_tool.ainvoke({"knowledge_id": foreign_id})
