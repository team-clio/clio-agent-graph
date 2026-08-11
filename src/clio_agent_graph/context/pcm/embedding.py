"""PCM semantic search에 사용하는 Ollama embedding provider."""

import asyncio
import json
import math
import os
from collections.abc import Sequence
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0
PCM_EMBEDDING_DIMENSIONS = 384
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
QUERY_INSTRUCTION = (
    "Given a project knowledge query, retrieve the most relevant project knowledge chunks. "
    "Consider requirements, domain rules, architecture decisions, and source code context."
)


class EmbeddingProvider(Protocol):
    """검색 인덱스가 구현체와 무관하게 사용하는 embedding 계약."""

    @property
    def model_id(self) -> str:
        """동일한 벡터 공간인지 식별하는 provider·model ID."""

        ...

    @property
    def dimensions(self) -> int:
        """저장소 vector column과 일치해야 하는 출력 차원."""

        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """색인할 여러 문서를 같은 벡터 공간으로 변환한다."""

        ...

    async def embed_query(self, text: str) -> list[float]:
        """검색어 하나를 문서와 같은 벡터 공간으로 변환한다."""

        ...


class OllamaEmbeddingProvider:
    """Qwen3 embedding을 PCM의 384차원 pgvector schema에 연결한다."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        dimensions: int = PCM_EMBEDDING_DIMENSIONS,
    ) -> None:
        configured_model_name = (
            model_name if model_name is not None else os.getenv("OLLAMA_EMBEDDING_MODEL", "")
        )
        self._model_name = configured_model_name.strip()
        if dimensions != PCM_EMBEDDING_DIMENSIONS:
            raise ValueError("The current PCM pgvector schema requires 384 dimensions.")
        self._dimensions = dimensions

        self._base_url = (
            (base_url or os.getenv("CLIO_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))
            .strip()
            .rstrip("/")
        )
        parsed_url = urlparse(self._base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("CLIO_OLLAMA_BASE_URL must be an HTTP URL.")

        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(
                os.getenv(
                    "CLIO_OLLAMA_TIMEOUT_SECONDS",
                    str(DEFAULT_OLLAMA_TIMEOUT_SECONDS),
                )
            )
        )
        if self._timeout_seconds <= 0:
            raise ValueError("CLIO_OLLAMA_TIMEOUT_SECONDS must be greater than zero.")

    @property
    def model_id(self) -> str:
        """알고리즘 버전과 차원을 함께 노출해 잘못된 인덱스 재사용을 막는다."""

        return f"ollama:{self._require_model_name()}:{self.dimensions}"


    @property
    def dimensions(self) -> int:
        """생성되는 feature-hash vector의 고정 차원."""

        return self._dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """네트워크 호출 없이 각 문서를 결정적인 단위 벡터로 변환한다."""

        inputs = list(texts)
        if not inputs:
            return []
        return await asyncio.to_thread(self._request_embeddings, inputs)


    async def embed_query(self, text: str) -> list[float]:
        """문서와 동일한 feature hashing 규칙으로 검색어를 변환한다."""

        instructed_query = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        embeddings = await asyncio.to_thread(self._request_embeddings, [instructed_query])
        return embeddings[0]


    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        request = Request(
            f"{self._base_url}/api/embed",
            data=json.dumps(
                {
                    "model": self._require_model_name(),
                    "input": texts,
                    "dimensions": self.dimensions,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw_response = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            diagnostic = error.read(2_000).decode("utf-8", errors="replace").strip()
            suffix = f": {diagnostic}" if diagnostic else ""
            raise RuntimeError(f"Ollama embed returned HTTP {error.code}{suffix}") from error
        except URLError as error:
            raise RuntimeError(f"Ollama embed is unavailable at {self._base_url}.") from error

        if len(raw_response) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ollama embed response exceeded 16 MiB.")
        try:
            payload = json.loads(raw_response)
            embeddings = payload["embeddings"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError("Ollama embed response has an invalid shape.") from error
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama embed response count does not match the input count.")

        vectors: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise RuntimeError(
                    f"Ollama embed must return {self.dimensions}-dimensional vectors."
                )
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            ):
                raise RuntimeError("Ollama embedding contains an invalid value.")
            vectors.append([float(value) for value in vector])
        return vectors

    def _require_model_name(self) -> str:
        if not self._model_name:
            raise ValueError("OLLAMA_EMBEDDING_MODEL is not configured.")
        return self._model_name
