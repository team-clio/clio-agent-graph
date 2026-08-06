"""추후 PostgreSQL·Vector DB adapter가 만족할 저장소 계약."""

from collections.abc import Sequence
from typing import Protocol

from clio_agent_graph.services.pcm.models import (
    KnowledgeDocument,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectContextSnapshot,
)


class KnowledgeRepository(Protocol):
    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot: ...

    async def get_at_snapshot(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument | None: ...


class KnowledgeIndex(Protocol):
    async def search(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> Sequence[KnowledgeSearchResult]: ...

    async def index(self, documents: Sequence[KnowledgeDocument]) -> None: ...
