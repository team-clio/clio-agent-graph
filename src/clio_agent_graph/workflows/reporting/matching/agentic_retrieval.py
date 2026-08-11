"""LLM이 제공된 검색 Tool을 선택하는 Issue Retrieval subgraph."""

import json
from collections.abc import Sequence
from typing import Any, Protocol, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from clio_agent_graph.runtime.agent_runtime import (
    AgentLimits,
    StructuredToolAgent,
    ToolCallRecord,
)
from clio_agent_graph.runtime.llm import build_chat_model
from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport

SYSTEM_PROMPT = """당신은 Report Matcher 앞에서 기존 Issue 후보를 조사하는 Retrieval Agent입니다.
제공된 검색 Tool 중 현재 Bug에 필요한 것을 직접 선택하세요.
결과가 부족하면 다른 Tool이나 질의로 보완하세요.
Tool이 반환한 Issue만 후보로 사용할 수 있으며 Issue ID나 검색 근거를 만들지 마세요.
같은 Issue는 한 번만 반환하고 retrieval_score 내림차순으로 최대 5개를 반환하세요.
충분히 조사했는데 후보가 없을 때만 빈 후보 목록을 반환하세요."""


class RetrievalAgent(Protocol):
    """실제 runtime과 테스트 Fake가 공유하는 최소 실행 계약."""

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        """가장 최근 후보 조사에서 실행한 Tool 호출 기록."""

        ...

    def invoke(self, user_prompt: str) -> IssueRetrievalResponse:
        """정규화된 Bug를 조사해 기존 Issue 후보를 반환한다."""

        ...


class AgenticRetrievalInput(TypedDict):
    """후보 검색 subgraph가 호출자에게 요구하는 입력."""

    project_id: int
    bug_id: int
    normalized_report: NormalizedReport


class AgenticRetrievalState(AgenticRetrievalInput, total=False):
    """검색 중 생성되는 후보와 감사용 Tool 기록을 포함한 내부 상태."""

    issue_candidates: list[IssueCandidate]
    retrieval_tool_calls: list[ToolCallRecord]


class AgenticRetrievalOutput(TypedDict):
    """Report Matcher로 전달하는 후보 검색 결과."""

    issue_candidates: list[IssueCandidate]
    retrieval_tool_calls: list[ToolCallRecord]


def build_agentic_issue_retrieval_graph(
    *,
    tools: Sequence[BaseTool] = (),
    agent: RetrievalAgent | None = None,
    agent_limits: AgentLimits | None = None,
):
    """검색 Tool 선택권을 LLM에 주는 bounded Retrieval graph를 만든다."""

    if agent is None and not tools:
        raise ValueError("Agentic issue retrieval requires at least one search tool.")
    actual_agent = agent

    def get_agent() -> RetrievalAgent:
        """provider model과 agent graph 생성을 첫 retrieval 실행까지 미룬다."""

        nonlocal actual_agent
        if actual_agent is None:
            actual_agent = StructuredToolAgent(
                model=build_chat_model(),
                tools=list(tools),
                system_prompt=SYSTEM_PROMPT,
                response_model=IssueRetrievalResponse,
                name="issue_retrieval_agent",
                limits=agent_limits or AgentLimits(max_tool_calls=12, max_model_calls=16),
            )
        return actual_agent

    def retrieve(state: AgenticRetrievalState) -> dict[str, Any]:
        """그래프 상태를 Agent 요청으로 바꾸고 검색 응답 계약을 검증한다."""

        request = IssueRetrievalRequest(
            project_id=state["project_id"],
            bug_id=state["bug_id"],
            normalized_report=NormalizedReport.model_validate(state["normalized_report"]),
        )
        retrieval_agent = get_agent()
        response = IssueRetrievalResponse.model_validate(
            retrieval_agent.invoke(
                "다음 Bug와 동일한 기존 Issue 후보를 조사하세요.\n"
                + json.dumps(request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            )
        )
        return {
            "issue_candidates": response.candidates,
            "retrieval_tool_calls": retrieval_agent.last_tool_calls,
        }

    builder = StateGraph(
        AgenticRetrievalState,
        input_schema=AgenticRetrievalInput,
        output_schema=AgenticRetrievalOutput,
    )
    builder.add_node("autonomous_issue_retrieval", retrieve)
    builder.add_edge(START, "autonomous_issue_retrieval")
    builder.add_edge("autonomous_issue_retrieval", END)
    return builder.compile()
