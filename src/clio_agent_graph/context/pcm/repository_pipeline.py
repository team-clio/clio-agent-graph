"""고정 Git repository source를 PCM Knowledge 변경으로 전환하는 파이프라인."""

from collections.abc import Mapping, Sequence

from clio_agent_graph.context.pcm.knowledge_model import KnowledgeModel
from clio_agent_graph.context.pcm.models import (
    ExtractedTopic,
    IngestRepositoryCommand,
    KnowledgeCandidate,
    KnowledgeChange,
    KnowledgeChangeDraftSet,
    KnowledgeChangeSet,
    KnowledgeCommitResult,
    ProjectContextSnapshot,
    RepositorySourceUnit,
    SourceReference,
)
from clio_agent_graph.context.pcm.pipeline import (
    DocumentKnowledgePipeline,
    _validate_change_drafts,
    _validate_topics,
)
from clio_agent_graph.context.pcm.reader import ProjectContextReader
from clio_agent_graph.context.pcm.writer import ProjectContextWriter
from clio_agent_graph.context.repository import GitRepositoryService, RepositoryError


class RepositoryKnowledgePipeline(DocumentKnowledgePipeline):
    """bounded code units를 분석해 architecture·component·operation 지식을 갱신한다."""

    def __init__(
        self,
        *,
        reader: ProjectContextReader,
        writer: ProjectContextWriter,
        knowledge_model: KnowledgeModel,
        repositories: GitRepositoryService,
        max_generation_attempts: int = 2,
    ) -> None:
        super().__init__(
            reader=reader,
            writer=writer,
            knowledge_model=knowledge_model,
            max_generation_attempts=max_generation_attempts,
        )
        self._repositories = repositories

    async def ingest(self, command: IngestRepositoryCommand) -> KnowledgeCommitResult:
        """활성 commit의 코드를 분석해 검증된 Knowledge 변경으로 commit한다."""

        # 같은 이벤트를 다시 받아도 LLM과 저장소 작업을 반복하지 않는다.
        previous = await self._writer.find_commit_by_event(
            project_id=command.project_id,
            source_event_id=command.event_id,
        )
        if previous is not None:
            return previous
        revisions = await self._repositories.list_revisions(command.project_id)
        if revisions.get(command.repository_id) != command.commit:
            raise RepositoryError("repository Knowledge command is not the active commit")
        snapshot = await self._reader.resolve_snapshot(command.project_id)
        snapshot = snapshot.model_copy(update={"repository_revisions": revisions})
        source_units = await self._repositories.collect_source_units(
            project_id=command.project_id,
            repository_id=command.repository_id,
            commit=command.commit,
        )
        topics = await self._extract_topics(
            f"Repository {command.repository_id} source code at {command.commit}", source_units
        )
        _validate_topics(topics, source_units)
        candidates = await self._retrieve_candidates(snapshot, topics.topics)
        drafts = await self._generate_repository_changes(
            command=command,
            snapshot=snapshot,
            topics=topics.topics,
            source_units=source_units,
            candidates=candidates,
        )
        change_set = _trusted_repository_change_set(
            command=command,
            snapshot=snapshot,
            source_units=source_units,
            candidates=candidates,
            draft_set=drafts,
        )
        return await self._writer.apply_knowledge_changes(
            project_id=command.project_id,
            change_set=change_set,
        )

    async def _generate_repository_changes(
        self,
        *,
        command: IngestRepositoryCommand,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[RepositorySourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
    ) -> KnowledgeChangeDraftSet:
        # The shared generator already validates source IDs, candidate targets, and base revision.
        return await self._generate_changes(
            command=command,  # type: ignore[arg-type]
            snapshot=snapshot,
            topics=topics,
            source_units=source_units,  # type: ignore[arg-type]
            candidates=candidates,
        )


def _trusted_repository_change_set(
    *,
    command: IngestRepositoryCommand,
    snapshot: ProjectContextSnapshot,
    source_units: Sequence[RepositorySourceUnit],
    candidates: Mapping[str, Sequence[KnowledgeCandidate]],
    draft_set: KnowledgeChangeDraftSet,
) -> KnowledgeChangeSet:
    _validate_change_drafts(
        command=command,  # type: ignore[arg-type]
        snapshot=snapshot,
        source_units=source_units,  # type: ignore[arg-type]
        candidates=candidates,
        draft_set=draft_set,
    )
    units = {unit.source_unit_id: unit for unit in source_units}
    changes = tuple(
        KnowledgeChange(
            operation=draft.operation,
            logical_key=draft.logical_key,
            target_knowledge_id=draft.target_knowledge_id,
            knowledge_type=draft.knowledge_type,
            title=draft.title,
            body_markdown=draft.body_markdown,
            sources=tuple(
                _repository_source_reference(units[source_id])
                for source_id in draft.source_unit_ids
            ),
            related_knowledge_ids=draft.related_knowledge_ids,
            reason=draft.reason,
        )
        for draft in draft_set.changes
    )
    return KnowledgeChangeSet(
        source_event_id=command.event_id,
        base_pcm_revision=snapshot.pcm_revision,
        changes=changes,
    )


def _repository_source_reference(unit: RepositorySourceUnit) -> SourceReference:
    return SourceReference(
        source_type="repository",
        source_id=unit.repository_id,
        source_revision=unit.commit,
        locator={
            "path": unit.path,
            "start_line": unit.start_line,
            "end_line": unit.end_line,
        },
        content_hash=unit.content_hash,
    )
