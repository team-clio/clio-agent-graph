"""Graph Node만 사용할 PCM Writer 계약."""

from typing import Protocol

from clio_agent_graph.context.pcm.models import KnowledgeChangeSet, KnowledgeCommitResult


class ProjectContextWriter(Protocol):
    """검증된 Knowledge 변경을 프로젝트 revision으로 commit한다."""

    async def find_commit_by_event(
        self,
        *,
        project_id: str,
        source_event_id: str,
    ) -> KnowledgeCommitResult | None:
        """source event가 이미 처리됐는지 확인해 중복 쓰기를 막는다."""

        ...

    async def apply_knowledge_changes(
        self,
        *,
        project_id: str,
        change_set: KnowledgeChangeSet,
    ) -> KnowledgeCommitResult:
        """base revision을 확인하고 변경 묶음을 하나의 PCM revision으로 적용한다."""

        ...
