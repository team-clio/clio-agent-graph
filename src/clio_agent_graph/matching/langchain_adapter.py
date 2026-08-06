"""LangChain chat model을 RM 후보 비교 Protocol에 연결하는 adapter."""

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from clio_agent_graph.matching.errors import IssueMatchOutputError
from clio_agent_graph.matching.models import IssueCandidate, MatchComparisonDraft
from clio_agent_graph.matching.prompts import SYSTEM_PROMPT, build_user_prompt
from clio_agent_graph.normalization.models import NormalizedReport

DEFAULT_MODEL = "openai:gpt-4.1-mini"


class LangChainIssueMatchModel:
    """LangChain structured output으로 후보별 비교 결과를 생성한다."""

    def __init__(self, model_name: str | None = None) -> None:
        # 실제 모델은 API key를 요구할 수 있으므로 첫 compare 호출까지 만들지 않는다.
        self._model_name = model_name
        self._structured_model: Any | None = None

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        """후보 전체를 한 번에 비교하고 검증 가능한 결과를 반환한다."""

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=build_user_prompt(
                    report,
                    candidates,
                    correction_feedback=correction_feedback,
                )
            ),
        ]
        try:
            result = self._get_structured_model().invoke(messages)
            return MatchComparisonDraft.model_validate(result)
        except (OutputParserException, ValidationError) as error:
            # 인증·네트워크 같은 provider 오류는 서비스 계층이 동일 요청으로 재시도한다.
            raise IssueMatchOutputError(str(error)) from error

    def _get_structured_model(self) -> Any:
        """최초 비교 호출에서만 실제 chat model을 만든다."""

        if self._structured_model is None:
            model_name = self._model_name or os.getenv("CLIO_MODEL", DEFAULT_MODEL)
            chat_model = init_chat_model(model_name)
            self._structured_model = chat_model.with_structured_output(MatchComparisonDraft)
        return self._structured_model
