"""상황별 Judgment 모델을 실제 LangGraph subagent로 실행한다."""

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from clio_agent_graph.analysis.errors import JudgmentError, JudgmentOutputError
from clio_agent_graph.analysis.models import (
    AnalysisDraft,
    CodeRelation,
    Evidence,
    ExplorationDirective,
    JudgmentContext,
    JudgmentPhase,
)
from clio_agent_graph.analysis.ports import JudgmentModel


class JudgmentInput(TypedDict):
    """공통 IA가 Judgment subagent에 전달하는 state."""

    judgment_context: JudgmentContext
    judgment_phase: JudgmentPhase
    evidence: list[Evidence]
    relations: list[CodeRelation]
    asked_questions: list[str]


class JudgmentState(JudgmentInput, total=False):
    """Judgment subagent 내부 state."""

    exploration_directive: ExplorationDirective
    analysis_draft: AnalysisDraft


class JudgmentOutput(TypedDict, total=False):
    """현재 phase에 따라 하나의 structured output만 반환한다."""

    exploration_directive: ExplorationDirective
    analysis_draft: AnalysisDraft


def build_judgment_subgraph(model: JudgmentModel):
    """Judgment 모델의 plan·analyze 메서드를 조건부 subgraph로 만든다."""

    def route_phase(state: JudgmentState) -> Literal["plan", "analyze"]:
        """공통 IA가 요청한 판단 phase를 내부 노드 이름으로 바꾼다."""

        phase = JudgmentPhase(state["judgment_phase"])
        return "plan" if phase is JudgmentPhase.PLAN else "analyze"

    def plan_exploration(state: JudgmentState) -> dict[str, Any]:
        """다음 탐색 질문을 만들고 잘못된 출력은 한 번 교정한다."""

        directive = _call_with_one_retry(
            lambda feedback: model.plan(
                JudgmentContext.model_validate(state["judgment_context"]),
                [Evidence.model_validate(item) for item in state["evidence"]],
                list(state["asked_questions"]),
                correction_feedback=feedback,
            ),
            ExplorationDirective,
        )
        return {"exploration_directive": directive}

    def analyze_evidence(state: JudgmentState) -> dict[str, Any]:
        """Evidence를 분석 초안으로 바꾸고 잘못된 출력은 한 번 교정한다."""

        draft = _call_with_one_retry(
            lambda feedback: model.analyze(
                JudgmentContext.model_validate(state["judgment_context"]),
                [Evidence.model_validate(item) for item in state["evidence"]],
                [CodeRelation.model_validate(item) for item in state["relations"]],
                correction_feedback=feedback,
            ),
            AnalysisDraft,
        )
        return {"analysis_draft": draft}

    builder = StateGraph(
        JudgmentState,
        input_schema=JudgmentInput,
        output_schema=JudgmentOutput,
    )
    builder.add_node("plan_exploration", plan_exploration)
    builder.add_node("analyze_evidence", analyze_evidence)
    builder.add_conditional_edges(
        START,
        route_phase,
        {"plan": "plan_exploration", "analyze": "analyze_evidence"},
    )
    builder.add_edge("plan_exploration", END)
    builder.add_edge("analyze_evidence", END)
    return builder.compile()


def _call_with_one_retry(call, output_type):
    """provider 실패는 동일 호출로, schema 오류는 피드백과 함께 한 번 재시도한다."""

    feedback: str | None = None
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            return output_type.model_validate(call(feedback))
        except (JudgmentOutputError, ValidationError) as error:
            last_error = error
            feedback = str(error)[:2_000]
        except Exception as error:
            last_error = error
            feedback = None

    if isinstance(last_error, (JudgmentOutputError, ValidationError)):
        raise JudgmentOutputError(
            "Judgment output remained invalid after one correction."
        ) from last_error
    raise JudgmentError("Judgment subagent failed after one retry.") from last_error
