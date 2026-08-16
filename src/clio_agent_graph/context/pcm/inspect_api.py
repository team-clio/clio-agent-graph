"""PCM Knowledge를 읽기 전용으로 노출하는 standalone FastAPI 앱."""

from fastapi import FastAPI, HTTPException

from clio_agent_graph.context.application import get_application_services
from clio_agent_graph.context.pcm.errors import KnowledgeNotFoundError
from clio_agent_graph.context.pcm.models import (
    KnowledgeDocument,
    ProjectContextSnapshot,
)
from clio_agent_graph.context.pcm.reader import ProjectContextReader


def create_app(reader: ProjectContextReader) -> FastAPI:
    """테스트에서 PCM 구현을 주입할 수 있는 inspect 앱을 만든다."""

    app = FastAPI(title="Clio PCM Inspect API")

    @app.get("/pcm/projects/{project_id}/snapshot", response_model=ProjectContextSnapshot)
    async def read_snapshot(project_id: str) -> ProjectContextSnapshot:
        """프로젝트의 active PCM revision과 index revision을 반환한다."""

        return await reader.resolve_snapshot(project_id)

    @app.get(
        "/pcm/projects/{project_id}/knowledge",
        response_model=list[KnowledgeDocument],
    )
    async def list_knowledge(project_id: str) -> list[KnowledgeDocument]:
        """snapshot 시점에 유효한 Knowledge 목록을 반환한다."""

        snapshot = await reader.resolve_snapshot(project_id)
        return list(await reader.list_knowledge(snapshot=snapshot))

    @app.get(
        "/pcm/projects/{project_id}/knowledge/{knowledge_id}",
        response_model=KnowledgeDocument,
    )
    async def read_knowledge(project_id: str, knowledge_id: str) -> KnowledgeDocument:
        """Knowledge 상세를 반환한다. 유효하지 않으면 404를 응답한다."""

        snapshot = await reader.resolve_snapshot(project_id)
        try:
            return await reader.read_knowledge(snapshot=snapshot, knowledge_id=knowledge_id)
        except KnowledgeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


def build_app() -> FastAPI:
    """운영 설정으로 inspect 앱을 만든다. (uvicorn 진입점)"""

    return create_app(get_application_services().pcm)


app = build_app()
