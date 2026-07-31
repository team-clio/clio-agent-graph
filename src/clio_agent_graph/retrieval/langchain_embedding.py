"""LangChain embedding provider를 Retrieval Protocol에 연결하는 adapter."""

import os
from typing import Any

from clio_agent_graph.retrieval.errors import RetrievalConfigurationError


class LangChainEmbeddingModel:
    """실제 embedding 객체를 최초 embed 호출 때 만드는 지연 adapter."""

    def __init__(self, model_name: str | None = None, *, timeout_seconds: float = 20.0) -> None:
        self._configured_model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._model: Any | None = None

    @property
    def model_name(self) -> str:
        """환경변수에도 모델이 없으면 가짜 기본값 대신 설정 오류를 낸다."""

        value = self._configured_model_name or os.getenv("CLIO_EMBEDDING_MODEL")
        if value is None or not value.strip():
            raise RetrievalConfigurationError("CLIO_EMBEDDING_MODEL is not configured.")
        return value.strip()

    def embed(self, text: str) -> list[float]:
        """문서 하나를 provider의 document embedding으로 변환한다."""

        model = self._get_model()
        return [float(value) for value in model.embed_documents([text])[0]]

    def _get_model(self) -> Any:
        """LangChain provider 객체는 API key가 필요할 수 있어 지연 생성한다."""

        if self._model is None:
            from langchain.embeddings import init_embeddings

            self._model = init_embeddings(
                self.model_name,
                request_timeout=self._timeout_seconds,
            )
        return self._model
