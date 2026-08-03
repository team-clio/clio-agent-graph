"""이슈 분석 서브그래프의 흐름용 노드."""

from typing import Literal

from clio_agent_graph.agents.issue_analysis import IssueAnalysisAgent
from clio_agent_graph.services.mock import mock_service
from clio_agent_graph.state import ClioState

analysis_agent = IssueAnalysisAgent()


def prepare_analysis(state: ClioState) -> dict[str, object]:
    """이슈와 고정된 컨텍스트 snapshot 및 검색 질의를 준비한다."""

    default_snapshot, default_queries = analysis_agent.prepare(
        state["project_id"], state["issue_id"]
    )
    snapshot = state.get("context_snapshot", default_snapshot)
    queries = state.get("analysis_queries", default_queries)
    return {
        "context_snapshot": snapshot,
        "analysis_queries": queries,
        "completed_nodes": {"prepare_analysis": True},
    }


def search_documents(state: ClioState) -> dict[str, object]:
    """조사 Agent가 문서 검색 Tool을 호출한다."""

    return {
        "document_evidence": state.get("document_evidence")
        or analysis_agent.search(
            "documents", state["project_id"], state["analysis_queries"]["documents"]
        ),
        "completed_nodes": {"search_documents": True},
    }


def search_code(state: ClioState) -> dict[str, object]:
    """조사 Agent가 코드 검색 Tool을 호출한다."""

    return {
        "code_evidence": state.get("code_evidence")
        or analysis_agent.search("code", state["project_id"], state["analysis_queries"]["code"]),
        "completed_nodes": {"search_code": True},
    }


def search_history(state: ClioState) -> dict[str, object]:
    """조사 Agent가 해결 이력 검색 Tool을 호출한다."""

    return {
        "history_evidence": state.get("history_evidence")
        or analysis_agent.search(
            "history", state["project_id"], state["analysis_queries"]["history"]
        ),
        "completed_nodes": {"search_history": True},
    }


def analyze_issue(state: ClioState) -> dict[str, object]:
    """세 검색 결과가 합류한 뒤 실행되는 분석 노드의 계약을 제공한다."""

    analysis = analysis_agent.analyze(
        state["issue_id"],
        {
            "documents": state.get("document_evidence", []),
            "code": state.get("code_evidence", []),
            "history": state.get("history_evidence", []),
        },
    )
    return {
        "issue_analysis": analysis,
        "completed_nodes": {"analyze_issue": True},
    }


def plan_resolution(state: ClioState) -> dict[str, object]:
    """추후 LLM structured output으로 교체할 해결 계획 경계."""

    return {
        "resolution_plan": analysis_agent.plan(state["issue_id"], state["issue_analysis"]),
        "completed_nodes": {"plan_resolution": True},
    }


def quality_gate(state: ClioState) -> dict[str, object]:
    """근거 계약을 검사하고, 요청된 retry는 한 번만 재분석한다."""

    has_contract = "issue_analysis" in state and "resolution_plan" in state
    requested_status = state.get("quality_result", {}).get("requested_status")
    attempt = state.get("quality_attempt", 0)
    if requested_status == "retry" and attempt == 0:
        status = "retry"
        reasons = ["Quality gate requested one analysis retry."]
    elif requested_status == "retry":
        status = "needs_review"
        reasons = ["Retry limit reached; human review is required."]
    else:
        status = "passed" if has_contract else "needs_review"
        reasons = [] if has_contract else ["Analysis contract is incomplete."]
    quality = {
        "status": status,
        "reasons": reasons,
    }
    return {
        "quality_result": quality,
        "quality_attempt": attempt + 1,
        "completed_nodes": {"quality_gate": True},
    }


def route_quality_result(
    state: ClioState,
) -> Literal["save_analysis", "retry_analysis", "needs_review"]:
    """Quality Gate 결과를 저장 또는 사람 검토 상태로 분기한다."""

    if state["quality_result"]["status"] == "passed":
        return "save_analysis"
    if state["quality_result"]["status"] == "retry":
        return "retry_analysis"
    return "needs_review"


def save_analysis(state: ClioState) -> dict[str, object]:
    """추후 API Server 저장 호출로 교체할 외부 부작용 경계."""

    mock_service.save_analysis(state["project_id"], state["issue_id"])
    return {
        "status": "completed",
        "result": {
            "action": "analysis_completed",
            "issue_id": state["issue_id"],
            "analysis": state["issue_analysis"],
            "resolution_plan": state["resolution_plan"],
            "quality": state["quality_result"],
        },
        "completed_nodes": {"save_analysis": True},
    }


def mark_analysis_for_review(state: ClioState) -> dict[str, object]:
    """Quality Gate가 통과하지 못한 실행을 검토 필요 상태로 남긴다."""

    return {
        "status": "needs_review",
        "result": {
            "action": "analysis_needs_review",
            "issue_id": state["issue_id"],
            "quality": state["quality_result"],
        },
        "completed_nodes": {"mark_analysis_for_review": True},
    }
