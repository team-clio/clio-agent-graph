"""ReportMatcher를 LangGraph의 비교·정책 노드로 연결한다."""

from collections.abc import Callable
from typing import Any, Literal

from clio_agent_graph.workflows.reporting.matching.models import IssueCandidate
from clio_agent_graph.workflows.reporting.matching.service import ReportMatcher
from clio_agent_graph.workflows.reporting.matching.state import ReportMatchingState
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


def route_after_retrieval(state: ReportMatchingState) -> Literal["judge", "policy"]:
    """후보가 없으면 비용이 드는 비교 모델을 건너뛴다."""

    candidates = state.get("issue_candidates", [])
    return "judge" if candidates else "policy"


def create_judge_issue_match_node(
    matcher: ReportMatcher,
) -> Callable[[ReportMatchingState], dict[str, Any]]:
    """후보 전체를 비교하고 결과를 내부 state에 기록하는 노드를 만든다."""

    def judge_issue_match(state: ReportMatchingState) -> dict[str, Any]:
        """state 값을 계약으로 검증한 뒤 비교 서비스를 호출한다."""

        report = NormalizedReport.model_validate(state["normalized_report"])
        candidates = [
            IssueCandidate.model_validate(candidate) for candidate in state["issue_candidates"]
        ]
        comparisons = matcher.compare(report=report, candidates=candidates)
        return {
            "candidate_comparisons": comparisons,
            "matching_tool_calls": matcher.last_tool_calls,
        }

    return judge_issue_match


def create_apply_match_policy_node(
    matcher: ReportMatcher,
) -> Callable[[ReportMatchingState], dict[str, Any]]:
    """비교 결과를 최종 action으로 바꾸는 정책 노드를 만든다."""

    def apply_match_policy(state: ReportMatchingState) -> dict[str, Any]:
        """후보 없음과 후보 비교 완료 상태를 모두 결정 가능한 형태로 조립한다."""

        report = NormalizedReport.model_validate(state["normalized_report"])
        candidates = [
            IssueCandidate.model_validate(candidate)
            for candidate in state.get("issue_candidates", [])
        ]
        comparisons = state.get("candidate_comparisons", [])
        decision = matcher.decide(
            bug_id=state["bug_id"],
            report=report,
            candidates=candidates,
            comparisons=comparisons,
        )
        return {"match_decision": decision}

    return apply_match_policy
