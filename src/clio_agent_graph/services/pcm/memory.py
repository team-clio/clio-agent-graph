"""PCM 도메인 규칙을 검증하기 위한 결정적 in-memory 구현."""

import asyncio
import re
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid4, uuid5

from clio_agent_graph.services.pcm.errors import (
    KnowledgeNotFoundError,
    PCMRevisionConflict,
    PCMValidationError,
)
from clio_agent_graph.services.pcm.models import (
    KnowledgeChange,
    KnowledgeChangeSet,
    KnowledgeCommitResult,
    KnowledgeDocument,
    KnowledgeSearchPage,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectContextSnapshot,
    SourceReference,
)

_TOKEN_PATTERN = re.compile(r"[\w./:{}-]+", re.UNICODE)


class InMemoryPCM:
    """Reader와 Writer 계약을 함께 만족하는 테스트·개발용 PCM."""

    def __init__(self) -> None:
        self._project_revisions: dict[str, int] = defaultdict(int)
        self._histories: dict[tuple[str, str], list[KnowledgeDocument]] = defaultdict(list)
        self._logical_ids: dict[tuple[str, str], str] = {}
        self._event_results: dict[tuple[str, str], KnowledgeCommitResult] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def resolve_snapshot(self, project_id: str) -> ProjectContextSnapshot:
        _require_text(project_id, "project_id")
        revision = self._project_revisions[project_id]
        return ProjectContextSnapshot(
            project_id=project_id,
            pcm_revision=revision,
            knowledge_index_revision=revision,
        )

    async def find_commit_by_event(
        self,
        *,
        project_id: str,
        source_event_id: str,
    ) -> KnowledgeCommitResult | None:
        result = self._event_results.get((project_id, source_event_id))
        if result is None:
            return None
        return result.model_copy(update={"idempotent_replay": True})

    async def apply_knowledge_changes(
        self,
        *,
        project_id: str,
        change_set: KnowledgeChangeSet,
    ) -> KnowledgeCommitResult:
        _require_text(project_id, "project_id")
        event_key = (project_id, change_set.source_event_id)
        async with self._locks[project_id]:
            previous_result = self._event_results.get(event_key)
            if previous_result is not None:
                return previous_result.model_copy(update={"idempotent_replay": True})

            current_revision = self._project_revisions[project_id]
            if change_set.base_pcm_revision != current_revision:
                raise PCMRevisionConflict(
                    expected=change_set.base_pcm_revision,
                    actual=current_revision,
                )

            self._validate_changes(project_id, change_set.changes, current_revision)
            material_changes = tuple(
                change for change in change_set.changes if change.operation != "no_change"
            )
            target_revision = current_revision + 1 if material_changes else current_revision
            planned = self._plan_documents(project_id, material_changes, target_revision)

            for document, change in zip(planned, material_changes, strict=True):
                if change.operation == "create":
                    self._logical_ids[(project_id, document.logical_key)] = document.knowledge_id
            for document in planned:
                history = self._histories[(project_id, document.knowledge_id)]
                if history:
                    history[-1] = history[-1].model_copy(
                        update={"valid_until_pcm_revision": target_revision}
                    )
                history.append(document)

            if material_changes:
                self._project_revisions[project_id] = target_revision

            result = self._build_result(
                project_id=project_id,
                change_set=change_set,
                target_revision=target_revision,
                planned=planned,
            )
            self._event_results[event_key] = result
            return result

    async def search_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchPage:
        self._validate_snapshot(snapshot)
        query_tokens = _tokens(request.query)
        if not query_tokens:
            raise PCMValidationError("Knowledge search query must contain searchable text.")
        results: list[KnowledgeSearchResult] = []
        for (project_id, _), history in self._histories.items():
            if project_id != snapshot.project_id:
                continue
            document = _document_at_revision(history, snapshot.pcm_revision)
            if document is None or document.is_tombstone:
                continue
            if request.knowledge_types and document.knowledge_type not in request.knowledge_types:
                continue
            searchable = _tokens(f"{document.title}\n{document.body_markdown}")
            overlap = query_tokens & searchable
            if not overlap:
                continue
            score = len(overlap) / len(query_tokens)
            results.append(
                KnowledgeSearchResult(
                    knowledge_id=document.knowledge_id,
                    knowledge_revision=document.knowledge_revision,
                    knowledge_type=document.knowledge_type,
                    title=document.title,
                    matched_content=document.body_markdown[:1500],
                    score=score,
                    sources=document.sources,
                )
            )
        results.sort(key=lambda result: (-result.score, result.knowledge_id))
        return KnowledgeSearchPage(
            project_id=snapshot.project_id,
            pcm_revision=snapshot.pcm_revision,
            results=tuple(results[: request.limit]),
        )

    async def read_knowledge(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> KnowledgeDocument:
        self._validate_snapshot(snapshot)
        history = self._histories.get((snapshot.project_id, knowledge_id), [])
        document = _document_at_revision(history, snapshot.pcm_revision)
        if document is None or document.is_tombstone:
            raise KnowledgeNotFoundError(
                f"Knowledge {knowledge_id!r} is unavailable at PCM revision "
                f"{snapshot.pcm_revision}."
            )
        return document

    async def trace_knowledge_sources(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        knowledge_id: str,
    ) -> tuple[SourceReference, ...]:
        return (await self.read_knowledge(snapshot=snapshot, knowledge_id=knowledge_id)).sources

    def _validate_snapshot(self, snapshot: ProjectContextSnapshot) -> None:
        current = self._project_revisions[snapshot.project_id]
        if snapshot.pcm_revision > current:
            raise PCMValidationError(
                f"PCM revision {snapshot.pcm_revision} is newer than current revision {current}."
            )

    def _validate_changes(
        self,
        project_id: str,
        changes: tuple[KnowledgeChange, ...],
        current_revision: int,
    ) -> None:
        targets: set[str] = set()
        logical_keys: set[str] = set()
        for change in changes:
            target = change.target_knowledge_id
            if target and target in targets:
                raise PCMValidationError(f"Knowledge {target!r} changes more than once.")
            if target:
                targets.add(target)

            if change.operation == "create":
                assert change.logical_key is not None
                if (
                    project_id,
                    change.logical_key,
                ) in self._logical_ids or change.logical_key in logical_keys:
                    raise PCMValidationError(
                        f"Knowledge logical key {change.logical_key!r} already exists."
                    )
                logical_keys.add(change.logical_key)
                continue

            assert target is not None
            history = self._histories.get((project_id, target), [])
            document = _document_at_revision(history, current_revision)
            if document is None or document.is_tombstone:
                raise KnowledgeNotFoundError(f"Knowledge {target!r} is not active.")

    def _plan_documents(
        self,
        project_id: str,
        changes: tuple[KnowledgeChange, ...],
        target_revision: int,
    ) -> tuple[KnowledgeDocument, ...]:
        documents: list[KnowledgeDocument] = []
        for change in changes:
            if change.operation == "create":
                assert change.logical_key is not None
                knowledge_id = _knowledge_id(project_id, change.logical_key)
                knowledge_revision = 1
                logical_key = change.logical_key
            else:
                assert change.target_knowledge_id is not None
                knowledge_id = change.target_knowledge_id
                previous = self._histories[(project_id, knowledge_id)][-1]
                knowledge_revision = previous.knowledge_revision + 1
                logical_key = previous.logical_key

            previous = self._histories.get((project_id, knowledge_id), [])
            previous_document = previous[-1] if previous else None
            is_tombstone = change.operation == "tombstone"
            documents.append(
                KnowledgeDocument(
                    project_id=project_id,
                    knowledge_id=knowledge_id,
                    logical_key=logical_key,
                    knowledge_type=change.knowledge_type
                    or _require_previous(previous_document).knowledge_type,
                    title=change.title or _require_previous(previous_document).title,
                    body_markdown="" if is_tombstone else change.body_markdown or "",
                    knowledge_revision=knowledge_revision,
                    valid_from_pcm_revision=target_revision,
                    sources=change.sources,
                    related_knowledge_ids=change.related_knowledge_ids,
                    is_tombstone=is_tombstone,
                )
            )
        return tuple(documents)

    def _build_result(
        self,
        *,
        project_id: str,
        change_set: KnowledgeChangeSet,
        target_revision: int,
        planned: tuple[KnowledgeDocument, ...],
    ) -> KnowledgeCommitResult:
        created = tuple(
            document.knowledge_id
            for document, change in zip(planned, _material_changes(change_set), strict=True)
            if change.operation == "create"
        )
        updated = tuple(
            document.knowledge_id
            for document, change in zip(planned, _material_changes(change_set), strict=True)
            if change.operation == "update"
        )
        tombstoned = tuple(
            document.knowledge_id
            for document, change in zip(planned, _material_changes(change_set), strict=True)
            if change.operation == "tombstone"
        )
        unchanged = tuple(
            change.target_knowledge_id
            for change in change_set.changes
            if change.operation == "no_change" and change.target_knowledge_id
        )
        return KnowledgeCommitResult(
            commit_id=str(uuid4()),
            project_id=project_id,
            source_event_id=change_set.source_event_id,
            base_pcm_revision=change_set.base_pcm_revision,
            pcm_revision=target_revision,
            created_knowledge_ids=created,
            updated_knowledge_ids=updated,
            tombstoned_knowledge_ids=tombstoned,
            unchanged_knowledge_ids=unchanged,
        )


def _material_changes(change_set: KnowledgeChangeSet) -> tuple[KnowledgeChange, ...]:
    return tuple(change for change in change_set.changes if change.operation != "no_change")


def _document_at_revision(
    history: list[KnowledgeDocument],
    pcm_revision: int,
) -> KnowledgeDocument | None:
    for document in reversed(history):
        if document.valid_from_pcm_revision > pcm_revision:
            continue
        if (
            document.valid_until_pcm_revision is None
            or document.valid_until_pcm_revision > pcm_revision
        ):
            return document
    return None


def _knowledge_id(project_id: str, logical_key: str) -> str:
    return f"kn_{uuid5(NAMESPACE_URL, f'{project_id}:{logical_key}').hex}"


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(value)}


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise PCMValidationError(f"{name} must not be blank.")


def _require_previous(document: KnowledgeDocument | None) -> KnowledgeDocument:
    if document is None:
        raise PCMValidationError("An existing Knowledge revision is required.")
    return document
