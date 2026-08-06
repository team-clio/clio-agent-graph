"""Codex CLI structured output을 IA Judgment Protocol에 연결한다."""

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
from clio_agent_graph.codex_exec import (
    CodexExecOutputError,
    CodexExecStructuredInvoker,
)


class _CodexJudgmentModel:
    """Initial·Revision 판단이 공유하는 Codex structured-output 구현."""

    def __init__(
        self,
        system_prompt: str,
        invoker: CodexExecStructuredInvoker | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._invoker = invoker or CodexExecStructuredInvoker()

    def plan(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        asked_questions: list[str],
        *,
        correction_feedback: str | None = None,
    ) -> ExplorationDirective:
        """코드 탐색 질문을 Codex structured run으로 만든다."""

        try:
            return self._invoker.invoke(
                system_prompt=self._system_prompt,
                user_prompt=build_plan_prompt(
                    context,
                    evidence,
                    asked_questions,
                    correction_feedback=correction_feedback,
                ),
                output_type=ExplorationDirective,
            )
        except (CodexExecOutputError, ValidationError) as error:
            raise JudgmentOutputError(str(error)) from error

    def analyze(
        self,
        context: JudgmentContext,
        evidence: list[Evidence],
        relations: list[CodeRelation],
        *,
        correction_feedback: str | None = None,
    ) -> AnalysisDraft:
        """Finding·Hypothesis 초안을 Codex structured run으로 만든다."""

        try:
            return self._invoker.invoke(
                system_prompt=self._system_prompt,
                user_prompt=build_analysis_prompt(
                    context,
                    evidence,
                    relations,
                    correction_feedback=correction_feedback,
                ),
                output_type=AnalysisDraft,
            )
        except (CodexExecOutputError, ValidationError) as error:
            raise JudgmentOutputError(str(error)) from error


class CodexInitialJudgmentModel(_CodexJudgmentModel):
    """최초 Issue 분석용 Codex 판단 모델."""

    def __init__(self, invoker: CodexExecStructuredInvoker | None = None) -> None:
        super().__init__(INITIAL_SYSTEM_PROMPT, invoker)


class CodexRevisionJudgmentModel(_CodexJudgmentModel):
    """Issue 재분석용 Codex 판단 모델."""

    def __init__(self, invoker: CodexExecStructuredInvoker | None = None) -> None:
        super().__init__(REVISION_SYSTEM_PROMPT, invoker)
