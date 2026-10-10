import json

import pytest

from clio_agent_graph.context.pcm.embedding import (
    PCM_EMBEDDING_DIMENSIONS,
    QUERY_INSTRUCTION,
    OllamaEmbeddingProvider,
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


@pytest.mark.asyncio
async def test_ollama_embedding_uses_model_and_pcm_dimensions(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    def fake_urlopen(request, *, timeout):
        assert request.full_url == "http://ollama.test:11434/api/embed"
        assert timeout == 7
        payload = json.loads(request.data)
        requests.append(payload)
        vectors = [[0.0] * PCM_EMBEDDING_DIMENSIONS for _ in payload["input"]]
        return _FakeResponse(json.dumps({"embeddings": vectors}).encode())

    monkeypatch.setattr("clio_agent_graph.context.pcm.embedding.urlopen", fake_urlopen)
    monkeypatch.delenv("CLIO_OLLAMA_EMBED_CONTEXT_TOKENS", raising=False)
    provider = OllamaEmbeddingProvider(
        "qwen3-embedding:0.6b",
        base_url="http://ollama.test:11434/",
        timeout_seconds=7,
    )

    documents = await provider.embed_documents(["첫 문서", "둘째 문서"])
    query = await provider.embed_query("저장된 검색 수정 권한")

    assert provider.model_id == "ollama:qwen3-embedding:0.6b:384"
    assert provider.dimensions == PCM_EMBEDDING_DIMENSIONS
    assert len(documents) == 2
    assert len(query) == PCM_EMBEDDING_DIMENSIONS
    assert requests[0] == {
        "model": "qwen3-embedding:0.6b",
        "input": ["첫 문서", "둘째 문서"],
        "dimensions": PCM_EMBEDDING_DIMENSIONS,
        "truncate": True,
        "options": {"num_ctx": 1024},
    }
    assert requests[1]["input"] == [f"Instruct: {QUERY_INSTRUCTION}\nQuery: 저장된 검색 수정 권한"]


def test_ollama_embedding_requires_model_environment(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="OLLAMA_EMBEDDING_MODEL"):
        _ = OllamaEmbeddingProvider().model_id


@pytest.mark.parametrize("value", ["0", "large"])
def test_ollama_embedding_context_limit_must_be_a_positive_integer(monkeypatch, value) -> None:
    monkeypatch.setenv("CLIO_OLLAMA_EMBED_CONTEXT_TOKENS", value)

    with pytest.raises(ValueError, match="CLIO_OLLAMA_EMBED_CONTEXT_TOKENS"):
        OllamaEmbeddingProvider("qwen3-embedding:0.6b")
