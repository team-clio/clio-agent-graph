"""LangChain chat model을 NM 전용 Protocol에 연결하는 adapter."""

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
from clio_agent_graph.normalization.models import NormalizationDraft
from clio_agent_graph.normalization.ports import NormalizationOutputError
from clio_agent_graph.normalization.prompts import SYSTEM_PROMPT, build_user_prompt
from clio_agent_graph.structured_output import bind_structured_output


class LangChainNormalizationModel:
    """LangChain structured output을 사용해 NormalizationDraft를 생성한다."""

    def __init__(
        self,
        *,
        tools: Sequence[BaseTool] = (),
        agent_limits: AgentLimits | None = None,
    ) -> None:
        # 모델 객체는 네트워크 설정이나 API key를 요구할 수 있어 첫 호출까지 만들지 않는다.
        self._tools = list(tools)
        self._agent_limits = agent_limits
        self._chat_model: Any | None = None
        self._structured_model: Any | None = None
        self._tool_agent: StructuredToolAgent[NormalizationDraft] | None = None

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        """직전 정규화에서 LLM이 선택한 Tool 호출 기록."""

        if self._tool_agent is None:
            return []
        return self._tool_agent.last_tool_calls

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        """모델을 지연 생성하고 검증 가능한 NM 초안을 반환한다."""

        user_prompt = build_user_prompt(
            report_text,
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
            return NormalizationDraft.model_validate(result)
        except (OutputParserException, StructuredAgentOutputError, ValidationError) as error:
            # provider 연결 실패 같은 예외는 잡지 않는다. 구조화 결과 오류만 교정 대상이다.
            raise NormalizationOutputError(str(error)) from error

    def _get_structured_model(self) -> Any:
        """최초 호출에서만 실제 chat model과 structured output runnable을 만든다."""

        if self._structured_model is None:
            self._structured_model = bind_structured_output(
                self._get_chat_model(), NormalizationDraft
            )
        return self._structured_model

    def _get_tool_agent(self) -> StructuredToolAgent[NormalizationDraft]:
        """Tool이 제공된 경우에만 자율 정규화 agent를 지연 생성한다."""

        if self._tool_agent is None:
            self._tool_agent = StructuredToolAgent(
                model=self._get_chat_model(),
                tools=self._tools,
                system_prompt=SYSTEM_PROMPT,
                response_model=NormalizationDraft,
                name="report_normalizer",
                limits=self._agent_limits or AgentLimits(max_tool_calls=6, max_model_calls=10),
            )
        return self._tool_agent

    def _get_chat_model(self) -> Any:
        """Tool agent와 structured runnable이 공유할 실제 chat model을 만든다."""

        if self._chat_model is None:
            self._chat_model = build_chat_model()
        return self._chat_model
