"""버그 리포트 매칭 서브그래프의 노드."""

from typing import Literal

from clio_agent_graph.state import ClioState


def load_and_normalize_report(state: ClioState) -> dict[str, object]:
    """향후 리포트 조회·LLM 정규화를 대체할 결정적 흐름용 구현."""

    normalized = state.get(
        "normalized_report",
        {
            "report_id": state["report_id"],
            "symptom": "context service and LLM integration pending",
            "evidence": [],
        },
    )
    return {
        "normalized_report": normalized,
        "completed_nodes": {"load_and_normalize_report": True},
    }


def search_issue_candidates(state: ClioState) -> dict[str, object]:
    """향후 RDBMS·Vector 검색을 연결할 후보 검색 경계를 제공한다."""

    return {
        "issue_candidates": state.get("issue_candidates", []),
        "completed_nodes": {"search_issue_candidates": True},
    }


def match_report(state: ClioState) -> dict[str, object]:
    """현재 후보 상태를 이용해 그래프 분기를 결정한다.

    실제 의미 기반 동일 이슈 판정은 추후 LLM 구현으로 교체한다.
    """

    candidates = state.get("issue_candidates", [])
    if not candidates:
        decision = {
            "action": "create_new",
            "issue_id": None,
            "confidence": 1.0,
            "reason": "No candidate issue was supplied by the placeholder search.",
        }
    elif candidates[0].get("requires_review"):
        decision = {
            "action": "needs_review",
            "issue_id": candidates[0].get("issue_id"),
            "confidence": candidates[0].get("confidence", 0.0),
            "reason": "The best candidate requires human review.",
        }
    else:
        decision = {
            "action": "link_existing",
            "issue_id": candidates[0]["issue_id"],
            "confidence": candidates[0].get("confidence", 1.0),
            "reason": "The placeholder matcher selected the first candidate.",
        }
    return {
        "match_decision": decision,
        "completed_nodes": {"match_report": True},
    }


def apply_match_decision(state: ClioState) -> dict[str, object]:
    """연결·생성·검토라는 외부 부작용의 단일 경계를 표현한다."""

    decision = state["match_decision"]
    action = decision["action"]
    if action == "link_existing":
        issue_id = decision["issue_id"]
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

    issue_id = f"ISSUE-FROM-{state['report_id']}"
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
