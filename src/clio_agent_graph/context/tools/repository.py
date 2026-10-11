"""고정된 repository commit snapshot을 Agent에 노출하는 읽기 Tool."""

from langchain_core.tools import BaseTool, tool

from clio_agent_graph.context.pcm.models import ProjectContextSnapshot
from clio_agent_graph.context.repository import GitRepositoryService, RepositoryError


class RepositoryToolFactory:
    """Graph가 고정한 project 및 commit만 접근하는 Repository Tool을 만든다."""

    def __init__(self, repository_service: GitRepositoryService) -> None:
        self._service = repository_service

    def create_tools(self, snapshot: ProjectContextSnapshot) -> list[BaseTool]:
        """고정 snapshot 밖으로 벗어날 수 없는 Repository 읽기 Tool을 만든다."""

        service = self._service

        @tool
        async def list_project_repositories() -> dict[str, object]:
            """현재 분석 snapshot에 등록된 repository와 고정 commit을 조회한다."""

            repositories = await service.list_repositories(snapshot)
            return {"repositories": [item.model_dump(mode="json") for item in repositories]}

        @tool
        async def list_repository_files(
            repository_id: str | None = None,
            limit: int = 100,
        ) -> dict[str, object]:
            """현재 snapshot commit의 비밀 경로를 제외한 tracked 파일을 제한적으로 나열한다."""

            try:
                files = await service.list_files(
                    snapshot=snapshot,
                    repository_id=repository_id,
                    limit=limit,
                )
            except RepositoryError as error:
                return {"error": str(error), "files": []}
            return {"files": files}

        @tool
        async def search_repository_code(
            query: str,
            repository_id: str | None = None,
            limit: int = 20,
        ) -> dict[str, object]:
            """현재 snapshot commit의 tracked source에서 text 또는 symbol을 검색한다.

            결과는 소스 → 테스트 → 설정 → 문서 순이고 파일당 최대 2줄이다. `truncated`가 true면
            `total_matches` 중 일부만 반환된 것이므로 검색어를 좁히거나 파일을 직접 읽는다.
            """

            try:
                result = await service.search_with_stats(
                    snapshot=snapshot,
                    query=query,
                    repository_id=repository_id,
                    limit=limit,
                )
            except RepositoryError as error:
                return {"error": str(error), "results": []}
            return {
                "results": [hit.model_dump(mode="json") for hit in result.hits],
                "total_matches": result.total_matches,
                "truncated": result.truncated,
            }

        @tool
        async def read_repository_file(
            repository_id: str,
            path: str,
            start_line: int = 1,
            end_line: int = 200,
        ) -> dict[str, object]:
            """현재 snapshot commit에서 tracked 파일의 제한된 line 범위를 읽는다."""

            try:
                return await service.read_file(
                    snapshot=snapshot,
                    repository_id=repository_id,
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                )
            except RepositoryError as error:
                return {
                    "error": str(error),
                    "repository_id": repository_id,
                    "path": path,
                }

        return [
            list_project_repositories,
            list_repository_files,
            search_repository_code,
            read_repository_file,
        ]
