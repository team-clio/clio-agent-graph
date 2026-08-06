from clio_agent_graph.normalization.models import (
    NormalizationDraft,
    NormalizedReport,
    NormalizeReportInput,
)
from clio_agent_graph.retrieval.graph import (
    build_bug_retrieval_backfill_graph,
    build_bug_retrieval_indexer_graph,
)
from clio_agent_graph.retrieval.models import BugIndexResult, IndexStatus


class FakeEmbeddingModel:
    model_name = "fake:semantic"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, _text: str) -> list[float]:
        self.calls += 1
        return [0.1, 0.2, 0.3]


class FakeIndexRepository:
    def __init__(self) -> None:
        self.saved: dict[int, BugIndexResult] = {}
        self.save_calls = 0
        self.batch = [
            (
                72,
                NormalizeReportInput(
                    bug_report_id=351,
                    title="결제 실패",
                    description="결제 버튼을 누르면 오류가 발생한다.",
                ),
            ),
            (
                73,
                NormalizeReportInput(
                    bug_report_id=352,
                    title="주문 실패",
                    description="주문 생성이 실패한다.",
                ),
            ),
        ]

    def save_index(
        self,
        request,
        *,
        search_text,
        document_hash,
        embedding,
        embedding_model,
    ) -> BugIndexResult:
        self.save_calls += 1
        assert search_text
        assert embedding == [0.1, 0.2, 0.3]
        assert embedding_model == "fake:semantic"
        existing = self.saved.get(request.bug_id)
        if existing is not None and existing.document_hash == document_hash:
            return existing.model_copy(update={"status": IndexStatus.UNCHANGED})
        result = BugIndexResult(
            project_id=request.project_id,
            bug_id=request.bug_id,
            bug_report_id=request.normalized_report.bug_report_id,
            document_id=1000 + request.bug_id,
            document_version=1,
            document_hash=document_hash,
            embedding_model=embedding_model,
            embedding_dimension=len(embedding),
            status=IndexStatus.CREATED,
        )
        self.saved[request.bug_id] = result
        return result

    def load_backfill_batch(self, project_id, *, after_bug_id, limit):
        assert project_id == 3
        assert limit == 20
        rows = [item for item in self.batch if item[0] > after_bug_id]
        return rows[:limit], False


class FakeNormalizationModel:
    def extract(self, report_text: str, *, correction_feedback: str | None = None):
        assert correction_feedback is None
        if "주문 실패" in report_text:
            return NormalizationDraft(observed_behavior="주문 생성이 실패한다.")
        return NormalizationDraft(observed_behavior="결제 버튼 클릭 시 오류가 발생한다.")


def _normalized_report() -> NormalizedReport:
    return NormalizedReport(
        bug_report_id=351,
        observed_behavior="결제 버튼 클릭 시 오류가 발생한다.",
    )


def test_public_index_graph_is_idempotent_with_same_snapshot() -> None:
    repository = FakeIndexRepository()
    model = FakeEmbeddingModel()
    graph = build_bug_retrieval_indexer_graph(
        repository=repository,
        embedding_model=model,
    )
    graph_input = {
        "project_id": 3,
        "bug_id": 72,
        "normalized_report": _normalized_report().model_dump(mode="json"),
    }

    first = graph.invoke(graph_input)["index_result"]
    second = graph.invoke(graph_input)["index_result"]

    assert first.status is IndexStatus.CREATED
    assert second.status is IndexStatus.UNCHANGED
    assert first.document_hash == second.document_hash
    assert repository.save_calls == 2
    assert model.calls == 2


def test_indexer_prefers_document_specific_embedding() -> None:
    class DocumentAwareModel(FakeEmbeddingModel):
        def embed(self, _text: str) -> list[float]:
            raise AssertionError("generic embedding must not be used for a document")

        def embed_document(self, text: str) -> list[float]:
            assert "observed_behavior" in text
            return [0.1, 0.2, 0.3]

    result = build_bug_retrieval_indexer_graph(
        repository=FakeIndexRepository(),
        embedding_model=DocumentAwareModel(),
    ).invoke(
        {
            "project_id": 3,
            "bug_id": 72,
            "normalized_report": _normalized_report().model_dump(mode="json"),
        }
    )["index_result"]

    assert result.status is IndexStatus.CREATED


def test_backfill_graph_normalizes_batch_and_returns_cursor() -> None:
    repository = FakeIndexRepository()
    graph = build_bug_retrieval_backfill_graph(
        repository=repository,
        embedding_model=FakeEmbeddingModel(),
        normalization_model=FakeNormalizationModel(),
    )

    result = graph.invoke({"project_id": 3})["backfill_result"]

    assert result.processed_count == 2
    assert result.indexed_count == 2
    assert result.unchanged_count == 0
    assert result.failures == []
    assert result.next_after_bug_id == 73
    assert result.has_more is False


def test_backfill_keeps_data_failure_without_hiding_other_success() -> None:
    class PartlyInvalidModel(FakeNormalizationModel):
        def extract(self, report_text: str, *, correction_feedback: str | None = None):
            if "주문 실패" in report_text:
                raise ValueError("과거 payload를 정규화할 수 없음")
            return super().extract(report_text, correction_feedback=correction_feedback)

    repository = FakeIndexRepository()
    graph = build_bug_retrieval_backfill_graph(
        repository=repository,
        embedding_model=FakeEmbeddingModel(),
        normalization_model=PartlyInvalidModel(),
    )

    result = graph.invoke({"project_id": 3})["backfill_result"]

    assert result.processed_count == 2
    assert result.indexed_count == 1
    assert [failure.bug_id for failure in result.failures] == [73]
