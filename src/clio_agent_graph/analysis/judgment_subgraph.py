"""상황별 Judgment 모델을 실제 LangGraph subagent로 실행한다."""

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from clio_agent_graph.agent_runtime import ToolCallRecord
from clio_agent_graph.analysis.errors import JudgmentError, JudgmentOutputError
from clio_agent_graph.analysis.models import (
    AnalysisDraft,
    AnalysisMode,
    AnalysisStatus,
    CodeRelation,
    Evidence,
    ExplorationDirective,
    HypothesisDisposition,
    IssueAnalysis,
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
    judgment_tool_calls: list[ToolCallRecord]


class JudgmentOutput(TypedDict, total=False):
    """현재 phase에 따라 하나의 structured output만 반환한다."""

    exploration_directive: ExplorationDirective
    analysis_draft: AnalysisDraft
    judgment_tool_calls: list[ToolCallRecord]


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
        return {
            "exploration_directive": directive,
            "judgment_tool_calls": [dict(item) for item in getattr(model, "last_tool_calls", [])],
        }

    def analyze_evidence(state: JudgmentState) -> dict[str, Any]:
        """Evidence를 분석 초안으로 바꾸고 잘못된 출력은 한 번 교정한다."""

        context = JudgmentContext.model_validate(state["judgment_context"])
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        relations = [CodeRelation.model_validate(item) for item in state["relations"]]

        def call_and_validate(feedback: str | None) -> AnalysisDraft:
            """모델 초안을 실제 Evidence와 이전 분석 문맥까지 대조한다."""

            draft = AnalysisDraft.model_validate(
                model.analyze(
                    context,
                    evidence,
                    relations,
                    correction_feedback=feedback,
                )
            )
            _validate_analysis_draft(context, evidence, relations, draft)
            return draft

        draft = _call_with_one_retry(
            call_and_validate,
            AnalysisDraft,
        )
        return {
            "analysis_draft": draft,
            "judgment_tool_calls": [dict(item) for item in getattr(model, "last_tool_calls", [])],
        }

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


def _validate_analysis_draft(
    context: JudgmentContext,
    evidence: list[Evidence],
    relations: list[CodeRelation],
    draft: AnalysisDraft,
) -> None:
    """초안 참조와 재분석 변화 요약을 실제 입력에 맞춰 검증한다."""

    analysis = IssueAnalysis(
        analysis_job_id=context.analysis_job_id,
        project_id=context.project_id,
        issue_id=context.issue.issue_id,
        status=AnalysisStatus.COMPLETED,
        evidence=evidence,
        relations=relations,
        findings=draft.findings,
        hypotheses=draft.hypotheses,
        revision_summary=draft.revision_summary,
    )
    if context.mode is AnalysisMode.INITIAL:
        if analysis.revision_summary is not None:
            raise JudgmentOutputError("Initial analysis must not contain revision_summary.")
        return

    previous = context.previous_analysis
    revision = analysis.revision_summary
    if previous is None or revision is None:
        raise JudgmentOutputError("Revision analysis requires revision_summary.")
    if revision.previous_analysis_job_id != previous.analysis_job_id:
        raise JudgmentOutputError("Revision summary references the wrong previous job.")

    previous_ids = {item.hypothesis_id for item in previous.hypotheses}
    revision_previous_ids = [item.previous_hypothesis_id for item in revision.hypothesis_revisions]
    if len(revision_previous_ids) != len(set(revision_previous_ids)):
        raise JudgmentOutputError("Previous hypotheses must be revised exactly once.")
    if set(revision_previous_ids) != previous_ids:
        raise JudgmentOutputError("Revision summary must cover every previous hypothesis.")

    current_ids = {item.hypothesis_id for item in analysis.hypotheses}
    mapped_current_ids: set[str] = set()
    for item in revision.hypothesis_revisions:
        if item.disposition is HypothesisDisposition.DROPPED:
            if item.current_hypothesis_id is not None:
                raise JudgmentOutputError(
                    "DROPPED hypothesis must not reference a current hypothesis."
                )
            continue
        if item.current_hypothesis_id not in current_ids:
            raise JudgmentOutputError("Retained hypothesis must reference a current hypothesis.")
        mapped_current_ids.add(item.current_hypothesis_id)

    new_ids = set(revision.new_hypothesis_ids)
    if not new_ids.issubset(current_ids):
        raise JudgmentOutputError("New hypothesis IDs must exist in the current analysis.")
    if new_ids != current_ids - mapped_current_ids:
        raise JudgmentOutputError(
            "Revision summary must identify every unmapped current hypothesis as new."
        )
