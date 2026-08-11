"""기본 Ollama embedding adapter를 생성한다."""

from clio_agent_graph.workflows.reporting.retrieval.ports import EmbeddingModel


def load_default_embedding_model() -> EmbeddingModel:
    """`OLLAMA_EMBEDDING_MODEL`을 사용하는 기본 adapter를 지연 생성한다."""

    from clio_agent_graph.workflows.reporting.retrieval.ollama_embedding import (
        OllamaEmbeddingModel,
    )

    return OllamaEmbeddingModel()
