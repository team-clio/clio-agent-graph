"""프로젝트 컨텍스트 계층의 구현 독립적인 인터페이스."""

from collections.abc import Sequence
from typing import Any, Protocol


class ProjectContextService(Protocol):
    """문서·코드·해결 이력 검색을 제공할 추후 구현 계약.

    현재 Vertical Slice는 그래프 흐름만 구현하므로 구체 클래스나 저장소 연결을
    제공하지 않는다. 이후 Vector DB, Git 및 RDBMS 구현체가 이 계약을 만족해야 한다.
    """

    async def resolve_snapshot(self, project_id: str) -> dict[str, Any]:
        """분석에 사용할 문서 및 코드 revision을 고정한다."""

        ...

    async def search_documents(
        self,
        *,
        project_id: str,
        queries: Sequence[str],
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """프로젝트 문서에서 관련 근거를 찾는다."""

        ...

    async def search_code(
        self,
        *,
        project_id: str,
        queries: Sequence[str],
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """등록된 코드베이스에서 관련 근거를 찾는다."""

        ...

    async def search_resolution_history(
        self,
        *,
        project_id: str,
        queries: Sequence[str],
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """과거 해결 이슈에서 관련 근거를 찾는다."""

        ...
