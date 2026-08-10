import pytest

from clio_agent_graph.nodes import memory_sync
from clio_agent_graph.services.application import (
    ApplicationServices,
    DocumentKnowledgePipeline,
)
from clio_agent_graph.services.pcm import InMemoryPCM


class _Repositories:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    async def remove(self, *, project_id: str, repository_id: str) -> bool:
        self.removed.append((project_id, repository_id))
        return True


class _RepositoryPipeline:
    async def ingest(self, command: object) -> object:
        raise AssertionError("repository lifecycle must not ingest PCM knowledge")


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
