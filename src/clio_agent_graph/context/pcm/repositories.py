"""추후 PostgreSQL·Vector DB adapter가 만족할 저장소 계약."""

from collections.abc import Sequence
from typing import Protocol

from clio_agent_graph.context.pcm.models import (
    KnowledgeDocument,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectContextSnapshot,
)


class KnowledgeRepository(Protocol):
    """Knowledge 원문과 revision snapshot을 제공하는 metadata 저장소 계약."""

    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot:
        """현재 project revision을 일관된 읽기 snapshot으로 반환한다."""

        ...

    async def get_at_snapshot(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument | None:
        """지정한 snapshot에서 유효한 Knowledge revision을 조회한다."""

        ...


class KnowledgeIndex(Protocol):
    """Knowledge 검색과 비동기 색인을 분리하는 검색 저장소 계약."""

    async def search(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> Sequence[KnowledgeSearchResult]:
        """snapshot과 검색 조건을 만족하는 Knowledge 후보를 반환한다."""

        ...

    async def index(self, documents: Sequence[KnowledgeDocument]) -> None:
        """새 Knowledge revision들을 검색 가능한 형태로 반영한다."""

        ...
