"""실제 코드 탐색 구현이 들어갈 Codebase Exploration subgraph."""

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.workflows.analysis.errors import (
    CodeExplorationError,
    CodeExplorerNotConfiguredError,
)
from clio_agent_graph.workflows.analysis.models import ExplorationRequest, ExplorationResponse

CodeExplorer = Callable[[ExplorationRequest], ExplorationResponse | dict[str, Any]]


class ExplorationInput(TypedDict):
    """공통 IA가 Code Explorer에 전달하는 state."""

    exploration_request: ExplorationRequest


class ExplorationState(ExplorationInput, total=False):
    """Code Explorer가 실행 중 읽고 쓰는 state."""

    exploration_response: ExplorationResponse


class ExplorationOutput(TypedDict):
    """Code Explorer가 공통 IA로 돌려주는 state."""

    exploration_response: ExplorationResponse


def build_code_exploration_subgraph(explorer: CodeExplorer | None = None):
    """코드 탐색 함수를 subgraph로 감싸며 생략하면 안전하게 실패한다."""

    def explore_codebase(state: ExplorationState) -> dict[str, Any]:
        """탐색 입출력을 검증하고 일시 실패에는 한 번 재시도한다."""

        if explorer is None:
            raise CodeExplorerNotConfiguredError("Codebase exploration subgraph is not configured.")

        request = ExplorationRequest.model_validate(state["exploration_request"])
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                response = ExplorationResponse.model_validate(explorer(request))
                return {"exploration_response": response}
            except CodeExplorerNotConfiguredError:
                raise
            except Exception as error:
                last_error = error

        raise CodeExplorationError("Codebase exploration failed after one retry.") from last_error

    builder = StateGraph(
        ExplorationState,
        input_schema=ExplorationInput,
        output_schema=ExplorationOutput,
    )
    builder.add_node("explore_codebase", explore_codebase)
    builder.add_edge(START, "explore_codebase")
    builder.add_edge("explore_codebase", END)
    return builder.compile()
