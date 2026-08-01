"""이슈 분석 서브그래프의 흐름용 노드."""

from typing import Literal

from clio_agent_graph.state import ClioState


def prepare_analysis(state: ClioState) -> dict[str, object]:
    """이슈와 고정된 컨텍스트 snapshot 및 검색 질의를 준비한다."""

    snapshot = state.get(
        "context_snapshot",
        {
            "status": "not_connected",
            "document_revision": None,
            "repository_revisions": {},
        },
    )
    queries = state.get(
        "analysis_queries",
        {
            "documents": [state["issue_id"]],
            "code": [state["issue_id"]],
            "history": [state["issue_id"]],
        },
    )
    return {
        "context_snapshot": snapshot,
        "analysis_queries": queries,
        "completed_nodes": {"prepare_analysis": True},
    }


def search_documents(state: ClioState) -> dict[str, object]:
    """ProjectContextService.search_documents의 추후 연결 지점."""

    return {
        "document_evidence": state.get("document_evidence", []),
        "completed_nodes": {"search_documents": True},
    }


def search_code(state: ClioState) -> dict[str, object]:
    """ProjectContextService.search_code의 추후 연결 지점."""

    return {
        "code_evidence": state.get("code_evidence", []),
        "completed_nodes": {"search_code": True},
    }


def search_history(state: ClioState) -> dict[str, object]:
    """ProjectContextService.search_resolution_history의 추후 연결 지점."""

    return {
        "history_evidence": state.get("history_evidence", []),
        "completed_nodes": {"search_history": True},
    }


def analyze_issue(state: ClioState) -> dict[str, object]:
    """세 검색 결과가 합류한 뒤 실행되는 분석 노드의 계약을 제공한다."""

    analysis = {
        "issue_id": state["issue_id"],
        "status": "placeholder",
        "evidence_counts": {
            "documents": len(state.get("document_evidence", [])),
            "code": len(state.get("code_evidence", [])),
            "history": len(state.get("history_evidence", [])),
        },
        "root_cause_hypotheses": [],
    }
    return {
        "issue_analysis": analysis,
        "completed_nodes": {"analyze_issue": True},
    }


def plan_resolution(state: ClioState) -> dict[str, object]:
    """추후 LLM structured output으로 교체할 해결 계획 경계."""

    return {
        "resolution_plan": {
            "issue_id": state["issue_id"],
            "status": "placeholder",
            "steps": [],
            "acceptance_criteria": [],
        },
        "completed_nodes": {"plan_resolution": True},
    }


def quality_gate(state: ClioState) -> dict[str, object]:
    """현재 placeholder 산출물의 구조를 확인하고 저장 경로로 보낸다."""

    has_contract = "issue_analysis" in state and "resolution_plan" in state
    quality = {
        "status": "passed" if has_contract else "needs_review",
        "reasons": [] if has_contract else ["Analysis contract is incomplete."],
    }
    return {
        "quality_result": quality,
        "completed_nodes": {"quality_gate": True},
    }


def route_quality_result(
    state: ClioState,
) -> Literal["save_analysis", "needs_review"]:
    """Quality Gate 결과를 저장 또는 사람 검토 상태로 분기한다."""

    if state["quality_result"]["status"] == "passed":
        return "save_analysis"
    return "needs_review"


def save_analysis(state: ClioState) -> dict[str, object]:
    """추후 API Server 저장 호출로 교체할 외부 부작용 경계."""

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
