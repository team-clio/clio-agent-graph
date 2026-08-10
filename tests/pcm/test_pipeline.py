from collections.abc import Mapping, Sequence

import pytest

from clio_agent_graph.context.pcm import (
    DocumentKnowledgePipeline,
    IngestDocumentCommand,
    InMemoryPCM,
)
from clio_agent_graph.context.pcm.errors import KnowledgeModelOutputError
from clio_agent_graph.context.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    KnowledgeCandidate,
    KnowledgeChangeDraft,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    TopicExtractionResult,
)


class ScriptedKnowledgeModel:
    def __init__(self, *, invalid_change_once: bool = False) -> None:
        self.invalid_change_once = invalid_change_once
        self.topic_attempts = 0
        self.change_attempts = 0
        self.received_validation_errors: list[tuple[str, ...]] = []

    async def extract_topics(
        self,
        *,
        document_title: str,
        source_units: Sequence[DocumentSourceUnit],
        validation_errors: Sequence[str] = (),
    ) -> TopicExtractionResult:
        self.topic_attempts += 1
        assert document_title
        return TopicExtractionResult(
            topics=(
                ExtractedTopic(
                    topic_key="saved-search-permissions",
                    title="Saved Search permissions",
                    knowledge_type="domain_rule",
                    summary="Who can modify a saved search.",
                    source_unit_ids=(source_units[0].source_unit_id,),
                    suggested_search_queries=("saved search owner permissions",),
                ),
            )
        )

    async def generate_change_set(
        self,
        *,
        source_event_id: str,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[DocumentSourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
        validation_errors: Sequence[str] = (),
    ) -> KnowledgeChangeDraftSet:
        self.change_attempts += 1
        self.received_validation_errors.append(tuple(validation_errors))
        candidate = next(iter(candidates[topics[0].topic_key]), None)
        source_unit_id = source_units[0].source_unit_id
        if self.invalid_change_once and self.change_attempts == 1:
            source_unit_id = "unknown-source-unit"
        if candidate:
            change = KnowledgeChangeDraft(
                operation="update",
                target_knowledge_id=candidate.knowledge_id,
                knowledge_type="domain_rule",
                title="Saved Search permissions",
                body_markdown=source_units[0].content,
                source_unit_ids=(source_unit_id,),
                reason="The new document revision updates the permission rule.",
            )
        else:
            change = KnowledgeChangeDraft(
                operation="create",
                logical_key="saved-search-permissions",
                knowledge_type="domain_rule",
                title="Saved Search permissions",
                body_markdown=source_units[0].content,
                source_unit_ids=(source_unit_id,),
                reason="The document defines a durable permission rule.",
            )
        return KnowledgeChangeDraftSet(
            source_event_id=source_event_id,
            base_pcm_revision=snapshot.pcm_revision,
            changes=(change,),
        )


def ingest_command(*, event_id: str, revision: str, rule: str) -> IngestDocumentCommand:
    return IngestDocumentCommand(
        event_id=event_id,
        project_id="PROJECT-1",
        document_id="requirements",
        revision=revision,
        title="Saved Search Requirements",
        markdown=f"# Permissions\n\n{rule}",
    )


@pytest.mark.asyncio
async def test_ingests_markdown_as_searchable_knowledge() -> None:
    pcm = InMemoryPCM()
    pipeline = DocumentKnowledgePipeline(
        reader=pcm,
        writer=pcm,
        knowledge_model=ScriptedKnowledgeModel(),
    )

    result = await pipeline.ingest(
        ingest_command(
            event_id="EVENT-1",
            revision="1",
            rule="Only owners can edit a saved search.",
        )
    )
    snapshot = await pcm.resolve_snapshot("PROJECT-1")
    document = await pcm.read_knowledge(
        snapshot=snapshot,
        knowledge_id=result.created_knowledge_ids[0],
    )

    assert result.pcm_revision == 1
    assert document.body_markdown == "Only owners can edit a saved search."
    assert document.sources[0].source_id == "requirements"
    assert document.sources[0].locator == {"heading_path": ["Permissions"]}


@pytest.mark.asyncio
async def test_new_document_revision_updates_retrieved_knowledge() -> None:
    pcm = InMemoryPCM()
    pipeline = DocumentKnowledgePipeline(
        reader=pcm,
        writer=pcm,
        knowledge_model=ScriptedKnowledgeModel(),
    )
    first = await pipeline.ingest(
        ingest_command(event_id="EVENT-1", revision="1", rule="Only owners can edit.")
    )

    second = await pipeline.ingest(
        ingest_command(
            event_id="EVENT-2",
            revision="2",
            rule="Owners and administrators can edit.",
        )
    )

    assert second.pcm_revision == 2
    assert second.updated_knowledge_ids == first.created_knowledge_ids


@pytest.mark.asyncio
async def test_invalid_llm_change_is_retried_with_validation_error() -> None:
    pcm = InMemoryPCM()
    model = ScriptedKnowledgeModel(invalid_change_once=True)
    pipeline = DocumentKnowledgePipeline(reader=pcm, writer=pcm, knowledge_model=model)

    result = await pipeline.ingest(
        ingest_command(event_id="EVENT-1", revision="1", rule="Only owners can edit.")
    )

    assert result.pcm_revision == 1
    assert model.change_attempts == 2
    assert model.received_validation_errors[0] == ()
    assert "unknown Source Units" in model.received_validation_errors[1][0]


@pytest.mark.asyncio
async def test_repeated_invalid_llm_change_does_not_commit() -> None:
    class AlwaysInvalidModel(ScriptedKnowledgeModel):
        async def generate_change_set(self, **kwargs: object) -> KnowledgeChangeDraftSet:
            result = await super().generate_change_set(**kwargs)  # type: ignore[arg-type]
            change = result.changes[0].model_copy(
                update={"source_unit_ids": ("unknown-source-unit",)}
            )
            return result.model_copy(update={"changes": (change,)})

    pcm = InMemoryPCM()
    pipeline = DocumentKnowledgePipeline(
        reader=pcm,
        writer=pcm,
        knowledge_model=AlwaysInvalidModel(),
    )

    with pytest.raises(KnowledgeModelOutputError, match="failed validation"):
        await pipeline.ingest(
            ingest_command(event_id="EVENT-1", revision="1", rule="Only owners can edit.")
        )

    assert (await pcm.resolve_snapshot("PROJECT-1")).pcm_revision == 0


@pytest.mark.asyncio
async def test_replaying_document_event_does_not_create_new_revision() -> None:
    pcm = InMemoryPCM()
    model = ScriptedKnowledgeModel()
    pipeline = DocumentKnowledgePipeline(
        reader=pcm,
        writer=pcm,
        knowledge_model=model,
    )
    command = ingest_command(event_id="EVENT-1", revision="1", rule="Only owners can edit.")

    first = await pipeline.ingest(command)
    replay = await pipeline.ingest(command)

    assert replay.commit_id == first.commit_id
    assert replay.idempotent_replay is True
    assert (await pcm.resolve_snapshot("PROJECT-1")).pcm_revision == 1
    assert model.topic_attempts == 1
    assert model.change_attempts == 1
