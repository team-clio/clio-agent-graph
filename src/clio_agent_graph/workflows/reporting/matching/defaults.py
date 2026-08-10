"""RM의 환경별 기본 모델 선택."""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from clio_agent_graph.workflows.reporting.matching.ports import IssueMatchModel


def load_default_issue_match_model(
    tools: Sequence[BaseTool] = (),
) -> IssueMatchModel:
    """전역 LangChain 모델을 사용하는 RM adapter를 지연 import한다."""

    from clio_agent_graph.workflows.reporting.matching.langchain_adapter import (
        LangChainIssueMatchModel,
    )

    return LangChainIssueMatchModel(tools=tools)
