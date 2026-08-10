import math

import pytest

from clio_agent_graph.workflows.reporting.retrieval.embedding_factory import (
    load_default_embedding_model,
)
from clio_agent_graph.workflows.reporting.retrieval.local_embedding import (
    LOCAL_HASH_DIMENSION,
    LOCAL_HASH_MODEL,
    LocalHashEmbeddingModel,
)


def test_local_hash_embedding_is_deterministic_and_normalized() -> None:
    model = LocalHashEmbeddingModel()

    first = model.embed("결제 완료 후 주문이 보이지 않는다")
    second = model.embed("결제 완료 후 주문이 보이지 않는다")

    assert first == second
    assert len(first) == LOCAL_HASH_DIMENSION
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)
    assert model.model_name == LOCAL_HASH_MODEL


def test_embedding_factory_requires_an_explicit_supported_local_model(monkeypatch) -> None:
    monkeypatch.setenv("CLIO_EMBEDDING_MODEL", LOCAL_HASH_MODEL)

    assert isinstance(load_default_embedding_model(), LocalHashEmbeddingModel)

    monkeypatch.setenv("CLIO_EMBEDDING_MODEL", "local:unknown")
    with pytest.raises(ValueError, match="Unsupported local embedding model"):
        load_default_embedding_model()
