"""버그 리포트 매칭 서브그래프의 노드."""

from typing import Literal

from clio_agent_graph.agents.report_processing import ReportProcessingAgent
from clio_agent_graph.services.mock import mock_service
from clio_agent_graph.state import ClioState

report_agent = ReportProcessingAgent()


def load_and_normalize_report(state: ClioState) -> dict[str, object]:
    """향후 리포트 조회·LLM 정규화를 대체할 결정적 흐름용 구현."""

    normalized = state.get("normalized_report") or report_agent.normalize_report(
        state["project_id"], state["report_id"]
    )
    return {
        "normalized_report": normalized,
        "completed_nodes": {"load_and_normalize_report": True},
    }


def search_issue_candidates(state: ClioState) -> dict[str, object]:
    """향후 RDBMS·Vector 검색을 연결할 후보 검색 경계를 제공한다."""

    return {
        "issue_candidates": state.get("issue_candidates")
        or report_agent.find_candidates(state["project_id"], state["normalized_report"]),
        "completed_nodes": {"search_issue_candidates": True},
    }


def match_report(state: ClioState) -> dict[str, object]:
    """현재 후보 상태를 이용해 그래프 분기를 결정한다.

    실제 의미 기반 동일 이슈 판정은 추후 LLM 구현으로 교체한다.
    """

    decision = report_agent.decide_match(
        state["project_id"], state["report_id"], state.get("issue_candidates", [])
    )
    return {
        "match_decision": decision,
        "completed_nodes": {"match_report": True},
    }


def apply_match_decision(state: ClioState) -> dict[str, object]:
    """Mock Service를 통해 연결·생성·검토 부작용 경계를 호출한다."""

    decision = state["match_decision"]
    action = decision["action"]
    applied = mock_service.apply_match_decision(state["project_id"], state["report_id"], decision)
    if action == "link_existing":
        issue_id = applied["issue_id"]
        return {
            "issue_id": issue_id,
            "status": "completed",
            "result": {
                "action": action,
                "report_id": state["report_id"],
                "issue_id": issue_id,
            },
            "completed_nodes": {"apply_match_decision": True},
        }
    if action == "needs_review":
        return {
            "status": "needs_review",
            "result": {
                "action": action,
                "report_id": state["report_id"],
                "candidate_issue_id": decision.get("issue_id"),
            },
            "completed_nodes": {"apply_match_decision": True},
        }

    issue_id = applied["issue_id"]
    return {
        "issue_id": issue_id,
        "result": {
            "action": "create_new",
            "report_id": state["report_id"],
            "issue_id": issue_id,
        },
        "completed_nodes": {"apply_match_decision": True},
    }


def route_after_match(
    state: ClioState,
) -> Literal["issue_analysis", "report_complete"]:
    """신규 이슈만 재사용 가능한 Issue Analysis Graph로 보낸다."""

    if state["match_decision"]["action"] == "create_new":
        return "issue_analysis"
    return "report_complete"
