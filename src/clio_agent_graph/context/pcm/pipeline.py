"""Markdown 문서를 Knowledge 변경으로 전환하는 PCM 애플리케이션 파이프라인."""

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from clio_agent_graph.context.pcm.errors import (
    KnowledgeModelOutputError,
    PCMValidationError,
)
from clio_agent_graph.context.pcm.knowledge_model import KnowledgeModel
from clio_agent_graph.context.pcm.markdown import MarkdownSourceParser
from clio_agent_graph.context.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    IngestDocumentCommand,
    KnowledgeCandidate,
    KnowledgeChange,
    KnowledgeChangeDraftSet,
    KnowledgeChangeSet,
    KnowledgeCommitResult,
    KnowledgeSearchRequest,
    ProjectContextSnapshot,
    SourceReference,
    TopicExtractionResult,
)
from clio_agent_graph.context.pcm.reader import ProjectContextReader
from clio_agent_graph.context.pcm.storage import DocumentSourceStore
from clio_agent_graph.context.pcm.writer import ProjectContextWriter


class DocumentKnowledgePipeline:
    """문서 분석, 관련 지식 조회, LLM 변경 판단과 commit을 조율한다."""

    def __init__(
        self,
        *,
        reader: ProjectContextReader,
        writer: ProjectContextWriter,
        knowledge_model: KnowledgeModel,
        parser: MarkdownSourceParser | None = None,
        source_store: DocumentSourceStore | None = None,
        max_generation_attempts: int = 2,
    ) -> None:
        if max_generation_attempts < 1:
            raise ValueError("max_generation_attempts must be at least 1")
        self._reader = reader
        self._writer = writer
        self._knowledge_model = knowledge_model
        self._parser = parser or MarkdownSourceParser()
        self._source_store = source_store
        self._max_generation_attempts = max_generation_attempts

    async def ingest(self, command: IngestDocumentCommand) -> KnowledgeCommitResult:
        previous_result = await self._writer.find_commit_by_event(
            project_id=command.project_id,
            source_event_id=command.event_id,
        )
        if previous_result is not None:
            return previous_result
        if self._source_store is not None:
            await self._source_store.save_document_source(command)
        snapshot = await self._reader.resolve_snapshot(command.project_id)
        source_units = self._parser.parse(
            document_id=command.document_id,
            revision=command.revision,
            markdown=command.markdown,
        )
        topic_result = await self._extract_topics(command.title, source_units)
        _validate_topics(topic_result, source_units)
        candidates = await self._retrieve_candidates(snapshot, topic_result.topics)
        draft_set = await self._generate_changes(
            command=command,
            snapshot=snapshot,
            topics=topic_result.topics,
            source_units=source_units,
            candidates=candidates,
        )
        change_set = _trusted_change_set(
            command=command,
            snapshot=snapshot,
            source_units=source_units,
            candidates=candidates,
            draft_set=draft_set,
        )
        return await self._writer.apply_knowledge_changes(
            project_id=command.project_id,
            change_set=change_set,
        )

    async def _extract_topics(
        self,
        document_title: str,
        source_units: Sequence[DocumentSourceUnit],
    ) -> TopicExtractionResult:
        errors: tuple[str, ...] = ()
        for attempt in range(self._max_generation_attempts):
            try:
                result = await self._knowledge_model.extract_topics(
                    document_title=document_title,
                    source_units=source_units,
                    validation_errors=errors,
                )
                _validate_topics(result, source_units)
                return result
            except (KnowledgeModelOutputError, PCMValidationError, ValidationError) as exc:
                errors = (str(exc),)
                if attempt + 1 == self._max_generation_attempts:
                    raise KnowledgeModelOutputError(
                        f"Topic extraction failed validation: {exc}"
                    ) from exc
        raise AssertionError("unreachable")

    async def _retrieve_candidates(
        self,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
    ) -> dict[str, tuple[KnowledgeCandidate, ...]]:
        candidates: dict[str, tuple[KnowledgeCandidate, ...]] = {}
        for topic in topics:
            found: dict[str, KnowledgeCandidate] = {}
            queries = (topic.title, *topic.suggested_search_queries)
            for query in dict.fromkeys(queries):
                page = await self._reader.search_knowledge(
                    snapshot=snapshot,
                    request=KnowledgeSearchRequest(
                        query=query,
                        knowledge_types=(topic.knowledge_type,),
                    ),
                )
                for hit in page.results:
                    if hit.knowledge_id in found:
                        continue
                    document = await self._reader.read_knowledge(
                        snapshot=snapshot,
                        knowledge_id=hit.knowledge_id,
                    )
                    found[hit.knowledge_id] = KnowledgeCandidate(
                        knowledge_id=document.knowledge_id,
                        knowledge_revision=document.knowledge_revision,
                        knowledge_type=document.knowledge_type,
                        title=document.title,
                        body_markdown=document.body_markdown,
                        sources=document.sources,
                        retrieval_reasons=("hybrid_search",),
                    )
            candidates[topic.topic_key] = tuple(found.values())
        return candidates

    async def _generate_changes(
        self,
        *,
        command: IngestDocumentCommand,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[DocumentSourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
    ) -> KnowledgeChangeDraftSet:
        errors: tuple[str, ...] = ()
        for attempt in range(self._max_generation_attempts):
            try:
                draft_set = await self._knowledge_model.generate_change_set(
                    source_event_id=command.event_id,
                    snapshot=snapshot,
                    topics=topics,
                    source_units=source_units,
                    candidates=candidates,
                    validation_errors=errors,
                )
                _validate_change_drafts(
                    command=command,
                    snapshot=snapshot,
                    source_units=source_units,
                    candidates=candidates,
                    draft_set=draft_set,
                )
                return draft_set
            except (KnowledgeModelOutputError, PCMValidationError, ValidationError) as exc:
                errors = (str(exc),)
                if attempt + 1 == self._max_generation_attempts:
                    raise KnowledgeModelOutputError(
                        f"Knowledge change generation failed validation: {exc}"
                    ) from exc
        raise AssertionError("unreachable")


def _validate_topics(
    result: TopicExtractionResult,
    source_units: Sequence[DocumentSourceUnit],
) -> None:
    valid_source_ids = {unit.source_unit_id for unit in source_units}
    topic_keys: set[str] = set()
    for topic in result.topics:
        if topic.topic_key in topic_keys:
            raise PCMValidationError(f"Duplicate topic key: {topic.topic_key}")
        topic_keys.add(topic.topic_key)
        unknown = set(topic.source_unit_ids) - valid_source_ids
        if unknown:
            raise PCMValidationError(f"Topic references unknown Source Units: {sorted(unknown)}")
        if any(not query.strip() for query in topic.suggested_search_queries):
            raise PCMValidationError("Topic search queries must not be blank.")


def _validate_change_drafts(
    *,
    command: IngestDocumentCommand,
    snapshot: ProjectContextSnapshot,
    source_units: Sequence[DocumentSourceUnit],
    candidates: Mapping[str, Sequence[KnowledgeCandidate]],
    draft_set: KnowledgeChangeDraftSet,
) -> None:
    if draft_set.source_event_id != command.event_id:
        raise PCMValidationError("Knowledge change set source_event_id does not match the event.")
    if draft_set.base_pcm_revision != snapshot.pcm_revision:
        raise PCMValidationError("Knowledge change set base revision does not match the snapshot.")
    valid_source_ids = {unit.source_unit_id for unit in source_units}
    candidate_ids = {
        candidate.knowledge_id
        for topic_candidates in candidates.values()
        for candidate in topic_candidates
    }
    for change in draft_set.changes:
        unknown_sources = set(change.source_unit_ids) - valid_source_ids
        if unknown_sources:
            raise PCMValidationError(
                f"Knowledge change references unknown Source Units: {sorted(unknown_sources)}"
            )
        if (
            change.operation in {"update", "no_change"}
            and change.target_knowledge_id not in candidate_ids
        ):
            raise PCMValidationError(
                f"Knowledge change targets an unretrieved candidate: {change.target_knowledge_id}"
            )


def _trusted_change_set(
    *,
    command: IngestDocumentCommand,
    snapshot: ProjectContextSnapshot,
    source_units: Sequence[DocumentSourceUnit],
    candidates: Mapping[str, Sequence[KnowledgeCandidate]],
    draft_set: KnowledgeChangeDraftSet,
) -> KnowledgeChangeSet:
    _validate_change_drafts(
        command=command,
        snapshot=snapshot,
        source_units=source_units,
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
                _source_reference(units[source_id]) for source_id in draft.source_unit_ids
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


def _source_reference(unit: DocumentSourceUnit) -> SourceReference:
    return SourceReference(
        source_type="document",
        source_id=unit.document_id,
        source_revision=unit.source_revision,
        locator={"heading_path": list(unit.heading_path)},
        content_hash=unit.content_hash,
    )
