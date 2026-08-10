import pytest

from clio_agent_graph.context.application import ApplicationServices
from clio_agent_graph.context.pcm import (
    DocumentKnowledgePipeline,
    InMemoryPCM,
    KnowledgeChange,
    KnowledgeChangeSet,
    SourceReference,
)
from clio_agent_graph.workflows.orchestration.nodes import issue_analysis


@pytest.mark.asyncio
async def test_quality_gate_rejects_mismatched_knowledge_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm = InMemoryPCM()
    commit = await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-1",
            base_pcm_revision=0,
            changes=(
                KnowledgeChange(
                    operation="create",
                    logical_key="permissions",
                    knowledge_type="domain_rule",
                    title="Permissions",
                    body_markdown="Only owners can edit.",
                    sources=(
                        SourceReference(
                            source_type="document",
                            source_id="requirements",
                            source_revision="1",
                        ),
                    ),
                    reason="The source defines permissions.",
                ),
            ),
        ),
    )
    services = ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=object(),  # type: ignore[arg-type]
        ),
    )
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    snapshot = await pcm.resolve_snapshot("PROJECT-1")

    result = await issue_analysis.quality_gate(
        {
            "project_id": "PROJECT-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
            "issue_analysis": {
                "facts": ["Only owners can edit."],
                "citations": [
                    {
                        "source_type": "knowledge",
                        "knowledge_id": commit.created_knowledge_ids[0],
                        "knowledge_revision": 99,
                    }
                ],
            },
            "resolution_plan": {},
        }
    )

    assert result["quality_result"]["status"] == "needs_review"
    assert "revision does not match" in result["quality_result"]["reasons"][0]


@pytest.mark.asyncio
async def test_quality_gate_rejects_repository_commit_outside_snapshot() -> None:
    result = await issue_analysis.quality_gate(
        {
            "project_id": "PROJECT-1",
            "context_snapshot": {
                "project_id": "PROJECT-1",
                "pcm_revision": 0,
                "knowledge_index_revision": 0,
                "repository_revisions": {"backend": "a" * 40},
            },
            "issue_analysis": {
                "facts": ["The backend allows administrators."],
                "citations": [
                    {
                        "source_type": "repository",
                        "repository_id": "backend",
                        "commit": "b" * 40,
                    }
                ],
            },
            "resolution_plan": {},
        }
    )

    assert result["quality_result"]["status"] == "needs_review"
    assert "commit does not match" in result["quality_result"]["reasons"][0]
