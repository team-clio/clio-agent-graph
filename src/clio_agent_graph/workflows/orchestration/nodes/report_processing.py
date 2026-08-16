"""버그 리포트 매칭 서브그래프의 노드."""

from contextlib import suppress
from typing import Literal

from clio_agent_graph.context.application import get_application_services
from clio_agent_graph.workflows.orchestration.agents.report_processing import ReportProcessingAgent
from clio_agent_graph.workflows.orchestration.state import ClioState
from clio_agent_graph.workflows.reporting.matching.retrieval_subgraph import (
    build_issue_retrieval_subgraph,
)
from clio_agent_graph.workflows.reporting.normalization.defaults import (
    load_default_normalization_model,
)
from clio_agent_graph.workflows.reporting.normalization.models import (
    NormalizedReport,
    NormalizeReportInput,
)
from clio_agent_graph.workflows.reporting.normalization.service import ReportNormalizer
from clio_agent_graph.workflows.reporting.retrieval.graph import (
    build_bug_retrieval_indexer_graph,
)

report_agent = ReportProcessingAgent()


def _server():
    server = get_application_services().clio_server
    if server is None:
        raise RuntimeError("Clio Server service is not configured.")
    return server


def start_workflow(state: ClioState) -> dict[str, object]:
    """Server에 process_report 실행을 등록하고 RUNNING으로 전이한다."""

    started = _server().start_workflow(
        state["project_id"],
        state["request_id"],
        state["request_type"],
        state["request"]["payload"],
    )
    update: dict[str, object] = {
        "workflow_run_id": started.workflow_run_id,
        "workflow_replayed": started.status == "COMPLETED",
        "completed_nodes": {"start_workflow": True},
    }
    if started.status == "COMPLETED":
        update["status"] = "completed"
        update["result"] = _replayed_result(started.result)
    return update


def route_after_workflow_start(state: ClioState) -> Literal["process", "replayed"]:
    """완료된 멱등 replay는 Agent 실행과 쓰기를 반복하지 않는다."""

    return "replayed" if state.get("workflow_replayed") else "process"


def fail_workflow(state: ClioState, error: Exception) -> None:
    """실행 중 예외를 Server workflow 실패로 기록한다."""

    _server().fail_workflow(
        state["project_id"],
        state["workflow_run_id"],
        failure_code=type(error).__name__.upper()[:100],
        failure_message=str(error) or type(error).__name__,
    )


def load_and_normalize_report(state: ClioState) -> dict[str, object]:
    """Server Bug 원문을 정규화해 retrieval과 matcher에 전달한다."""

    report = report_agent.normalize_report(state["project_id"], state["bug_id"])
    normalized = build_report_normalizer().normalize(_normalization_input(state, report))
    return {
        "normalized_report": normalized.model_dump(mode="json"),
        "completed_nodes": {"load_and_normalize_report": True},
    }


def search_issue_candidates(state: ClioState) -> dict[str, object]:
    """Hybrid retrieval 결과를 matcher가 소비할 후보 상태로 변환한다."""

    candidates = state.get("issue_candidates")
    if candidates is None:
        result = build_issue_retrieval_subgraph().invoke(
            {
                "project_id": int(state["project_id"]),
                "bug_id": int(state["bug_id"]),
                "normalized_report": _normalized_report_for_retrieval(state),
            }
        )
        candidates = []
        for candidate in result["issue_candidates"]:
            payload = candidate.model_dump(mode="json")
            payload["issue_id"] = str(payload["issue_id"])
            candidates.append(payload)

    return {
        "issue_candidates": candidates,
        "completed_nodes": {"search_issue_candidates": True},
    }


def index_normalized_report(state: ClioState) -> dict[str, object]:
    """Issue 연결이 확정된 Bug를 다음 요청의 retrieval corpus에 반영한다."""

    build_bug_retrieval_indexer_graph().invoke(
        {
            "project_id": int(state["project_id"]),
            "bug_id": int(state["bug_id"]),
            "normalized_report": state["normalized_report"],
        }
    )
    return {"completed_nodes": {"index_normalized_report": True}}


def _normalized_report_for_retrieval(state: ClioState) -> NormalizedReport:
    """정규화 상태를 retrieval의 엄격한 도메인 계약으로 복원한다."""

    return NormalizedReport.model_validate(state["normalized_report"])


def build_report_normalizer() -> ReportNormalizer:
    """운영 기본 모델을 사용하는 ReportNormalizer를 조립한다."""

    return ReportNormalizer(load_default_normalization_model())


def _normalization_input(state: ClioState, report: dict[str, object]) -> NormalizeReportInput:
    """Server Bug projection을 Normalizer 공개 입력 계약으로 제한해 변환한다."""

    return NormalizeReportInput.model_validate(
        {
            "bug_id": int(state["bug_id"]),
            "title": report.get("title"),
            "description": report.get("description"),
            "source": report.get("source"),
            "error_type": report.get("error_type"),
            "message": report.get("message"),
            "stack_trace": report.get("stack_trace") or [],
            "occurred_at": report.get("occurred_at"),
            "raw_payload": report.get("raw_payload") or {},
        }
    )


def _replayed_result(result: dict[str, object] | None) -> dict[str, object]:
    """Server snapshot의 식별자를 신규 실행 결과와 같은 문자열 형식으로 맞춘다."""

    replayed = dict(result or {})
    for key in ("issue_id", "candidate_issue_id"):
        if replayed.get(key) is not None:
            replayed[key] = str(replayed[key])
    return replayed


def match_report(state: ClioState) -> dict[str, object]:
    """후보가 없으면 신규 Issue를 만들고, 있으면 LLM 비교를 실행한다."""

    candidates = state.get("issue_candidates", [])
    if not candidates:
        return {
            "match_decision": {
                "action": "create_new",
                "issue_id": None,
                "confidence": 1.0,
                "reason": "검색된 기존 이슈 후보가 없습니다.",
            },
            "completed_nodes": {"match_report": True},
        }

    decision = report_agent.decide_match(
        state["project_id"],
        state["bug_id"],
        state["normalized_report"],
        candidates,
    )
    return {
        "match_decision": decision,
        "completed_nodes": {"match_report": True},
    }


def apply_match_decision(state: ClioState) -> dict[str, object]:
    """Server API를 통해 Bug를 기존 또는 신규 Issue에 반영한다."""

    decision = state["match_decision"]
    action = decision["action"]
    if action == "link_existing":
        applied = _server().link_bug(
            state["project_id"],
            state["workflow_run_id"],
            state["bug_id"],
            decision["issue_id"],
            decision["confidence"],
        )
        issue_id = str(applied["issue_id"])
        return {
            "issue_id": issue_id,
            "status": "completed",
            "result": {
                "action": action,
                "bug_id": state["bug_id"],
                "issue_id": issue_id,
            },
            "completed_nodes": {"apply_match_decision": True},
        }
    if action == "needs_review":
        return {
            "status": "needs_review",
            "result": {
                "action": action,
                "bug_id": state["bug_id"],
                "candidate_issue_id": decision.get("issue_id"),
            },
            "completed_nodes": {"apply_match_decision": True},
        }

    draft = report_agent.draft_issue(state["normalized_report"])
    applied = _server().create_issue(
        state["project_id"],
        state["workflow_run_id"],
        state["bug_id"],
        decision["confidence"],
        title=draft["title"],
        description=draft["description"],
    )
    issue_id = str(applied["issue_id"])
    return {
        "issue_id": issue_id,
        "result": {
            "action": "create_new",
            "bug_id": state["bug_id"],
            "issue_id": issue_id,
        },
        "completed_nodes": {"apply_match_decision": True},
    }


def complete_workflow(state: ClioState) -> dict[str, object]:
    """모든 업무 결과를 Server workflow의 완료 snapshot으로 저장한다."""

    try:
        _server().complete_workflow(
            state["project_id"], state["workflow_run_id"], state.get("result", {})
        )
    except Exception as error:
        with suppress(Exception):
            fail_workflow(state, error)
        raise
    return {"completed_nodes": {"complete_workflow": True}}


def route_after_match(
    state: ClioState,
) -> Literal["index_report", "report_complete"]:
    """Issue 쓰기가 필요한 결정만 retrieval corpus에 먼저 반영한다."""

    if state["match_decision"]["action"] in {"create_new", "link_existing"}:
        return "index_report"
    return "report_complete"


def route_after_match_application(state: ClioState) -> Literal["issue_analysis", "report_complete"]:
    """신규 Issue만 생성 뒤의 분석 workflow로 진행한다."""

    return (
        "issue_analysis" if state["match_decision"]["action"] == "create_new" else "report_complete"
    )
