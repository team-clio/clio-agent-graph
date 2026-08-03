"""Codex CLI structured output을 NM Protocol에 연결한다."""

from pydantic import ValidationError

from clio_agent_graph.codex_exec import (
    CodexExecOutputError,
    CodexExecStructuredInvoker,
)
from clio_agent_graph.normalization.models import NormalizationDraft
from clio_agent_graph.normalization.ports import NormalizationOutputError
from clio_agent_graph.normalization.prompts import SYSTEM_PROMPT, build_user_prompt


class CodexNormalizationModel:
    """ChatGPT OAuth로 로그인한 Codex CLI에서 NM 초안을 생성한다."""

    def __init__(self, invoker: CodexExecStructuredInvoker | None = None) -> None:
        self._invoker = invoker or CodexExecStructuredInvoker()

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        """기존 NM prompt와 schema를 그대로 Codex structured run에 전달한다."""

        try:
            return self._invoker.invoke(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(
                    report_text,
                    correction_feedback=correction_feedback,
                ),
                output_type=NormalizationDraft,
            )
        except (CodexExecOutputError, ValidationError) as error:
            raise NormalizationOutputError(str(error)) from error
