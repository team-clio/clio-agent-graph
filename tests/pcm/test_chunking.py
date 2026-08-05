from clio_agent_graph.services.pcm.chunking import MarkdownKnowledgeChunker
from clio_agent_graph.services.pcm.models import KnowledgeDocument, SourceReference


def knowledge(body: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        project_id="PROJECT-1",
        knowledge_id="KNOWLEDGE-1",
        logical_key="saved-search",
        knowledge_type="domain_rule",
        title="Saved Search",
        body_markdown=body,
        knowledge_revision=1,
        valid_from_pcm_revision=1,
        sources=(
            SourceReference(
                source_type="document",
                source_id="requirements",
                source_revision="1",
            ),
        ),
    )


def test_chunks_knowledge_by_heading_and_preserves_context() -> None:
    chunks = MarkdownKnowledgeChunker().chunk(
        knowledge(
            """
# Execution

Saved searches execute asynchronously.

## Permissions

Only owners can edit.
"""
        )
    )

    assert [chunk.heading_path for chunk in chunks] == [
        ("Execution",),
        ("Execution", "Permissions"),
    ]
    assert chunks[1].content.startswith("Saved Search > Execution > Permissions")


def test_chunk_identity_is_deterministic() -> None:
    chunker = MarkdownKnowledgeChunker()
    document = knowledge("# Permissions\n\nOnly owners can edit.")

    assert chunker.chunk(document) == chunker.chunk(document)


def test_splits_long_sections_with_configured_limit() -> None:
    chunks = MarkdownKnowledgeChunker(max_characters=256).chunk(knowledge("A" * 600))

    assert len(chunks) == 3
    assert all(len(chunk.content) <= 256 + len("Saved Search\n\n") for chunk in chunks)
