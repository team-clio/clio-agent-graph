import pytest

from clio_agent_graph.context.application import (
    ApplicationServices,
    DocumentKnowledgePipeline,
)
from clio_agent_graph.context.pcm import InMemoryPCM, KnowledgeCommitResult
from clio_agent_graph.context.repository import RepositoryRegistration
from clio_agent_graph.workflows.orchestration.nodes import memory_sync


class _Repositories:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    async def remove(self, *, project_id: str, repository_id: str) -> bool:
        self.removed.append((project_id, repository_id))
        return True


class _RepositoryPipeline:
    def __init__(self) -> None:
        self.commands: list[object] = []

    async def ingest(self, command: object) -> object:
        self.commands.append(command)
        return KnowledgeCommitResult(
            commit_id="commit-1",
            project_id="PROJECT-1",
            source_event_id="REQ-1",
            base_pcm_revision=0,
            pcm_revision=1,
            created_knowledge_ids=("knowledge-1",),
        )


def _services(repositories: _Repositories) -> ApplicationServices:
    pcm = InMemoryPCM()
    return ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=object(),  # type: ignore[arg-type]
        ),
        repositories=repositories,  # type: ignore[arg-type]
        repository_pipeline=_RepositoryPipeline(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_repository_removal_does_not_reconcile_pcm_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _Repositories()
    monkeypatch.setattr(memory_sync, "get_application_services", lambda: _services(repositories))

    result = await memory_sync.build_repository_index(
        {
            "request_type": "repository_removed",
            "project_id": "PROJECT-1",
            "repository_id": "backend",
            "repository_sync": {"repository_id": "backend"},
        }
    )

    assert repositories.removed == [("PROJECT-1", "backend")]
    assert result["repository_sync"] == {"repository_id": "backend", "removed": True}


@pytest.mark.asyncio
async def test_repository_registration_ingests_active_commit_into_pcm_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repositories(_Repositories):
        async def register(self, **_: object) -> RepositoryRegistration:
            return RepositoryRegistration(
                project_id="PROJECT-1",
                repository_id="backend",
                branch="main",
                active_commit="a" * 40,
                file_count=3,
            )

    repositories = Repositories()
    services = _services(repositories)
    monkeypatch.setattr(memory_sync, "get_application_services", lambda: services)

    result = await memory_sync.build_repository_index(
        {
            "request_id": "REQ-1",
            "request_type": "repository_added",
            "project_id": "PROJECT-1",
            "repository_id": "backend",
            "repository_source_uri": "https://github.com/acme/backend.git",
            "branch": "main",
            "repository_sync": {"repository_id": "backend"},
        }
    )

    assert result["repository_sync"]["knowledge"]["pcm_revision"] == 1
