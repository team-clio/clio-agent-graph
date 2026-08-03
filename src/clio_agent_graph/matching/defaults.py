"""RM의 환경별 기본 모델 선택."""

from clio_agent_graph.configuration import load_chat_backend
from clio_agent_graph.matching.ports import IssueMatchModel


def load_default_issue_match_model() -> IssueMatchModel:
    """명시적 backend 설정에 맞는 RM adapter를 지연 import한다."""

    if load_chat_backend() == "codex":
        from clio_agent_graph.matching.codex_adapter import CodexIssueMatchModel

        return CodexIssueMatchModel()
    from clio_agent_graph.matching.langchain_adapter import LangChainIssueMatchModel

    return LangChainIssueMatchModel()
