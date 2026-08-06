"""LangChain 모델을 Initial·Revision Judgment Protocol에 연결하는 adapter."""

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from clio_agent_graph.analysis.errors import JudgmentOutputError
from clio_agent_graph.analysis.models import (
    AnalysisDraft,
    CodeRelation,
    Evidence,
    ExplorationDirective,
    JudgmentContext,
)
from clio_agent_graph.analysis.prompts import (
    INITIAL_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
    build_analysis_prompt,
    build_plan_prompt,
)

DEFAULT_MODEL = "openai:gpt-4.1-mini"


class _LangChainJudgmentModel:
    """두 Judgment adapter가 공유하는 지연 생성·structured output 구현."""

    def __init__(self, system_prompt: str, model_name: str | None = None) -> None:
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._chat_model: Any | None = None
        self._plan_model: Any | None = None
        self._analysis_model: Any | None = None

    def plan(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        asked_questions: list[str],
        *,
        correction_feedback: str | None = None,
    ) -> ExplorationDirective:
        """현재 분석 상태에 맞는 다음 탐색 질문을 structured output으로 만든다."""

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(
                content=build_plan_prompt(
                    context,
                    evidence,
                    asked_questions,
                    correction_feedback=correction_feedback,
                )
            ),
        ]
        try:
            result = self._get_plan_model().invoke(messages)
            return ExplorationDirective.model_validate(result)
        except (OutputParserException, ValidationError) as error:
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

        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(
                content=build_analysis_prompt(
                    context,
                    evidence,
                    relations,
                    correction_feedback=correction_feedback,
                )
            ),
        ]
        try:
            result = self._get_analysis_model().invoke(messages)
            return AnalysisDraft.model_validate(result)
        except (OutputParserException, ValidationError) as error:
            raise JudgmentOutputError(str(error)) from error

    def _get_chat_model(self) -> Any:
        """첫 plan 또는 analyze 호출 전에는 실제 provider 모델을 만들지 않는다."""

        if self._chat_model is None:
            model_name = self._model_name or os.getenv("CLIO_MODEL", DEFAULT_MODEL)
            self._chat_model = init_chat_model(model_name)
        return self._chat_model

    def _get_plan_model(self) -> Any:
        """탐색 질문 schema를 사용하는 runnable을 최초 한 번만 만든다."""

        if self._plan_model is None:
            self._plan_model = self._get_chat_model().with_structured_output(ExplorationDirective)
        return self._plan_model

    def _get_analysis_model(self) -> Any:
        """분석 초안 schema를 사용하는 runnable을 최초 한 번만 만든다."""

        if self._analysis_model is None:
            self._analysis_model = self._get_chat_model().with_structured_output(AnalysisDraft)
        return self._analysis_model


class LangChainInitialJudgmentModel(_LangChainJudgmentModel):
    """최초 Issue 분석 전용 prompt를 사용하는 adapter."""

    def __init__(self, model_name: str | None = None) -> None:
        super().__init__(INITIAL_SYSTEM_PROMPT, model_name)


class LangChainRevisionJudgmentModel(_LangChainJudgmentModel):
    """이전 가설 재판단 전용 prompt를 사용하는 adapter."""

    def __init__(self, model_name: str | None = None) -> None:
        super().__init__(REVISION_SYSTEM_PROMPT, model_name)
