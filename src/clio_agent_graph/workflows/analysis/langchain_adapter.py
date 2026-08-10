"""LangChain 모델을 Initial·Revision Judgment Protocol에 연결하는 adapter."""

from collections.abc import Sequence
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from clio_agent_graph.runtime.agent_runtime import (
    AgentLimits,
    StructuredAgentOutputError,
    StructuredToolAgent,
    ToolCallRecord,
)
from clio_agent_graph.runtime.llm import build_chat_model
from clio_agent_graph.runtime.structured_output import bind_structured_output
from clio_agent_graph.workflows.analysis.errors import JudgmentOutputError
from clio_agent_graph.workflows.analysis.models import (
    AnalysisDraft,
    CodeRelation,
    Evidence,
    ExplorationDirective,
    JudgmentContext,
)
from clio_agent_graph.workflows.analysis.prompts import (
    INITIAL_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
    build_analysis_prompt,
    build_plan_prompt,
)


class _LangChainJudgmentModel:
    """두 Judgment adapter가 공유하는 지연 생성·structured output 구현."""

    def __init__(
        self,
        system_prompt: str,
        *,
        tools: Sequence[BaseTool] = (),
        agent_limits: AgentLimits | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._tools = list(tools)
        self._agent_limits = agent_limits
        self._chat_model: Any | None = None
        self._plan_model: Any | None = None
        self._analysis_model: Any | None = None
        self._plan_agent: StructuredToolAgent[ExplorationDirective] | None = None
        self._analysis_agent: StructuredToolAgent[AnalysisDraft] | None = None
        self._last_tool_calls: list[ToolCallRecord] = []

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        """직전 plan 또는 analyze에서 LLM이 선택한 Tool 호출 기록."""

        return [dict(item) for item in self._last_tool_calls]

    def plan(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        asked_questions: list[str],
        *,
        correction_feedback: str | None = None,
    ) -> ExplorationDirective:
        """현재 분석 상태에 맞는 다음 탐색 질문을 structured output으로 만든다."""

        user_prompt = build_plan_prompt(
            context,
            evidence,
            asked_questions,
            correction_feedback=correction_feedback,
        )
        try:
            if self._tools:
                agent = self._get_plan_agent()
                result = agent.invoke(user_prompt)
                self._last_tool_calls = agent.last_tool_calls
            else:
                self._last_tool_calls = []
                result = self._get_plan_model().invoke(
                    [
                        SystemMessage(content=self._system_prompt),
                        HumanMessage(content=user_prompt),
                    ]
                )
            return ExplorationDirective.model_validate(result)
        except (OutputParserException, StructuredAgentOutputError, ValidationError) as error:
            raise JudgmentOutputError(str(error)) from error

    def analyze(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        relations: list[CodeRelation],
        *,
        correction_feedback: str | None = None,
    ) -> AnalysisDraft:
        """현재 Evidence에서 Finding·Hypothesis 초안을 생성한다."""

        user_prompt = build_analysis_prompt(
            context,
            evidence,
            relations,
            correction_feedback=correction_feedback,
        )
        try:
            if self._tools:
                agent = self._get_analysis_agent()
                result = agent.invoke(user_prompt)
                self._last_tool_calls = agent.last_tool_calls
            else:
                self._last_tool_calls = []
                result = self._get_analysis_model().invoke(
                    [
                        SystemMessage(content=self._system_prompt),
                        HumanMessage(content=user_prompt),
                    ]
                )
            return AnalysisDraft.model_validate(result)
        except (OutputParserException, StructuredAgentOutputError, ValidationError) as error:
            raise JudgmentOutputError(str(error)) from error

    def _get_chat_model(self) -> Any:
        """첫 plan 또는 analyze 호출 전에는 실제 provider 모델을 만들지 않는다."""

        if self._chat_model is None:
            self._chat_model = build_chat_model()
        return self._chat_model

    def _get_plan_model(self) -> Any:
        """탐색 질문 schema를 사용하는 runnable을 최초 한 번만 만든다."""

        if self._plan_model is None:
            self._plan_model = bind_structured_output(self._get_chat_model(), ExplorationDirective)
        return self._plan_model

    def _get_analysis_model(self) -> Any:
        """분석 초안 schema를 사용하는 runnable을 최초 한 번만 만든다."""

        if self._analysis_model is None:
            self._analysis_model = bind_structured_output(self._get_chat_model(), AnalysisDraft)
        return self._analysis_model

    def _get_plan_agent(self) -> StructuredToolAgent[ExplorationDirective]:
        """탐색 계획 Tool agent를 최초 한 번만 만든다."""

        if self._plan_agent is None:
            self._plan_agent = StructuredToolAgent(
                model=self._get_chat_model(),
                tools=self._tools,
                system_prompt=self._system_prompt,
                response_model=ExplorationDirective,
                name="issue_analysis_planner",
                limits=self._agent_limits or AgentLimits(max_tool_calls=8, max_model_calls=12),
            )
        return self._plan_agent

    def _get_analysis_agent(self) -> StructuredToolAgent[AnalysisDraft]:
        """Evidence 판단 Tool agent를 최초 한 번만 만든다."""

        if self._analysis_agent is None:
            self._analysis_agent = StructuredToolAgent(
                model=self._get_chat_model(),
                tools=self._tools,
                system_prompt=self._system_prompt,
                response_model=AnalysisDraft,
                name="issue_analysis_judgment",
                limits=self._agent_limits or AgentLimits(max_tool_calls=8, max_model_calls=12),
            )
        return self._analysis_agent


class LangChainInitialJudgmentModel(_LangChainJudgmentModel):
    """최초 Issue 분석 전용 prompt를 사용하는 adapter."""

    def __init__(
        self,
        *,
        tools: Sequence[BaseTool] = (),
        agent_limits: AgentLimits | None = None,
    ) -> None:
        super().__init__(
            INITIAL_SYSTEM_PROMPT,
            tools=tools,
            agent_limits=agent_limits,
        )


class LangChainRevisionJudgmentModel(_LangChainJudgmentModel):
    """이전 가설 재판단 전용 prompt를 사용하는 adapter."""

    def __init__(
        self,
        *,
        tools: Sequence[BaseTool] = (),
        agent_limits: AgentLimits | None = None,
    ) -> None:
        super().__init__(
            REVISION_SYSTEM_PROMPT,
            tools=tools,
            agent_limits=agent_limits,
        )
