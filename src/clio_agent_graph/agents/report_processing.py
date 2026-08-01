"""리포트 조사용 LLM Agent와 키가 없을 때의 Mock fallback."""

import json
from typing import Any

from clio_agent_graph.agents.models import MatchDecision
from clio_agent_graph.llm import ToolCallingAgent
from clio_agent_graph.tools.reports import load_report, search_issue_candidates


class ReportProcessingAgent:
    """읽기 Tool을 호출하고 판단 결과만 반환하는 Agent 경계."""

    def normalize_report(self, project_id: str, report_id: str) -> dict[str, Any]:
        return load_report.invoke({"project_id": project_id, "report_id": report_id})

    def find_candidates(
        self, project_id: str, normalized_report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return search_issue_candidates.invoke(
            {"project_id": project_id, "normalized_report": normalized_report}
        )

    def decide_match(
        self, project_id: str, report_id: str, candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """LLM이 구성되면 Tool-calling 판단, 아니면 결정적 Mock 판단을 사용한다."""

        llm_result = self.match_agent.invoke(
            "Decide the match for this report. You may call tools for more evidence.\n"
            + json.dumps(
                {"project_id": project_id, "report_id": report_id, "candidates": candidates}
            )
        )
        if llm_result is not None:
            return llm_result

        if not candidates:
            return {
                "action": "create_new",
                "issue_id": None,
                "confidence": 1.0,
                "reason": "No candidate issue was returned by the mock tools.",
            }
        candidate = candidates[0]
        if candidate.get("requires_review"):
            return {
                "action": "needs_review",
                "issue_id": candidate.get("issue_id"),
                "confidence": candidate.get("confidence", 0.0),
                "reason": "The best candidate requires human review.",
            }
        return {
            "action": "link_existing",
            "issue_id": candidate["issue_id"],
            "confidence": candidate.get("confidence", 1.0),
            "reason": "The mock agent selected the first candidate.",
        }

    def __init__(self) -> None:
        self.match_agent = ToolCallingAgent(
            name="report_matcher",
            system_prompt=(
                "You match a bug report to existing issues. Use the read-only tools when "
                "additional evidence is needed. Never create, link, or modify an issue. "
                "Return create_new when no existing issue is supported, needs_review when "
                "evidence is insufficient, and link_existing only with strong evidence."
            ),
            tools=[load_report, search_issue_candidates],
            response_model=MatchDecision,
        )
