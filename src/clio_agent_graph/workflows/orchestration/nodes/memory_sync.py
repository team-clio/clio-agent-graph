"""문서·레포지토리·코드 변경 메모리 동기화 노드."""

import asyncio

from clio_agent_graph.context.application import get_application_services
from clio_agent_graph.context.mock import mock_service
from clio_agent_graph.context.pcm import (
    IngestDocumentCommand,
    IngestRepositoryCommand,
    KnowledgeCommitResult,
)
from clio_agent_graph.workflows.orchestration.state import ClioState


def prepare_document_sync(state: ClioState) -> dict[str, object]:
    """문서 삭제 경로가 후속 색인·commit 단계에서 사용할 상태를 준비한다."""

    # TODO: 원본 조회, 정규화, 메타데이터 추출 및 chunk 생성을 실제 서비스로 교체.
    return {
        "document_sync": {"document_id": state["document_id"], "revision": state["revision"]},
        "completed_nodes": {"prepare_document_sync": True},
    }


async def sync_document_knowledge(state: ClioState) -> dict[str, object]:
    """정규화 Markdown을 LLM으로 분석하고 검증된 Knowledge commit을 만든다."""

    result = await get_application_services().document_pipeline.ingest(
        IngestDocumentCommand(
            event_id=state["request_id"],
            project_id=state["project_id"],
            document_id=state["document_id"],
            revision=state["revision"],
            title=state["document_title"],
            markdown=state["document_markdown"],
            source_metadata=state.get("source_metadata", {}),
        )
    )
    return {
        "document_sync": {
            "document_id": state["document_id"],
            "source_revision": state["revision"],
            "pcm_revision": result.pcm_revision,
            "commit_id": result.commit_id,
        },
        "status": "completed",
        "result": {
            "action": "document_synced",
            "document_id": state["document_id"],
            "source_revision": state["revision"],
            "pcm_revision": result.pcm_revision,
            "created_knowledge_ids": list(result.created_knowledge_ids),
            "updated_knowledge_ids": list(result.updated_knowledge_ids),
            "unchanged_knowledge_ids": list(result.unchanged_knowledge_ids),
            "idempotent_replay": result.idempotent_replay,
        },
        "completed_nodes": {"sync_document_knowledge": True},
    }


def update_document_index(state: ClioState) -> dict[str, object]:
    """문서 삭제에 따른 검색 인덱스 갱신 위치를 명시하는 임시 노드."""

    # TODO: 임베딩 생성과 Vector DB 추가·교체·비활성화 구현.
    return {"completed_nodes": {"update_document_index": True}}


def commit_document_revision(state: ClioState) -> dict[str, object]:
    """문서 삭제 동기화 결과를 외부에 공개할 완료 상태로 확정한다."""

    committed = mock_service.commit_sync(
        "document", state["project_id"], state["document_id"], state["revision"]
    )
    return {
        "status": "completed",
        "result": {"action": "document_synced", "sync": committed},
        "completed_nodes": {"commit_document_revision": True},
    }


def prepare_repository_sync(state: ClioState) -> dict[str, object]:
    """Repository 등록 입력을 Graph write boundary에서 준비한다."""

    return {
        "repository_sync": {
            "repository_id": state["repository_id"],
            "branch": state["branch"],
            "operation": state["request_type"],
        },
        "completed_nodes": {"prepare_repository_sync": True},
    }


async def build_repository_index(state: ClioState) -> dict[str, object]:
    """bare Git mirror를 생성·갱신하고 선택한 commit을 활성화한다."""

    services = await asyncio.to_thread(get_application_services)
    service = services.repositories
    if service is None:
        return {"completed_nodes": {"build_repository_index": True}}
    try:
        if state["request_type"] == "repository_removed":
            removed = await service.remove(
                project_id=state["project_id"], repository_id=state["repository_id"]
            )
            sync = {**state["repository_sync"], "removed": removed}
        else:
            registration = await service.register(
                project_id=state["project_id"],
                repository_id=state["repository_id"],
                source_uri=state["repository_source_uri"],
                branch=state["branch"],
                commit=state.get("revision"),
            )
            sync = registration.model_dump(mode="json")
            if services.repository_pipeline is not None:
                knowledge = await services.repository_pipeline.ingest(
                    IngestRepositoryCommand(
                        event_id=state["request_id"],
                        project_id=state["project_id"],
                        repository_id=state["repository_id"],
                        commit=registration.active_commit,
                    )
                )
                sync["knowledge"] = _knowledge_result(knowledge)
    except Exception:
        if state["request_type"] == "repository_added" and services.clio_server is not None:
            await asyncio.to_thread(
                services.clio_server.fail_repository_sync,
                state["project_id"],
                state["repository_id"],
            )
        raise
    if state["request_type"] == "repository_added" and services.clio_server is not None:
        await asyncio.to_thread(
            services.clio_server.complete_repository_sync,
            state["project_id"],
            state["repository_id"],
        )
    return {
        "repository_sync": sync,
        "completed_nodes": {"build_repository_index": True},
    }


def commit_repository_revision(state: ClioState) -> dict[str, object]:
    """Repository 등록·제거 결과를 공통 응답 형식으로 확정한다."""

    if get_application_services().repositories is None:
        committed = mock_service.commit_sync(
            "repository", state["project_id"], state["repository_id"], state.get("revision")
        )
    else:
        committed = state["repository_sync"]
    return {
        "status": "completed",
        "result": {"action": "repository_synced", "sync": committed},
        "completed_nodes": {"commit_repository_revision": True},
    }


async def validate_code_change(state: ClioState) -> dict[str, object]:
    """증분 이벤트의 before revision이 현재 active commit인지 확인한다."""

    service = get_application_services().repositories
    if service is not None:
        revisions = await service.list_revisions(state["project_id"])
        if revisions.get(state["repository_id"]) != state["before_commit"]:
            raise ValueError("before_commit does not match the active repository revision")
    return {"completed_nodes": {"validate_code_change": True}}


async def calculate_code_changes(state: ClioState) -> dict[str, object]:
    """두 commit 사이에서 변경된 tracked path를 계산한다."""

    service = get_application_services().repositories
    changed_paths = []
    if service is not None:
        changed_paths = await service.changed_paths(
            project_id=state["project_id"],
            repository_id=state["repository_id"],
            before_commit=state["before_commit"],
            after_commit=state["after_commit"],
        )
    return {
        "code_change": {
            "repository_id": state["repository_id"],
            "before_commit": state["before_commit"],
            "after_commit": state["after_commit"],
            "changed_paths": changed_paths,
        },
        "completed_nodes": {"calculate_code_changes": True},
    }


def update_changed_code_index(state: ClioState) -> dict[str, object]:
    """변경된 코드 경로만 재색인할 향후 구현 위치를 표시한다."""

    # TODO: 변경/삭제 chunk만 증분 반영.
    return {"completed_nodes": {"update_changed_code_index": True}}


async def commit_code_revision(state: ClioState) -> dict[str, object]:
    """검증된 branch head를 활성 revision으로 바꾸고 변경 목록을 반환한다."""

    service = get_application_services().repositories
    if service is None:
        committed = mock_service.commit_sync(
            "code_change", state["project_id"], state["repository_id"], state["after_commit"]
        )
    else:
        registration = await service.activate_revision(
            project_id=state["project_id"],
            repository_id=state["repository_id"],
            branch=state["branch"],
            after_commit=state["after_commit"],
        )
        committed = {
            **registration.model_dump(mode="json"),
            "changed_paths": state["code_change"]["changed_paths"],
        }
        # TODO: reconcile repository-derived PCM knowledge after repository lifecycle changes.
    return {
        "status": "completed",
        "result": {"action": "code_change_synced", "sync": committed},
        "completed_nodes": {"commit_code_revision": True},
    }


def _knowledge_result(result: KnowledgeCommitResult) -> dict[str, object]:
    """Repository sync 결과에 공개할 Knowledge commit 요약."""

    return {
        "commit_id": result.commit_id,
        "pcm_revision": result.pcm_revision,
        "created_knowledge_ids": list(result.created_knowledge_ids),
        "updated_knowledge_ids": list(result.updated_knowledge_ids),
        "unchanged_knowledge_ids": list(result.unchanged_knowledge_ids),
        "idempotent_replay": result.idempotent_replay,
    }
