"""LangChain chat model을 RM 후보 비교 Protocol에 연결하는 adapter."""

from collections.abc import Sequence
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from clio_agent_graph.agent_runtime import (
    AgentLimits,
    StructuredAgentOutputError,
    StructuredToolAgent,
    ToolCallRecord,
)
from clio_agent_graph.llm import build_chat_model
from clio_agent_graph.matching.errors import IssueMatchOutputError
from clio_agent_graph.matching.models import IssueCandidate, MatchComparisonDraft
from clio_agent_graph.matching.prompts import SYSTEM_PROMPT, build_user_prompt
from clio_agent_graph.normalization.models import NormalizedReport


class LangChainIssueMatchModel:
    """LangChain structured output으로 후보별 비교 결과를 생성한다."""

    def __init__(
        self,
        *,
        tools: Sequence[BaseTool] = (),
        agent_limits: AgentLimits | None = None,
    ) -> None:
        # 실제 모델은 API key를 요구할 수 있으므로 첫 compare 호출까지 만들지 않는다.
        self._tools = list(tools)
        self._agent_limits = agent_limits
        self._chat_model: Any | None = None
        self._structured_model: Any | None = None
        self._tool_agent: StructuredToolAgent[MatchComparisonDraft] | None = None

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        """직전 후보 비교에서 LLM이 선택한 Tool 호출 기록."""

        if self._tool_agent is None:
            return []
        return self._tool_agent.last_tool_calls

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        """후보 전체를 한 번에 비교하고 검증 가능한 결과를 반환한다."""

        user_prompt = build_user_prompt(
            report,
            candidates,
            correction_feedback=correction_feedback,
        )
        try:
            if self._tools:
                result = self._get_tool_agent().invoke(user_prompt)
            else:
                result = self._get_structured_model().invoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ]
                )
            return MatchComparisonDraft.model_validate(result)
        except (OutputParserException, StructuredAgentOutputError, ValidationError) as error:
            # 인증·네트워크 같은 provider 오류는 서비스 계층이 동일 요청으로 재시도한다.
            raise IssueMatchOutputError(str(error)) from error

    def _get_structured_model(self) -> Any:
        """최초 비교 호출에서만 실제 chat model을 만든다."""

        if self._structured_model is None:
            self._structured_model = self._get_chat_model().with_structured_output(
                MatchComparisonDraft
            )
        return self._structured_model

    def _get_tool_agent(self) -> StructuredToolAgent[MatchComparisonDraft]:
        """후보 조사 Tool이 제공된 경우에만 자율 비교 agent를 지연 생성한다."""

        if self._tool_agent is None:
            self._tool_agent = StructuredToolAgent(
                model=self._get_chat_model(),
                tools=self._tools,
                system_prompt=SYSTEM_PROMPT,
                response_model=MatchComparisonDraft,
                name="report_matcher",
                limits=self._agent_limits or AgentLimits(max_tool_calls=10, max_model_calls=14),
            )
        return self._tool_agent

    def _get_chat_model(self) -> Any:
        """structured runnable과 Tool agent가 공유할 chat model을 지연 생성한다."""

        if self._chat_model is None:
            self._chat_model = build_chat_model()
        return self._chat_model
