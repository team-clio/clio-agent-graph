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


async def _pcm_with_repository_knowledge(
    monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...]
) -> tuple[object, list[dict[str, object]]]:
    pcm = InMemoryPCM()
    commit = await pcm.apply_knowledge_changes(
        project_id="PROJECT-1",
        change_set=KnowledgeChangeSet(
            source_event_id="EVENT-1",
            base_pcm_revision=0,
            changes=tuple(
                KnowledgeChange(
                    operation="create",
                    logical_key=f"loader-{index}",
                    knowledge_type="component",
                    title=f"Loader {index}",
                    body_markdown="Loads ids and tokens.",
                    sources=(
                        SourceReference(
                            source_type="repository",
                            source_id="7",
                            source_revision="b" * 40,
                            locator={"path": path, "start_line": 1, "end_line": 120},
                        ),
                    ),
                    reason="The source defines the loader.",
                )
                for index, path in enumerate(paths)
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
    evidence = [
        {
            "knowledge_id": knowledge_id,
            "knowledge_revision": 1,
            "sources": [{"locator": {"path": path, "start_line": 1, "end_line": 120}}],
        }
        for knowledge_id, path in zip(commit.created_knowledge_ids, paths, strict=True)
    ]
    return await pcm.resolve_snapshot("PROJECT-1"), evidence


@pytest.mark.asyncio
async def test_quality_gate_restores_knowledge_id_from_supplied_document_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, evidence = await _pcm_with_repository_knowledge(monkeypatch, ("k6/lib/data.js",))

    result = await issue_analysis.quality_gate(
        {
            "project_id": "PROJECT-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
            "document_evidence": evidence,
            "issue_analysis": {
                "facts": ["Loader reads tokens."],
                "citations": [{"source_type": "knowledge", "location": "k6/lib/data.js:10-20"}],
            },
            "resolution_plan": {},
        }
    )

    assert result["quality_result"] == {"status": "passed", "reasons": [], "warnings": []}
    assert result["issue_analysis"]["citations"][0]["knowledge_id"] == evidence[0]["knowledge_id"]


@pytest.mark.asyncio
async def test_quality_gate_drops_ambiguous_knowledge_citation_with_its_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, evidence = await _pcm_with_repository_knowledge(
        monkeypatch, ("k6/lib/data.js", "k6/lib/data.js")
    )

    result = await issue_analysis.quality_gate(
        {
            "project_id": "PROJECT-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
            "document_evidence": evidence,
            "issue_analysis": {
                "facts": [],
                "citations": [{"source_type": "knowledge", "location": "k6/lib/data.js:10-20"}],
            },
            "resolution_plan": {},
        }
    )

    assert result["issue_analysis"]["citations"] == []
    assert result["quality_result"]["warnings"] == [
        "Dropped a knowledge citation without knowledge_id: "
        "location=k6/lib/data.js:10-20, fields=-."
    ]
