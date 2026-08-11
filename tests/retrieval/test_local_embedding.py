import math

import pytest

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
