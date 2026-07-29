"""최초 분석과 재분석이 공유하는 IA LangGraph 오케스트레이터."""

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.analysis.exploration_subgraph import (
    build_code_exploration_subgraph,
)
from clio_agent_graph.analysis.judgment_subgraph import build_judgment_subgraph
from clio_agent_graph.analysis.langchain_adapter import (
    LangChainInitialJudgmentModel,
    LangChainRevisionJudgmentModel,
)
from clio_agent_graph.analysis.models import (
    AnalysisBug,
    AnalysisDraft,
    AnalysisIssue,
    AnalysisMode,
    AnalysisStatus,
    CodeRelation,
    Evidence,
    EvidenceCandidate,
    ExplorationDirective,
    ExplorationRequest,
    ExplorationResponse,
    InitialAnalysisInput,
    IssueAnalysis,
    JudgmentContext,
    JudgmentPhase,
    ReanalysisInput,
    RevisionSummary,
)
from clio_agent_graph.analysis.ports import JudgmentModel

MAX_EXPLORATION_ROUNDS = 3
MAX_EVIDENCE = 20
MAX_RELATIONS = 30


class InitialGraphInput(TypedDict):
    """`issue_analyzer` 공개 그래프의 JSON 입력."""

    analysis_job_id: int
    project_id: int
    issue: AnalysisIssue
    bugs: list[AnalysisBug]
    trigger_bug_id: int


class ReanalysisGraphInput(InitialGraphInput):
    """`issue_reanalyzer`가 추가로 요구하는 이전 분석."""

    previous_analysis: IssueAnalysis


class AnalysisGraphState(TypedDict, total=False):
    """공통 IA가 탐색 round와 subagent 결과를 운반하는 내부 state."""

    analysis_job_id: int
    project_id: int
    issue: AnalysisIssue
    bugs: list[AnalysisBug]
    trigger_bug_id: int
    previous_analysis: IssueAnalysis
    judgment_context: JudgmentContext
    judgment_phase: JudgmentPhase
    evidence: list[Evidence]
    relations: list[CodeRelation]
    asked_questions: list[str]
    exploration_round: int
    exploration_directive: ExplorationDirective
    exploration_request: ExplorationRequest
    exploration_response: ExplorationResponse
    analysis_draft: AnalysisDraft
    warnings: list[str]
    issue_analysis: IssueAnalysis


class AnalysisGraphOutput(TypedDict):
    """두 공개 그래프가 Supervisor에 반환하는 공통 출력."""

    issue_analysis: IssueAnalysis


def build_issue_analyzer_graph(
    *,
    code_exploration_subgraph: Any | None = None,
    judgment_model: JudgmentModel | None = None,
):
    """최초 분석 전용 Judgment subagent를 사용하는 공개 그래프를 만든다."""

    model = judgment_model if judgment_model is not None else LangChainInitialJudgmentModel()
    return _build_analysis_graph(
        mode=AnalysisMode.INITIAL,
        input_schema=InitialGraphInput,
        code_exploration_subgraph=code_exploration_subgraph,
        judgment_subgraph=build_judgment_subgraph(model),
    )


def build_issue_reanalyzer_graph(
    *,
    code_exploration_subgraph: Any | None = None,
    judgment_model: JudgmentModel | None = None,
):
    """이전 가설 재판단 subagent를 사용하는 공개 그래프를 만든다."""

    model = judgment_model if judgment_model is not None else LangChainRevisionJudgmentModel()
    return _build_analysis_graph(
        mode=AnalysisMode.REVISION,
        input_schema=ReanalysisGraphInput,
        code_exploration_subgraph=code_exploration_subgraph,
        judgment_subgraph=build_judgment_subgraph(model),
    )


def _build_analysis_graph(
    *,
    mode: AnalysisMode,
    input_schema: type,
    code_exploration_subgraph: Any | None,
    judgment_subgraph: Any,
):
    """상황별 입력과 판단 subagent를 공통 탐색 오케스트레이터에 연결한다."""

    explorer = (
        code_exploration_subgraph
        if code_exploration_subgraph is not None
        else build_code_exploration_subgraph()
    )

    def prepare_analysis(state: AnalysisGraphState) -> dict[str, Any]:
        """공개 입력을 검증하고 비어 있는 공통 IA state를 만든다."""

        if mode is AnalysisMode.INITIAL:
            parsed = InitialAnalysisInput.model_validate(state)
            previous = None
        else:
            parsed = ReanalysisInput.model_validate(state)
            previous = parsed.previous_analysis
        context = JudgmentContext(
            mode=mode,
            analysis_job_id=parsed.analysis_job_id,
            project_id=parsed.project_id,
            issue=parsed.issue,
            bugs=parsed.bugs,
            trigger_bug_id=parsed.trigger_bug_id,
            previous_analysis=previous,
        )
        return {
            "judgment_context": context,
            "judgment_phase": JudgmentPhase.PLAN,
            "evidence": [],
            "relations": [],
            "asked_questions": [],
            "exploration_round": 0,
            "warnings": [],
        }

    def route_after_judgment(
        state: AnalysisGraphState,
    ) -> Literal["prepare_request", "finalize"]:
        """판단 phase가 끝난 뒤 탐색 또는 최종 조립으로 이동한다."""

        if JudgmentPhase(state["judgment_phase"]) is JudgmentPhase.ANALYZE:
            return "finalize"
        return "prepare_request"

    def prepare_exploration_request(state: AnalysisGraphState) -> dict[str, Any]:
        """반복 질문을 제거하고 다음 탐색 요청 또는 종료 상태를 만든다."""

        directive = ExplorationDirective.model_validate(state["exploration_directive"])
        previous_keys = {_normalize_question(item) for item in state["asked_questions"]}
        novel_questions: list[str] = []
        for question in directive.questions:
            key = _normalize_question(question)
            if key not in previous_keys:
                novel_questions.append(question)
                previous_keys.add(key)

        if not novel_questions or state["exploration_round"] >= MAX_EXPLORATION_ROUNDS:
            return {
                "judgment_phase": (
                    JudgmentPhase.ANALYZE if state["evidence"] else JudgmentPhase.PLAN
                ),
                "exploration_directive": ExplorationDirective(),
            }

        request = ExplorationRequest(
            project_id=state["project_id"],
            issue=AnalysisIssue.model_validate(state["issue"]),
            bugs=[AnalysisBug.model_validate(item) for item in state["bugs"]],
            questions=novel_questions,
            existing_evidence=state["evidence"],
        )
        return {
            "exploration_request": request,
            "asked_questions": [*state["asked_questions"], *novel_questions],
        }

    def route_prepared_request(
        state: AnalysisGraphState,
    ) -> Literal["explore", "analyze", "insufficient"]:
        """새 질문과 현재 Evidence 유무로 다음 노드를 선택한다."""

        if (
            state.get("exploration_request") is not None
            and state["exploration_directive"].questions
        ):
            return "explore"
        return "analyze" if state["evidence"] else "insufficient"

    def merge_exploration(state: AnalysisGraphState) -> dict[str, Any]:
        """새 후보를 중복 제거해 E ID를 부여하고 유효한 관계만 병합한다."""

        response = ExplorationResponse.model_validate(state["exploration_response"])
        evidence, relations, warnings = _merge_exploration_response(
            state["evidence"],
            state["relations"],
            response,
            state["warnings"],
        )
        round_number = state["exploration_round"] + 1
        next_phase = (
            JudgmentPhase.ANALYZE
            if round_number >= MAX_EXPLORATION_ROUNDS and evidence
            else JudgmentPhase.PLAN
        )
        return {
            "evidence": evidence,
            "relations": relations,
            "warnings": warnings,
            "exploration_round": round_number,
            "judgment_phase": next_phase,
            "exploration_request": None,
            "exploration_response": None,
        }

    def route_after_merge(
        state: AnalysisGraphState,
    ) -> Literal["judge", "insufficient"]:
        """최대 round에 Evidence가 하나도 없을 때만 근거 부족으로 끝낸다."""

        if state["exploration_round"] >= MAX_EXPLORATION_ROUNDS and not state["evidence"]:
            return "insufficient"
        return "judge"

    def finalize_analysis(state: AnalysisGraphState) -> dict[str, Any]:
        """검증된 초안과 현재 snapshot을 완전한 IssueAnalysis로 조립한다."""

        context = JudgmentContext.model_validate(state["judgment_context"])
        draft = AnalysisDraft.model_validate(state["analysis_draft"])
        result = IssueAnalysis(
            analysis_job_id=context.analysis_job_id,
            project_id=context.project_id,
            issue_id=context.issue.issue_id,
            status=AnalysisStatus.COMPLETED,
            evidence=state["evidence"],
            relations=state["relations"],
            findings=draft.findings,
            hypotheses=draft.hypotheses,
            revision_summary=draft.revision_summary,
            warnings=state["warnings"],
        )
        return {"issue_analysis": result}

    def finalize_insufficient(state: AnalysisGraphState) -> dict[str, Any]:
        """정상 탐색에서 근거를 찾지 못한 결과를 모델 호출 없이 만든다."""

        context = JudgmentContext.model_validate(state["judgment_context"])
        revision_summary = None
        if context.previous_analysis is not None:
            revision_summary = RevisionSummary(
                previous_analysis_job_id=context.previous_analysis.analysis_job_id
            )
        return {
            "issue_analysis": IssueAnalysis(
                analysis_job_id=context.analysis_job_id,
                project_id=context.project_id,
                issue_id=context.issue.issue_id,
                status=AnalysisStatus.INSUFFICIENT_EVIDENCE,
                revision_summary=revision_summary,
                warnings=[*state["warnings"], "코드 탐색에서 분석 근거를 찾지 못했습니다."],
            )
        }

    builder = StateGraph(
        AnalysisGraphState,
        input_schema=input_schema,
        output_schema=AnalysisGraphOutput,
    )
    builder.add_node("prepare_analysis", prepare_analysis)
    builder.add_node("judgment_subagent", judgment_subgraph)
    builder.add_node("prepare_exploration", prepare_exploration_request)
    builder.add_node("codebase_exploration_subgraph", explorer)
    builder.add_node("merge_exploration", merge_exploration)
    builder.add_node("finalize_analysis", finalize_analysis)
    builder.add_node("finalize_insufficient", finalize_insufficient)
    builder.add_edge(START, "prepare_analysis")
    builder.add_edge("prepare_analysis", "judgment_subagent")
    builder.add_conditional_edges(
        "judgment_subagent",
        route_after_judgment,
        {"prepare_request": "prepare_exploration", "finalize": "finalize_analysis"},
    )
    builder.add_conditional_edges(
        "prepare_exploration",
        route_prepared_request,
        {
            "explore": "codebase_exploration_subgraph",
            "analyze": "judgment_subagent",
            "insufficient": "finalize_insufficient",
        },
    )
    builder.add_edge("codebase_exploration_subgraph", "merge_exploration")
    builder.add_conditional_edges(
        "merge_exploration",
        route_after_merge,
        {"judge": "judgment_subagent", "insufficient": "finalize_insufficient"},
    )
    builder.add_edge("finalize_analysis", END)
    builder.add_edge("finalize_insufficient", END)
    return builder.compile()


def _merge_exploration_response(
    existing_evidence: list[Evidence],
    existing_relations: list[CodeRelation],
    response: ExplorationResponse,
    existing_warnings: list[str],
) -> tuple[list[Evidence], list[CodeRelation], list[str]]:
    """한 round 결과를 first-seen 순서로 병합하고 상한을 적용한다."""

    evidence = list(existing_evidence)
    relations = list(existing_relations)
    warnings = list(existing_warnings)
    key_to_id = {_evidence_dedup_key(item): item.evidence_id for item in evidence}
    response_ref_map: dict[str, str] = {}

    for candidate in response.candidates:
        candidate = EvidenceCandidate.model_validate(candidate)
        dedup_key = _candidate_dedup_key(candidate)
        evidence_id = key_to_id.get(dedup_key)
        if evidence_id is None:
            if len(evidence) >= MAX_EVIDENCE:
                _append_warning_once(warnings, "Evidence 최대 20개 제한을 적용했습니다.")
                continue
            evidence_id = f"E{len(evidence) + 1}"
            item = Evidence(
                evidence_id=evidence_id,
                kind=candidate.kind,
                code_snapshot=candidate.code_snapshot,
                observation=candidate.observation,
                file_path=candidate.file_path,
                symbol=candidate.symbol,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                change_id=candidate.change_id,
            )
            evidence.append(item)
            key_to_id[dedup_key] = evidence_id
        response_ref_map[candidate.candidate_key] = evidence_id

    known_evidence_ids = {item.evidence_id for item in evidence}
    relation_keys = {
        (item.source_evidence_id, item.target_evidence_id, item.relation_type) for item in relations
    }
    for candidate in response.relations:
        source = response_ref_map.get(candidate.source_ref, candidate.source_ref)
        target = response_ref_map.get(candidate.target_ref, candidate.target_ref)
        if source not in known_evidence_ids or target not in known_evidence_ids:
            continue
        key = (source, target, candidate.relation_type)
        if key in relation_keys:
            continue
        if len(relations) >= MAX_RELATIONS:
            _append_warning_once(warnings, "CodeRelation 최대 30개 제한을 적용했습니다.")
            break
        relations.append(
            CodeRelation(
                source_evidence_id=source,
                target_evidence_id=target,
                relation_type=candidate.relation_type,
            )
        )
        relation_keys.add(key)
    return evidence, relations, warnings


def _normalize_question(value: str) -> str:
    """대소문자와 반복 공백 차이를 무시해 같은 질문을 찾는다."""

    return " ".join(value.casefold().split())


def _evidence_dedup_key(item: Evidence) -> tuple[object, ...]:
    """이미 ID가 부여된 Evidence의 내용 기반 중복 제거 key를 만든다."""

    return (
        item.kind,
        item.code_snapshot,
        item.file_path,
        item.symbol,
        item.start_line,
        item.end_line,
        item.change_id,
    )


def _candidate_dedup_key(item: EvidenceCandidate) -> tuple[object, ...]:
    """Explorer 후보를 최종 Evidence와 같은 기준으로 비교한다."""

    return (
        item.kind,
        item.code_snapshot,
        item.file_path,
        item.symbol,
        item.start_line,
        item.end_line,
        item.change_id,
    )


def _append_warning_once(warnings: list[str], message: str) -> None:
    """같은 상한 경고가 탐색 round마다 반복되지 않게 한다."""

    if message not in warnings:
        warnings.append(message)


issue_analyzer_graph = build_issue_analyzer_graph()
issue_reanalyzer_graph = build_issue_reanalyzer_graph()
