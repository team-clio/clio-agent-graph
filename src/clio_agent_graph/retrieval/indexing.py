"""단일 Bug snapshot 색인과 기존 Bug backfill 업무 서비스."""

from collections.abc import Callable
from typing import TypeVar

from clio_agent_graph.normalization.service import (
    ReportNormalizer,
    ReportPayloadTooLargeError,
)
from clio_agent_graph.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
    RetrievalOperationError,
)
from clio_agent_graph.retrieval.models import (
    BackfillFailure,
    BackfillInput,
    BackfillResult,
    BugIndexInput,
    BugIndexResult,
    IndexStatus,
)
from clio_agent_graph.retrieval.ports import BugIndexRepository, EmbeddingModel
from clio_agent_graph.retrieval.query import build_search_text, calculate_document_hash
from clio_agent_graph.retrieval.service import _validate_embedding

T = TypeVar("T")


class BugIndexer:
    """NM snapshot의 검색 문서와 embedding을 멱등하게 저장한다."""

    def __init__(self, repository: BugIndexRepository, embedding_model: EmbeddingModel) -> None:
        self._repository = repository
        self._embedding_model = embedding_model

    def index(self, request: BugIndexInput) -> BugIndexResult:
        """외부 호출을 각각 한 번 재시도한 뒤 DB transaction에 저장한다."""

        search_text = build_search_text(request.normalized_report)
        document_hash = calculate_document_hash(request.normalized_report, search_text)
        model_name = self._embedding_model.model_name
        embedding = _retry_index_operation(lambda: self._embedding_model.embed(search_text))
        _validate_embedding(embedding)
        return _retry_index_operation(
            lambda: self._repository.save_index(
                request,
                search_text=search_text,
                document_hash=document_hash,
                embedding=embedding,
                embedding_model=model_name,
            )
        )


class BugBackfiller:
    """과거 Bug를 cursor batch로 NM 재정규화하고 같은 indexer로 저장한다."""

    def __init__(
        self,
        repository: BugIndexRepository,
        normalizer: ReportNormalizer,
        indexer: BugIndexer,
    ) -> None:
        self._repository = repository
        self._normalizer = normalizer
        self._indexer = indexer

    def backfill(self, request: BackfillInput) -> BackfillResult:
        """데이터별 실패는 기록하고 DB·provider 기술 실패는 숨기지 않는다."""

        batch, has_more = _retry_index_operation(
            lambda: self._repository.load_backfill_batch(
                request.project_id,
                after_bug_id=request.after_bug_id or 0,
                limit=request.batch_size,
            )
        )
        indexed_count = 0
        unchanged_count = 0
        failures: list[BackfillFailure] = []
        next_after_bug_id: int | None = request.after_bug_id
        for bug_id, report in batch:
            next_after_bug_id = bug_id
            try:
                normalized = self._normalizer.normalize(report)
                result = self._indexer.index(
                    BugIndexInput(
                        project_id=request.project_id,
                        bug_id=bug_id,
                        normalized_report=normalized,
                    )
                )
            except (ReportPayloadTooLargeError, RetrievalDataError, ValueError) as error:
                failures.append(BackfillFailure(bug_id=bug_id, reason=str(error)[:2_000]))
                continue
            if result.status is IndexStatus.CREATED:
                indexed_count += 1
            else:
                unchanged_count += 1

        return BackfillResult(
            project_id=request.project_id,
            processed_count=len(batch),
            indexed_count=indexed_count,
            unchanged_count=unchanged_count,
            failures=failures,
            next_after_bug_id=next_after_bug_id,
            has_more=has_more,
        )


def _retry_index_operation(operation: Callable[[], T]) -> T:
    """색인 외부 operation을 한 번 재시도하되 영구 오류는 즉시 전달한다."""

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            return operation()
        except (RetrievalConfigurationError, RetrievalDataError):
            raise
        except Exception as error:
            last_error = error
    raise RetrievalOperationError("Index operation failed after one retry.") from last_error
