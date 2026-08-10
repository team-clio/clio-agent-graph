import json
from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from clio_agent_graph.context.application import ApplicationServices
from clio_agent_graph.context.pcm import DocumentKnowledgePipeline, InMemoryPCM
from clio_agent_graph.context.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    KnowledgeCandidate,
    KnowledgeChangeDraft,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    TopicExtractionResult,
)
from clio_agent_graph.graph import graph
from clio_agent_graph.runtime.llm import ToolCallingAgent
from clio_agent_graph.workflows.orchestration.nodes import issue_analysis, memory_sync


@pytest.fixture(autouse=True)
def fake_llm_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep graph-routing tests independent of a live LLM provider."""

    def invoke(self: ToolCallingAgent, prompt: str) -> dict[str, object]:
        payload = json.loads(prompt.split("\n", 1)[1])
        if self.name == "report_matcher":
            candidates = payload["candidates"]
            if not candidates:
                return {
                    "action": "create_new",
                    "issue_id": None,
                    "confidence": 1.0,
                    "reason": "No matching issue was found.",
                }
            candidate = candidates[0]
            if candidate.get("requires_review"):
                return {
                    "action": "needs_review",
                    "issue_id": candidate["issue_id"],
                    "confidence": candidate["confidence"],
                    "reason": "The candidate requires human review.",
                }
            return {
                "action": "link_existing",
                "issue_id": candidate["issue_id"],
                "confidence": candidate["confidence"],
                "reason": "The candidate is a strong match.",
            }
        if self.name == "issue_analyst":
            evidence = payload["evidence"]
            return {
                "issue_id": payload["issue_id"],
                "evidence_counts": {source: len(items) for source, items in evidence.items()},
                "root_cause_hypotheses": [],
                "confidence": 0.0,
            }
        return {
            "issue_id": payload["issue_id"],
            "steps": [],
            "acceptance_criteria": [],
        }

    monkeypatch.setattr(ToolCallingAgent, "invoke", invoke)

    async def ainvoke(self: ToolCallingAgent, prompt: str) -> dict[str, object]:
        return invoke(self, prompt)

    monkeypatch.setattr(ToolCallingAgent, "ainvoke", ainvoke)

    class FakeKnowledgeModel:
        async def extract_topics(
            self,
            *,
            document_title: str,
            source_units: Sequence[DocumentSourceUnit],
            validation_errors: Sequence[str] = (),
        ) -> TopicExtractionResult:
            return TopicExtractionResult(
                topics=(
                    ExtractedTopic(
                        topic_key="saved-search-permissions",
                        title="Saved Search permissions",
                        knowledge_type="domain_rule",
                        summary=document_title,
                        source_unit_ids=(source_units[0].source_unit_id,),
                        suggested_search_queries=("saved search permissions",),
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
            candidate = next(iter(candidates[topics[0].topic_key]), None)
            if candidate:
                change = KnowledgeChangeDraft(
                    operation="update",
                    target_knowledge_id=candidate.knowledge_id,
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown=source_units[0].content,
                    source_unit_ids=(source_units[0].source_unit_id,),
                    reason="The document updates an existing rule.",
                )
            else:
                change = KnowledgeChangeDraft(
                    operation="create",
                    logical_key="saved-search-permissions",
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown=source_units[0].content,
                    source_unit_ids=(source_units[0].source_unit_id,),
                    reason="The document defines a durable rule.",
                )
            return KnowledgeChangeDraftSet(
                source_event_id=source_event_id,
                base_pcm_revision=snapshot.pcm_revision,
                changes=(change,),
            )

    pcm = InMemoryPCM()
    services = ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=FakeKnowledgeModel(),
        ),
    )
    monkeypatch.setattr(memory_sync, "get_application_services", lambda: services)
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)


@pytest.mark.asyncio
async def test_routes_analyze_issue_directly_to_reusable_analysis_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-1",
                "request_type": "analyze_issue",
                "project_id": "PROJECT-1",
                "payload": {"issue_id": "ISSUE-1"},
            },
            "document_evidence": [{"id": "DOC-1"}],
            "code_evidence": [{"id": "CODE-1"}],
            "history_evidence": [{"id": "HISTORY-1"}],
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "ISSUE-1"
    assert result["result"]["analysis"]["evidence_counts"] == {
        "documents": 1,
        "code": 1,
        "history": 1,
    }
    assert "load_and_normalize_report" not in result["completed_nodes"]
    assert result["completed_nodes"]["prepare_analysis"] is True


@pytest.mark.asyncio
async def test_new_report_reuses_issue_analysis_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-2",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-1"},
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "ISSUE-FROM-REPORT-1"
    assert result["completed_nodes"]["match_report"] is True
    assert result["completed_nodes"]["prepare_analysis"] is True
    assert result["completed_nodes"]["save_analysis"] is True


def test_existing_issue_match_skips_issue_analysis_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-3",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-2"},
            },
            "issue_candidates": [
                {
                    "issue_id": "ISSUE-EXISTING",
                    "confidence": 0.97,
                }
            ],
        }
    )

    assert result["status"] == "completed"
    assert result["result"] == {
        "action": "link_existing",
        "report_id": "REPORT-2",
        "issue_id": "ISSUE-EXISTING",
    }
    assert "prepare_analysis" not in result["completed_nodes"]


def test_uncertain_match_finishes_as_needs_review() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-4",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-3"},
            },
            "issue_candidates": [
                {
                    "issue_id": "ISSUE-CANDIDATE",
                    "confidence": 0.55,
                    "requires_review": True,
                }
            ],
        }
    )

    assert result["status"] == "needs_review"
    assert result["result"]["action"] == "needs_review"
    assert "prepare_analysis" not in result["completed_nodes"]


def test_rejects_unknown_request_type_before_routing() -> None:
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-5",
                    "request_type": "unknown",
                    "project_id": "PROJECT-1",
                    "payload": {},
                }
            }
        )


@pytest.mark.asyncio
async def test_routes_document_event_to_pcm_knowledge_pipeline() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-6",
                "request_type": "document_added",
                "project_id": "PROJECT-1",
                "payload": {
                    "document_id": "DOC-1",
                    "revision": "REV-1",
                    "title": "Saved Search requirements",
                    "markdown": "# Permissions\n\nOnly owners can edit a saved search.",
                },
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "document_synced"
    assert result["result"]["pcm_revision"] == 1
    assert len(result["result"]["created_knowledge_ids"]) == 1
    assert result["completed_nodes"]["sync_document_knowledge"] is True


@pytest.mark.asyncio
async def test_replaying_document_event_returns_same_pcm_commit() -> None:
    request = {
        "request": {
            "request_id": "REQ-DOCUMENT-REPLAY",
            "request_type": "document_added",
            "project_id": "PROJECT-REPLAY",
            "payload": {
                "document_id": "DOC-1",
                "revision": "REV-1",
                "title": "Saved Search requirements",
                "markdown": "# Permissions\n\nOnly owners can edit a saved search.",
            },
        }
    }

    first = await graph.ainvoke(request)
    replay = await graph.ainvoke(request)

    assert first["result"]["pcm_revision"] == 1
    assert replay["result"]["pcm_revision"] == 1
    assert replay["result"]["idempotent_replay"] is True


def test_document_added_requires_normalized_markdown() -> None:
    with pytest.raises(ValidationError, match="markdown"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-DOCUMENT-MISSING-CONTENT",
                    "request_type": "document_added",
                    "project_id": "PROJECT-1",
                    "payload": {
                        "document_id": "DOC-1",
                        "revision": "REV-1",
                        "title": "Saved Search requirements",
                    },
                }
            }
        )


def test_repository_added_requires_source_uri() -> None:
    with pytest.raises(ValidationError, match="source_uri"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-REPOSITORY-MISSING-SOURCE",
                    "request_type": "repository_added",
                    "project_id": "PROJECT-1",
                    "payload": {
                        "repository_id": "REPO-1",
                        "branch": "main",
                    },
                }
            }
        )


@pytest.mark.asyncio
async def test_routes_repository_change_to_incremental_mock_sync_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-7",
                "request_type": "repository_changed",
                "project_id": "PROJECT-1",
                "payload": {
                    "repository_id": "REPO-1",
                    "branch": "main",
                    "before_commit": "a" * 40,
                    "after_commit": "b" * 40,
                },
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "code_change_synced"
    assert result["completed_nodes"]["validate_code_change"] is True
