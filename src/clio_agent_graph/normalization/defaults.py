"""NM의 환경별 기본 모델 선택."""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from clio_agent_graph.configuration import ModelBackendConfigurationError, load_chat_backend
from clio_agent_graph.normalization.ports import NormalizationModel


def load_default_normalization_model(
    tools: Sequence[BaseTool] = (),
) -> NormalizationModel:
    """명시적 backend 설정에 맞는 NM adapter를 지연 import한다."""

    if load_chat_backend() == "codex":
        if tools:
            raise ModelBackendConfigurationError(
                "Injected LangChain tools are not supported by the codex NM backend."
            )
        from clio_agent_graph.normalization.codex_adapter import CodexNormalizationModel

        return CodexNormalizationModel()
    from clio_agent_graph.normalization.langchain_adapter import LangChainNormalizationModel

    return LangChainNormalizationModel(tools=tools)
