"""LangChain chat model을 NM 전용 Protocol에 연결하는 adapter."""

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from clio_agent_graph.normalization.models import NormalizationDraft
from clio_agent_graph.normalization.ports import NormalizationOutputError
from clio_agent_graph.normalization.prompts import SYSTEM_PROMPT, build_user_prompt

DEFAULT_MODEL = "openai:gpt-4.1-mini"


class LangChainNormalizationModel:
    """LangChain structured output을 사용해 NormalizationDraft를 생성한다."""

    def __init__(self, model_name: str | None = None) -> None:
        # 모델 객체는 네트워크 설정이나 API key를 요구할 수 있어 첫 호출까지 만들지 않는다.
        self._model_name = model_name
        self._structured_model: Any | None = None

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        """모델을 지연 생성하고 검증 가능한 NM 초안을 반환한다."""

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=build_user_prompt(
                    report_text,
                    correction_feedback=correction_feedback,
                )
            ),
        ]
        try:
            result = self._get_structured_model().invoke(messages)
            return NormalizationDraft.model_validate(result)
        except (OutputParserException, ValidationError) as error:
            # provider 연결 실패 같은 예외는 잡지 않는다. 구조화 결과 오류만 교정 대상이다.
            raise NormalizationOutputError(str(error)) from error

    def _get_structured_model(self) -> Any:
        """최초 호출에서만 실제 chat model과 structured output runnable을 만든다."""

        if self._structured_model is None:
            model_name = self._model_name or os.getenv("CLIO_MODEL", DEFAULT_MODEL)
            chat_model = init_chat_model(model_name)
            self._structured_model = chat_model.with_structured_output(NormalizationDraft)
        return self._structured_model
