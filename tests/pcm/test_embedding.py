import math

import pytest

from clio_agent_graph.context.pcm.embedding import DeterministicLocalEmbedding


@pytest.mark.asyncio
async def test_local_embedding_is_deterministic_and_normalized() -> None:
    provider = DeterministicLocalEmbedding(dimensions=64)

    document, duplicate = await provider.embed_documents(
        ["saved search owner permission", "saved search owner permission"]
    )

    assert document == duplicate
    assert len(document) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in document)), 1.0)
    assert provider.model_id == "local-feature-hash-v1-64"


@pytest.mark.asyncio
async def test_local_embedding_requires_no_network_for_query() -> None:
    vector = await DeterministicLocalEmbedding().embed_query("저장된 검색 수정 권한")

    assert len(vector) == 384
    assert any(vector)
