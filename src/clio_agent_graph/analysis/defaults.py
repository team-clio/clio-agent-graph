"""IA의 환경별 기본 Judgment 모델과 Code Explorer 선택."""

import os

from clio_agent_graph.analysis.errors import CodeExplorerNotConfiguredError
from clio_agent_graph.analysis.exploration_subgraph import CodeExplorer
from clio_agent_graph.analysis.ports import JudgmentModel
from clio_agent_graph.configuration import load_chat_backend


def load_default_initial_judgment_model() -> JudgmentModel:
    """최초 분석용 기본 adapter를 선택한다."""

    if load_chat_backend() == "codex":
        from clio_agent_graph.analysis.codex_adapter import CodexInitialJudgmentModel

        return CodexInitialJudgmentModel()
    from clio_agent_graph.analysis.langchain_adapter import LangChainInitialJudgmentModel

    return LangChainInitialJudgmentModel()


def load_default_revision_judgment_model() -> JudgmentModel:
    """재분석용 기본 adapter를 선택한다."""

    if load_chat_backend() == "codex":
        from clio_agent_graph.analysis.codex_adapter import CodexRevisionJudgmentModel

        return CodexRevisionJudgmentModel()
    from clio_agent_graph.analysis.langchain_adapter import LangChainRevisionJudgmentModel

    return LangChainRevisionJudgmentModel()


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
