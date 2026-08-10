"""고정된 프로젝트 snapshot을 Agent에 읽기 전용으로 노출하는 PCM Tool."""

from dataclasses import dataclass

from langchain_core.tools import BaseTool, tool

from clio_agent_graph.context.pcm.models import (
    KnowledgeSearchRequest,
    KnowledgeType,
    ProjectContextSnapshot,
)
from clio_agent_graph.context.pcm.reader import ProjectContextReader


@dataclass(frozen=True)
class PCMToolContext:
    """Graph가 선택하고 Agent가 변경할 수 없는 접근 범위."""

    project_id: str
    request_id: str
    snapshot: ProjectContextSnapshot


class PCMToolFactory:
    """요청의 project와 snapshot이 closure에 고정된 읽기 Tool을 만든다."""

    def __init__(self, reader: ProjectContextReader) -> None:
        self._reader = reader

    def create_tools(self, context: PCMToolContext) -> list[BaseTool]:
        reader = self._reader

        @tool
        async def search_project_knowledge(
            query: str,
            knowledge_types: list[KnowledgeType] | None = None,
            limit: int = 8,
        ) -> dict[str, object]:
            """현재 프로젝트 snapshot의 장기 지식에서 관련 주제를 검색한다."""

            page = await reader.search_knowledge(
                snapshot=context.snapshot,
                request=KnowledgeSearchRequest(
                    query=query,
                    knowledge_types=tuple(knowledge_types) if knowledge_types else None,
                    limit=limit,
                ),
            )
            return page.model_dump(mode="json")

        @tool
        async def read_project_knowledge(knowledge_id: str) -> dict[str, object]:
            """검색에서 선택한 Knowledge의 현재 snapshot 전체 내용을 읽는다."""

            document = await reader.read_knowledge(
                snapshot=context.snapshot,
                knowledge_id=knowledge_id,
            )
            content_limit = 12_000
            result = document.model_dump(mode="json")
            result["body_markdown"] = document.body_markdown[:content_limit]
            result["truncated"] = len(document.body_markdown) > content_limit
            return result

        @tool
        async def trace_knowledge_sources(knowledge_id: str) -> dict[str, object]:
            """Knowledge를 뒷받침한 문서·코드·해결 이슈의 provenance를 조회한다."""

            sources = await reader.trace_knowledge_sources(
                snapshot=context.snapshot,
                knowledge_id=knowledge_id,
            )
            return {
                "knowledge_id": knowledge_id,
                "pcm_revision": context.snapshot.pcm_revision,
                "sources": [source.model_dump(mode="json") for source in sources],
            }

        return [
            search_project_knowledge,
            read_project_knowledge,
            trace_knowledge_sources,
        ]
