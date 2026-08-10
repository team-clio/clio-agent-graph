"""Codex CLI structured output을 RM Protocol에 연결한다."""

from pydantic import ValidationError

from clio_agent_graph.runtime.codex_exec import (
    CodexExecOutputError,
    CodexExecStructuredInvoker,
)
from clio_agent_graph.workflows.reporting.matching.errors import IssueMatchOutputError
from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    MatchComparisonDraft,
)
from clio_agent_graph.workflows.reporting.matching.prompts import SYSTEM_PROMPT, build_user_prompt
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


class CodexIssueMatchModel:
    """ChatGPT OAuth로 로그인한 Codex CLI에서 후보 비교 결과를 생성한다."""

    def __init__(self, invoker: CodexExecStructuredInvoker | None = None) -> None:
        self._invoker = invoker or CodexExecStructuredInvoker()

    def compare(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        *,
        correction_feedback: str | None = None,
    ) -> MatchComparisonDraft:
        """기존 RM prompt와 schema를 Codex structured run에 전달한다."""

        try:
            return self._invoker.invoke(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(
                    report,
                    candidates,
                    correction_feedback=correction_feedback,
                ),
                output_type=MatchComparisonDraft,
            )
        except (CodexExecOutputError, ValidationError) as error:
            raise IssueMatchOutputError(str(error)) from error
