"""IA의 환경별 기본 Judgment 모델과 Code Explorer 선택."""

import os
from collections.abc import Sequence

from langchain_core.tools import BaseTool

from clio_agent_graph.analysis.errors import CodeExplorerNotConfiguredError
from clio_agent_graph.analysis.exploration_subgraph import CodeExplorer
from clio_agent_graph.analysis.ports import JudgmentModel


def load_default_initial_judgment_model(
    tools: Sequence[BaseTool] = (),
) -> JudgmentModel:
    """전역 LangChain 모델을 사용하는 최초 분석 adapter를 선택한다."""

    from clio_agent_graph.analysis.langchain_adapter import LangChainInitialJudgmentModel

    return LangChainInitialJudgmentModel(tools=tools)


def load_default_revision_judgment_model(
    tools: Sequence[BaseTool] = (),
) -> JudgmentModel:
    """전역 LangChain 모델을 사용하는 재분석 adapter를 선택한다."""

    from clio_agent_graph.analysis.langchain_adapter import LangChainRevisionJudgmentModel

    return LangChainRevisionJudgmentModel(tools=tools)


def load_default_code_explorer() -> CodeExplorer | None:
    """명시적으로 설정된 경우에만 실제 Code Explorer를 활성화한다."""

    value = os.getenv("CLIO_CODE_EXPLORER", "").strip().casefold()
    if not value or value in {"none", "disabled"}:
        return None
    if value in {"codex", "codex-exec", "subscription"}:
        from clio_agent_graph.analysis.codex_explorer import CodexCodeExplorer

        return CodexCodeExplorer()
    raise CodeExplorerNotConfiguredError(
        "CLIO_CODE_EXPLORER must be one of: codex, codex-exec, subscription, disabled."
    )
