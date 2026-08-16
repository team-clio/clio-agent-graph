"""Agent 읽기 Tool 뒤에서 사용할 PCM Reader 계약."""

from typing import Protocol

from clio_agent_graph.context.pcm.models import (
    KnowledgeDocument,
    KnowledgeSearchPage,
    KnowledgeSearchRequest,
    ProjectContextSnapshot,
    SourceReference,
)


class ProjectContextReader(Protocol):
    """프로젝트 snapshot에 고정된 지식 읽기 인터페이스."""

    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot:
        """한 번의 분석이 끝까지 사용할 project revision들을 고정한다."""

        ...

    async def search_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchPage:
        """지정한 snapshot 안에서 관련 Knowledge를 검색한다."""

        ...

    async def read_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument:
        """검색으로 선택한 Knowledge의 snapshot 시점 원문을 읽는다."""

        ...

    async def list_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
    ) -> tuple[KnowledgeDocument, ...]:
        """snapshot 시점에 유효한 Knowledge 전체를 나열한다."""

        ...

    async def trace_knowledge_sources(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> tuple[SourceReference, ...]:
        """Knowledge 주장을 뒷받침하는 문서·코드·해결 이력 출처를 읽는다."""

        ...
