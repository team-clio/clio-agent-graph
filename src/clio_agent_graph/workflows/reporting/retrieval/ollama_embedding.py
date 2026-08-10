"""로컬 Ollama의 embedding API를 Retrieval Protocol에 연결한다."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from clio_agent_graph.workflows.reporting.retrieval.errors import (
    RetrievalConfigurationError,
    RetrievalDataError,
)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
QUERY_INSTRUCTION = (
    "Given a software bug report, retrieve previous bug reports caused by the same "
    "underlying issue. Consider observed behavior, affected feature, error codes, "
    "error messages, and stack frames."
)


class OllamaEmbeddingModel:
    """Ollama에서 query와 document를 구분해 의미 embedding을 생성한다."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        configured_name = model_name or os.getenv("CLIO_EMBEDDING_MODEL", "")
        if configured_name.startswith("ollama:"):
            configured_name = configured_name.removeprefix("ollama:")
        self._ollama_model = configured_name.strip()
        if not self._ollama_model:
            raise RetrievalConfigurationError("Ollama embedding model is not configured.")

        configured_url = base_url or os.getenv("CLIO_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        self._base_url = configured_url.strip().rstrip("/")
        parsed_url = urlparse(self._base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise RetrievalConfigurationError("CLIO_OLLAMA_BASE_URL must be an HTTP URL.")

        configured_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(
                os.getenv(
                    "CLIO_OLLAMA_TIMEOUT_SECONDS",
                    str(DEFAULT_OLLAMA_TIMEOUT_SECONDS),
                )
            )
        )
        if configured_timeout <= 0:
            raise RetrievalConfigurationError(
                "CLIO_OLLAMA_TIMEOUT_SECONDS must be greater than zero."
            )
        self._timeout_seconds = configured_timeout

    @property
    def model_name(self) -> str:
        """DB에서 다른 provider·tag와 섞이지 않는 모델 ID를 반환한다."""

        return f"ollama:{self._ollama_model}"

    def embed(self, text: str) -> list[float]:
        """기존 EmbeddingModel 호출과 호환되는 document embedding이다."""

        return self.embed_document(text)

    def embed_document(self, text: str) -> list[float]:
        """색인할 Bug 문서는 instruction 없이 embedding한다."""

        return self._request_embedding(text)

    def embed_query(self, text: str) -> list[float]:
        """Qwen3 권장 형식으로 같은 원인의 과거 Bug 검색 목적을 명시한다."""

        instructed_query = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        return self._request_embedding(instructed_query)

    def _request_embedding(self, text: str) -> list[float]:
        """Ollama `/api/embed` 응답을 크기 제한 후 검증한다."""

        request = Request(
            f"{self._base_url}/api/embed",
            data=json.dumps(
                {"model": self._ollama_model, "input": text},
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
            raise RetrievalDataError("Ollama embed response exceeded 16 MiB.")
        try:
            payload = json.loads(raw_response)
            embeddings = payload["embeddings"]
            vector = embeddings[0]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise RetrievalDataError("Ollama embed response has an invalid shape.") from error
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise RetrievalDataError("Ollama embed must return exactly one vector.")
        if not isinstance(vector, list) or not vector:
            raise RetrievalDataError("Ollama embed returned an empty vector.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise RetrievalDataError("Ollama embedding contains a non-numeric value.")
        return [float(value) for value in vector]
