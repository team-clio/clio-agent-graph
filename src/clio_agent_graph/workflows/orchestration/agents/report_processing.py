"""리포트 조사용 LLM Agent."""

import json
from typing import Any

from clio_agent_graph.context.tools.reports import load_report, search_issue_candidates
from clio_agent_graph.runtime.llm import ToolCallingAgent
from clio_agent_graph.workflows.orchestration.agents.models import MatchDecision


class ReportProcessingAgent:
    """읽기 Tool을 호출하고 판단 결과만 반환하는 Agent 경계."""

    def normalize_report(self, project_id: str, report_id: str) -> dict[str, Any]:
        """원본 리포트를 매칭에 사용할 정규화된 입력으로 읽는다."""

        return load_report.invoke({"project_id": project_id, "report_id": report_id})

    def find_candidates(
        self, project_id: str, normalized_report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """정규화된 내용과 유사한 기존 이슈 후보를 조회한다."""

        return search_issue_candidates.invoke(
            {"project_id": project_id, "normalized_report": normalized_report}
        )

    def decide_match(
        self, project_id: str, report_id: str, candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """LLM Tool-calling Agent로 리포트와 후보 이슈의 매칭을 판단한다."""

        llm_result = self.match_agent.invoke(
            "Decide the match for this report. You may call tools for more evidence.\n"
            + json.dumps(
                {"project_id": project_id, "report_id": report_id, "candidates": candidates}
            )
        )
        return llm_result

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
