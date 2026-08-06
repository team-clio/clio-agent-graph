"""LLM이 제공된 검색 Tool을 선택하는 Issue Retrieval subgraph."""

import json
import os
from collections.abc import Sequence
from typing import Any, Protocol, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from clio_agent_graph.agent_runtime import (
    AgentLimits,
    StructuredToolAgent,
    ToolCallRecord,
)
from clio_agent_graph.matching.models import (
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.normalization.models import NormalizedReport

DEFAULT_MODEL = "openai:gpt-4.1-mini"

SYSTEM_PROMPT = """당신은 Report Matcher 앞에서 기존 Issue 후보를 조사하는 Retrieval Agent입니다.
제공된 검색 Tool 중 현재 Bug에 필요한 것을 직접 선택하세요.
결과가 부족하면 다른 Tool이나 질의로 보완하세요.
Tool이 반환한 Issue만 후보로 사용할 수 있으며 Issue ID나 검색 근거를 만들지 마세요.
같은 Issue는 한 번만 반환하고 retrieval_score 내림차순으로 최대 5개를 반환하세요.
충분히 조사했는데 후보가 없을 때만 빈 후보 목록을 반환하세요."""


class RetrievalAgent(Protocol):
    """실제 runtime과 테스트 Fake가 공유하는 최소 실행 계약."""

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]: ...

    def invoke(self, user_prompt: str) -> IssueRetrievalResponse: ...


class AgenticRetrievalInput(TypedDict):
    project_id: int
    bug_id: int
    normalized_report: NormalizedReport


class AgenticRetrievalState(AgenticRetrievalInput, total=False):
    issue_candidates: list[IssueCandidate]
    retrieval_tool_calls: list[ToolCallRecord]


class AgenticRetrievalOutput(TypedDict):
    issue_candidates: list[IssueCandidate]
    retrieval_tool_calls: list[ToolCallRecord]


def build_agentic_issue_retrieval_graph(
    *,
    tools: Sequence[BaseTool] = (),
    model_name: str | None = None,
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
                model=init_chat_model(model_name or os.getenv("CLIO_MODEL", DEFAULT_MODEL)),
                tools=list(tools),
                system_prompt=SYSTEM_PROMPT,
                response_model=IssueRetrievalResponse,
                name="issue_retrieval_agent",
                limits=agent_limits or AgentLimits(max_tool_calls=12, max_model_calls=16),
            )
        return actual_agent

    def retrieve(state: AgenticRetrievalState) -> dict[str, Any]:
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
