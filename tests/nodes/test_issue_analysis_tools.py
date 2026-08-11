import pytest

from clio_agent_graph.context.application import (
    ApplicationServices,
    DocumentKnowledgePipeline,
)
from clio_agent_graph.context.pcm import InMemoryPCM
from clio_agent_graph.context.pcm.models import ProjectContextSnapshot
from clio_agent_graph.workflows.orchestration.nodes import issue_analysis


class _RepositoryService:
    pass


def _services() -> ApplicationServices:
    pcm = InMemoryPCM()
    return ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=object(),  # type: ignore[arg-type]
        ),
        repositories=_RepositoryService(),  # type: ignore[arg-type]
    )


def test_issue_analysis_exposes_high_level_exploration_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = _services()
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
    )

    agent = issue_analysis._agent(
        {
            "project_id": "PROJECT-1",
            "request_id": "REQ-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
        }
    )

    tool_names = {tool.name for tool in agent.analysis_agent.tools}
    assert tool_names == {
        "search_project_knowledge",
        "read_project_knowledge",
        "trace_knowledge_sources",
        "explore_codebase",
    }
    assert not tool_names.intersection(
        {
            "resolve_project_snapshot",
            "search_document_evidence",
            "search_code_evidence",
            "search_resolution_history",
            "list_project_repositories",
            "list_repository_files",
            "search_repository_code",
            "read_repository_file",
        }
    )
