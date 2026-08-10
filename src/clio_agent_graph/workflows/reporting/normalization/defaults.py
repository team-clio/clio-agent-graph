"""NM의 환경별 기본 모델 선택."""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from clio_agent_graph.workflows.reporting.normalization.ports import NormalizationModel


def load_default_normalization_model(
    tools: Sequence[BaseTool] = (),
) -> NormalizationModel:
    """전역 LangChain 모델을 사용하는 NM adapter를 지연 import한다."""

    from clio_agent_graph.workflows.reporting.normalization.langchain_adapter import (
        LangChainNormalizationModel,
    )

    return LangChainNormalizationModel(tools=tools)
