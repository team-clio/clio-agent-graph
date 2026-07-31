"""Agent Server에 공개하는 단일 색인·batch backfill LangGraph."""

import os
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.normalization.langchain_adapter import LangChainNormalizationModel
from clio_agent_graph.normalization.ports import NormalizationModel
from clio_agent_graph.normalization.service import (
    DEFAULT_MAX_RAW_PAYLOAD_BYTES,
    ReportNormalizer,
)
from clio_agent_graph.retrieval.indexing import BugBackfiller, BugIndexer
from clio_agent_graph.retrieval.langchain_embedding import LangChainEmbeddingModel
from clio_agent_graph.retrieval.models import (
    BackfillInput,
    BackfillResult,
    BugIndexInput,
    BugIndexResult,
)
from clio_agent_graph.retrieval.ports import BugIndexRepository, EmbeddingModel
from clio_agent_graph.retrieval.postgres import PostgresRetrievalRepository


class BugIndexGraphInput(TypedDict):
    """단일 Bug 색인 graph의 공개 입력."""

    project_id: int
    bug_id: int
    normalized_report: dict[str, Any]


class BugIndexGraphState(BugIndexGraphInput, total=False):
    """단일 Bug 색인 중 사용하는 내부 상태."""

    index_result: BugIndexResult


class BugIndexGraphOutput(TypedDict):
    """단일 Bug 색인 graph의 공개 출력."""

    index_result: BugIndexResult


class BackfillGraphInput(TypedDict, total=False):
    """과거 Bug batch 색인 graph의 공개 입력."""

    project_id: int
    after_bug_id: int | None
    batch_size: int


class BackfillGraphState(BackfillGraphInput, total=False):
    """Backfill graph가 실행 중 사용하는 상태."""

    backfill_result: BackfillResult


class BackfillGraphOutput(TypedDict):
    """Backfill graph의 공개 출력."""

    backfill_result: BackfillResult


def build_bug_retrieval_indexer_graph(
    *,
    repository: BugIndexRepository | None = None,
    embedding_model: EmbeddingModel | None = None,
):
    """운영 adapter나 Fake를 주입해 단일 Bug 색인 graph를 만든다."""

    actual_repository = repository if repository is not None else PostgresRetrievalRepository()
    actual_embedding_model = (
        embedding_model if embedding_model is not None else LangChainEmbeddingModel()
    )
    indexer = BugIndexer(actual_repository, actual_embedding_model)

    def index_bug(state: BugIndexGraphState) -> dict[str, Any]:
        """공개 JSON을 검증하고 index 결과를 반환한다."""

        request = BugIndexInput.model_validate(state)
        return {"index_result": indexer.index(request)}

    builder = StateGraph(
        BugIndexGraphState,
        input_schema=BugIndexGraphInput,
        output_schema=BugIndexGraphOutput,
    )
    builder.add_node("index_bug", index_bug)
    builder.add_edge(START, "index_bug")
    builder.add_edge("index_bug", END)
    return builder.compile()


def build_bug_retrieval_backfill_graph(
    *,
    repository: BugIndexRepository | None = None,
    embedding_model: EmbeddingModel | None = None,
    normalization_model: NormalizationModel | None = None,
    max_raw_payload_bytes: int | None = None,
):
    """기존 Bug를 작은 batch로 처리하는 backfill graph를 만든다."""

    actual_repository = repository if repository is not None else PostgresRetrievalRepository()
    actual_embedding_model = (
        embedding_model if embedding_model is not None else LangChainEmbeddingModel()
    )
    actual_normalization_model = (
        normalization_model if normalization_model is not None else LangChainNormalizationModel()
    )
    payload_limit = (
        max_raw_payload_bytes
        if max_raw_payload_bytes is not None
        else int(os.getenv("CLIO_MAX_RAW_PAYLOAD_BYTES", DEFAULT_MAX_RAW_PAYLOAD_BYTES))
    )
    indexer = BugIndexer(actual_repository, actual_embedding_model)
    backfiller = BugBackfiller(
        actual_repository,
        ReportNormalizer(actual_normalization_model, max_raw_payload_bytes=payload_limit),
        indexer,
    )

    def backfill_bugs(state: BackfillGraphState) -> dict[str, Any]:
        """생략된 cursor·batch 기본값을 Pydantic 계약에서 채운다."""

        request = BackfillInput.model_validate(state)
        return {"backfill_result": backfiller.backfill(request)}

    builder = StateGraph(
        BackfillGraphState,
        input_schema=BackfillGraphInput,
        output_schema=BackfillGraphOutput,
    )
    builder.add_node("backfill_bugs", backfill_bugs)
    builder.add_edge(START, "backfill_bugs")
    builder.add_edge("backfill_bugs", END)
    return builder.compile()


# 실제 provider와 DB 연결은 각 graph의 첫 invoke까지 생성되지 않는다.
bug_retrieval_indexer_graph = build_bug_retrieval_indexer_graph()
bug_retrieval_backfill_graph = build_bug_retrieval_backfill_graph()
