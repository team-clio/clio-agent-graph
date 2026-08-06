"""Agent 읽기 Tool 뒤에서 사용할 PCM Reader 계약."""

from typing import Protocol

from clio_agent_graph.services.pcm.models import (
    KnowledgeDocument,
    KnowledgeSearchPage,
    KnowledgeSearchRequest,
    ProjectContextSnapshot,
    SourceReference,
)


class ProjectContextReader(Protocol):
    """프로젝트 snapshot에 고정된 지식 읽기 인터페이스."""

    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot: ...

    async def search_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchPage: ...

    async def read_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument: ...

    async def trace_knowledge_sources(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> tuple[SourceReference, ...]: ...
