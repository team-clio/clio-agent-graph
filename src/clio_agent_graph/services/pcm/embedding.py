"""외부 Embedding API를 연결하기 전 사용할 로컬 개발 provider."""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[\w./:{}-]+", re.UNICODE)


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class DeterministicLocalEmbedding:
    """Feature hashing으로 배선만 검증하는 네트워크 없는 임시 embedding."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 32:
            raise ValueError("Local embedding dimensions must be at least 32.")
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return f"local-feature-hash-v1-{self.dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        features = _features(text)
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest)
            index = value % self.dimensions
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def _features(text: str) -> tuple[str, ...]:
    tokens = tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))
    if not tokens:
        return ()
    bigrams = tuple(f"{left}\x1f{right}" for left, right in zip(tokens, tokens[1:], strict=False))
    return (*tokens, *bigrams)
