"""실제 Hybrid RAG가 들어갈 Issue retrieval LangGraph subgraph."""

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.matching.errors import (
    IssueRetrievalError,
    IssueRetrievalNotConfiguredError,
)
from clio_agent_graph.matching.models import (
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.normalization.models import NormalizedReport

# Callable은 Java의 함수형 interface처럼 호출할 수 있는 객체의 입력과 출력을 표현한다.
IssueRetriever = Callable[[IssueRetrievalRequest], IssueRetrievalResponse | dict[str, Any]]


class IssueRetrievalInput(TypedDict):
    """상위 RM 그래프에서 retrieval subgraph로 들어오는 상태."""

    project_id: int
    bug_id: int
    normalized_report: NormalizedReport


class IssueRetrievalState(IssueRetrievalInput, total=False):
    """RAG 하위 에이전트가 실행 중 읽고 쓰는 상태."""

    issue_candidates: list[IssueCandidate]


class IssueRetrievalOutput(TypedDict):
    """RAG 하위 에이전트가 상위 RM 그래프에 돌려주는 상태."""

    issue_candidates: list[IssueCandidate]


def build_issue_retrieval_subgraph(retriever: IssueRetriever | None = None):
    """검색 함수를 LangGraph subgraph로 감싸며, 생략하면 안전하게 실패한다."""

    def retrieve_issue_candidates(state: IssueRetrievalState) -> dict[str, Any]:
        """입출력을 검증하고 일시 실패에는 한 번만 재시도한다."""

        if retriever is None:
            raise IssueRetrievalNotConfiguredError("Issue retrieval subgraph is not configured.")

        request = IssueRetrievalRequest.model_validate(
            {
                "project_id": state["project_id"],
                "bug_id": state["bug_id"],
                "normalized_report": state["normalized_report"],
            }
        )
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                response = IssueRetrievalResponse.model_validate(retriever(request))
                return {"issue_candidates": response.candidates}
            except Exception as error:
                # 설정 오류는 일시 장애가 아니므로 같은 호출을 반복하지 않는다.
                if isinstance(error, IssueRetrievalNotConfiguredError):
                    raise
                last_error = error

        raise IssueRetrievalError("Issue retrieval failed after one retry.") from last_error

    builder = StateGraph(
        IssueRetrievalState,
        input_schema=IssueRetrievalInput,
        output_schema=IssueRetrievalOutput,
    )
    builder.add_node("retrieve_issue_candidates", retrieve_issue_candidates)
    builder.add_edge(START, "retrieve_issue_candidates")
    builder.add_edge("retrieve_issue_candidates", END)
    return builder.compile()
