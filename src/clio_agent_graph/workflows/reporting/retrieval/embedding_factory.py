"""환경 설정에 맞는 embedding adapter를 선택한다."""

import os

from clio_agent_graph.workflows.reporting.retrieval.ports import EmbeddingModel


def load_default_embedding_model() -> EmbeddingModel:
    """명시적 local 모델만 로컬 구현으로 보내고 나머지는 LangChain에 위임한다."""

    model_name = os.getenv("CLIO_EMBEDDING_MODEL", "").strip()
    if model_name.startswith("local:"):
        from clio_agent_graph.workflows.reporting.retrieval.local_embedding import (
            LocalHashEmbeddingModel,
        )

        return LocalHashEmbeddingModel(model_name)
    if model_name.startswith("ollama:"):
        from clio_agent_graph.workflows.reporting.retrieval.ollama_embedding import (
            OllamaEmbeddingModel,
        )

        return OllamaEmbeddingModel(model_name)
    from clio_agent_graph.workflows.reporting.retrieval.langchain_embedding import (
        LangChainEmbeddingModel,
    )

    return LangChainEmbeddingModel(model_name or None)
