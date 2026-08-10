"""Project Context Memory의 도메인 계약과 기본 구현."""

from clio_agent_graph.context.pcm.embedding import DeterministicLocalEmbedding, EmbeddingProvider
from clio_agent_graph.context.pcm.memory import InMemoryPCM
from clio_agent_graph.context.pcm.models import (
    IngestDocumentCommand,
    IngestRepositoryCommand,
    KnowledgeChange,
    KnowledgeChangeSet,
    KnowledgeCommitResult,
    KnowledgeDocument,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectContextSnapshot,
    RepositorySourceUnit,
    SourceReference,
)
from clio_agent_graph.context.pcm.pipeline import DocumentKnowledgePipeline
from clio_agent_graph.context.pcm.postgres import PostgresPCM
from clio_agent_graph.context.pcm.reader import ProjectContextReader
from clio_agent_graph.context.pcm.repository_pipeline import RepositoryKnowledgePipeline
from clio_agent_graph.context.pcm.writer import ProjectContextWriter

__all__ = [
    "InMemoryPCM",
    "DocumentKnowledgePipeline",
    "DeterministicLocalEmbedding",
    "EmbeddingProvider",
    "IngestDocumentCommand",
    "IngestRepositoryCommand",
    "KnowledgeChange",
    "KnowledgeChangeSet",
    "KnowledgeCommitResult",
    "KnowledgeDocument",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResult",
    "ProjectContextReader",
    "ProjectContextSnapshot",
    "ProjectContextWriter",
    "RepositoryKnowledgePipeline",
    "RepositorySourceUnit",
    "PostgresPCM",
    "SourceReference",
]
