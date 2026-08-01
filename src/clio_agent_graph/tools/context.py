"""프로젝트 컨텍스트를 읽기 전용으로 노출하는 Agent Tool."""

from langchain_core.tools import tool

from clio_agent_graph.services.mock import mock_service


@tool
def resolve_project_snapshot(project_id: str) -> dict[str, object]:
    """분석 실행에 고정할 프로젝트 문서·레포지토리 revision을 가져온다."""

    # TODO: 실행 단위 snapshot을 실제 ProjectContextService에서 조회한다.
    return mock_service.resolve_snapshot(project_id)


@tool
def search_document_evidence(project_id: str, queries: list[str]) -> list[dict[str, object]]:
    """요구사항, 정책, 아키텍처 문서에서 이슈 근거를 검색한다."""

    return mock_service.search("document", project_id, queries)


@tool
def search_code_evidence(project_id: str, queries: list[str]) -> list[dict[str, object]]:
    """등록된 레포지토리의 파일, 심볼, 호출 관계에서 이슈 근거를 검색한다."""

    return mock_service.search("code", project_id, queries)


@tool
def search_resolution_history(project_id: str, queries: list[str]) -> list[dict[str, object]]:
    """과거 해결 이슈, root cause, 수정 commit 및 검증 이력을 검색한다."""

    return mock_service.search("resolution", project_id, queries)
