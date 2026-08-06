"""LLM이 제공된 코드·PCM·이력 Tool을 선택하는 IA Exploration subgraph."""

import json
from collections.abc import Sequence
from typing import Any, Protocol, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from clio_agent_graph.agent_runtime import AgentLimits, StructuredToolAgent, ToolCallRecord
from clio_agent_graph.analysis.models import ExplorationRequest, ExplorationResponse
from clio_agent_graph.llm import build_chat_model

SYSTEM_PROMPT = """당신은 Issue Analyzer의 읽기 전용 Evidence Explorer입니다.
현재 질문에 답하기 위해 제공된 코드·프로젝트 지식·변경 이력 Tool 중 필요한 것을 직접 선택하세요.
검색 결과의 후보를 좁힌 뒤 원문을 읽어 확인하고, 실제 Tool observation에 존재하는 근거만 반환하세요.
code_snapshot은 확인한 원문 1~10줄이어야 하며 path·symbol·line·change metadata를 만들지 마세요.
추측은 Evidence로 반환하지 말고, 충분히 조사했는데 근거가 없을 때만 빈 결과를 반환하세요."""


class ExplorationAgent(Protocol):
    @property
    def last_tool_calls(self) -> list[ToolCallRecord]: ...

    def invoke(self, user_prompt: str) -> ExplorationResponse: ...


class AgenticExplorationInput(TypedDict):
    exploration_request: ExplorationRequest


class AgenticExplorationState(AgenticExplorationInput, total=False):
    exploration_response: ExplorationResponse
    exploration_tool_calls: list[ToolCallRecord]


class AgenticExplorationOutput(TypedDict):
    exploration_response: ExplorationResponse
    exploration_tool_calls: list[ToolCallRecord]


def build_agentic_code_exploration_graph(
    *,
    tools: Sequence[BaseTool] = (),
    agent: ExplorationAgent | None = None,
    agent_limits: AgentLimits | None = None,
):
    """IA 질문마다 LLM이 조사 Tool을 선택하는 bounded subgraph를 만든다."""

    if agent is None and not tools:
        raise ValueError("Agentic code exploration requires at least one tool.")
    actual_agent = agent

    def get_agent() -> ExplorationAgent:
        """provider model과 agent graph 생성을 첫 exploration 실행까지 미룬다."""

        nonlocal actual_agent
        if actual_agent is None:
            actual_agent = StructuredToolAgent(
                model=build_chat_model(),
                tools=list(tools),
                system_prompt=SYSTEM_PROMPT,
                response_model=ExplorationResponse,
                name="issue_evidence_explorer",
                limits=agent_limits or AgentLimits(max_tool_calls=20, max_model_calls=24),
            )
        return actual_agent

    def explore(state: AgenticExplorationState) -> dict[str, Any]:
        request = ExplorationRequest.model_validate(state["exploration_request"])
        exploration_agent = get_agent()
        response = ExplorationResponse.model_validate(
            exploration_agent.invoke(
                "다음 분석 질문의 근거를 조사하세요.\n"
                + json.dumps(request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            )
        )
        return {
            "exploration_response": response,
            "exploration_tool_calls": exploration_agent.last_tool_calls,
        }

    builder = StateGraph(
        AgenticExplorationState,
        input_schema=AgenticExplorationInput,
        output_schema=AgenticExplorationOutput,
    )
    builder.add_node("autonomous_evidence_exploration", explore)
    builder.add_edge(START, "autonomous_evidence_exploration")
    builder.add_edge("autonomous_evidence_exploration", END)
    return builder.compile()
