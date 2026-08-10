import json

import pytest

from clio_agent_graph.workflows.reporting.retrieval.embedding_factory import (
    load_default_embedding_model,
)
from clio_agent_graph.workflows.reporting.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
)
from clio_agent_graph.workflows.reporting.retrieval.ollama_embedding import (
    QUERY_INSTRUCTION,
    OllamaEmbeddingModel,
)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._payload


def test_ollama_adapter_separates_document_and_instructed_query(monkeypatch) -> None:
    inputs: list[str] = []

    def fake_urlopen(request, *, timeout):
        assert request.full_url == "http://ollama.test:11434/api/embed"
        assert timeout == 7
        payload = json.loads(request.data)
        assert payload["model"] == "qwen3-embedding:0.6b"
        inputs.append(payload["input"])
        return _FakeResponse(b'{"embeddings": [[0.1, 0.2, 0.3]]}')

    monkeypatch.setattr(
        "clio_agent_graph.workflows.reporting.retrieval.ollama_embedding.urlopen",
        fake_urlopen,
    )
    model = OllamaEmbeddingModel(
        "ollama:qwen3-embedding:0.6b",
        base_url="http://ollama.test:11434/",
        timeout_seconds=7,
    )

    document = model.embed_document("PaymentException PAY-500")
    query = model.embed_query("같은 결제 오류를 찾아라")

    assert model.model_name == "ollama:qwen3-embedding:0.6b"
    assert document == [0.1, 0.2, 0.3]
    assert query == [0.1, 0.2, 0.3]
    assert inputs[0] == "PaymentException PAY-500"
    assert inputs[1] == (f"Instruct: {QUERY_INSTRUCTION}\nQuery: 같은 결제 오류를 찾아라")


def test_ollama_adapter_rejects_invalid_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "clio_agent_graph.workflows.reporting.retrieval.ollama_embedding.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b'{"embeddings": []}'),
    )

    with pytest.raises(RetrievalDataError, match="invalid shape"):
        OllamaEmbeddingModel("qwen3-embedding:0.6b").embed_document("bug")


def test_ollama_configuration_and_factory(monkeypatch) -> None:
    with pytest.raises(RetrievalConfigurationError):
        OllamaEmbeddingModel("")

    monkeypatch.setenv("CLIO_EMBEDDING_MODEL", "ollama:qwen3-embedding:0.6b")
    model = load_default_embedding_model()

    assert isinstance(model, OllamaEmbeddingModel)
    assert model.model_name == "ollama:qwen3-embedding:0.6b"
