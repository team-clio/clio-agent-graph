import pytest

from clio_agent_graph.workflows.reporting.retrieval.errors import RetrievalConfigurationError
from clio_agent_graph.workflows.reporting.retrieval.langchain_embedding import (
    LangChainEmbeddingModel,
)


def test_embedding_model_is_not_created_during_construction(monkeypatch) -> None:
    monkeypatch.delenv("CLIO_EMBEDDING_MODEL", raising=False)
    adapter = LangChainEmbeddingModel()

    assert adapter._model is None
    with pytest.raises(RetrievalConfigurationError):
        _ = adapter.model_name


def test_embedding_adapter_uses_configured_lazy_model() -> None:
    class FakeModel:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            assert texts == ["결제 오류"]
            return [[0.1, 0.2]]

        def embed_query(self, text: str) -> list[float]:
            assert text == "결제 검색"
            return [0.3, 0.4]

    adapter = LangChainEmbeddingModel("fake:model")
    adapter._model = FakeModel()

    assert adapter.model_name == "fake:model"
    assert adapter.embed("결제 오류") == [0.1, 0.2]
    assert adapter.embed_query("결제 검색") == [0.3, 0.4]
