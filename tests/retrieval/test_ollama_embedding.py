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
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
    model = load_default_embedding_model()

    assert isinstance(model, OllamaEmbeddingModel)
    assert model.model_name == "ollama:qwen3-embedding:0.6b"


def test_ollama_factory_requires_model_environment(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)

    with pytest.raises(RetrievalConfigurationError, match="OLLAMA_EMBEDDING_MODEL"):
        _ = load_default_embedding_model().model_name


def test_ollama_adapter_caps_embedding_context_to_bound_memory(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_urlopen(request, *, timeout):
        payloads.append(json.loads(request.data))
        return _FakeResponse(b'{"embeddings": [[0.1]]}')

    monkeypatch.setattr(
        "clio_agent_graph.workflows.reporting.retrieval.ollama_embedding.urlopen",
        fake_urlopen,
    )
    monkeypatch.delenv("CLIO_OLLAMA_EMBED_CONTEXT_TOKENS", raising=False)
    OllamaEmbeddingModel("qwen3-embedding:0.6b").embed_document("bug")
    monkeypatch.setenv("CLIO_OLLAMA_EMBED_CONTEXT_TOKENS", "512")
    OllamaEmbeddingModel("qwen3-embedding:0.6b").embed_query("bug")

    assert [p["options"]["num_ctx"] for p in payloads] == [1024, 512]
    assert all(p["truncate"] is True for p in payloads)


@pytest.mark.parametrize("value", ["0", "-1", "large"])
def test_ollama_context_limit_must_be_a_positive_integer(monkeypatch, value) -> None:
    monkeypatch.setenv("CLIO_OLLAMA_EMBED_CONTEXT_TOKENS", value)

    with pytest.raises(RetrievalConfigurationError, match="CLIO_OLLAMA_EMBED_CONTEXT_TOKENS"):
        OllamaEmbeddingModel("qwen3-embedding:0.6b")
