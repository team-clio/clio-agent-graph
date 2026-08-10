"""단일 Agent Server 프로세스에서 공유하는 애플리케이션 서비스 구성."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from clio_agent_graph.context.pcm import DocumentKnowledgePipeline, InMemoryPCM
from clio_agent_graph.context.pcm.knowledge_model import LangChainKnowledgeModel
from clio_agent_graph.context.pcm.postgres import PostgresPCM
from clio_agent_graph.context.pcm.reader import ProjectContextReader
from clio_agent_graph.context.pcm.repository_pipeline import RepositoryKnowledgePipeline
from clio_agent_graph.context.pcm.settings import PCMStorageSettings
from clio_agent_graph.context.pcm.storage import MarkdownStore
from clio_agent_graph.context.pcm.writer import ProjectContextWriter
from clio_agent_graph.context.repository import GitRepositoryService


class PCMService(ProjectContextReader, ProjectContextWriter, Protocol):
    """Graph가 사용하는 PCM Reader/Writer 결합 계약."""


@dataclass(frozen=True)
class ApplicationServices:
    """Graph Node가 사용할 수명 주기가 긴 서비스 묶음."""

    pcm: PCMService
    document_pipeline: DocumentKnowledgePipeline
    repositories: GitRepositoryService | None = None
    repository_pipeline: RepositoryKnowledgePipeline | None = None


@lru_cache(maxsize=1)
def get_application_services() -> ApplicationServices:
    """단일 노드 v1용 in-memory PCM과 `.env` 기반 Knowledge LLM을 구성한다."""

    storage = PCMStorageSettings.from_env()
    if storage.persistent_enabled:
        assert storage.database_url is not None
        pcm: PCMService = PostgresPCM(
            database_url=storage.database_url,
            markdown_store=MarkdownStore(storage.data_root),
        )
        source_store = pcm
    else:
        pcm = InMemoryPCM()
        source_store = None
    repositories = GitRepositoryService.from_data_root(storage.data_root)
    knowledge_model = LangChainKnowledgeModel()
    return ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=knowledge_model,
            source_store=source_store,
        ),
        repositories=repositories,
        repository_pipeline=RepositoryKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=knowledge_model,
            repositories=repositories,
        ),
    )
