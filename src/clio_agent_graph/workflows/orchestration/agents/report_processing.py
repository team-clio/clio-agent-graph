"""리포트 조사용 LLM Agent."""

import json
from typing import Any

from clio_agent_graph.context.tools.reports import load_report
from clio_agent_graph.runtime.llm import ToolCallingAgent
from clio_agent_graph.workflows.orchestration.agents.models import KoreanIssueDraft, MatchDecision


class ReportProcessingAgent:
    """읽기 Tool을 호출하고 판단 결과만 반환하는 Agent 경계."""

    def normalize_report(self, project_id: str, bug_id: str) -> dict[str, Any]:
        """원본 리포트를 매칭에 사용할 정규화된 입력으로 읽는다."""

        return load_report.invoke({"project_id": project_id, "bug_id": bug_id})

    def decide_match(
        self,
        project_id: str,
        bug_id: str,
        normalized_report: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """정규화된 리포트와 후보 이슈를 비교해 매칭을 판단한다."""

        llm_result = self.match_agent.invoke(
            "Decide the match for this normalized report and its candidates.\n"
            + json.dumps(
                {
                    "project_id": project_id,
                    "bug_id": bug_id,
                    "normalized_report": normalized_report,
                    "candidates": candidates,
                }
            )
        )
        return llm_result

    def draft_issue(self, normalized_report: dict[str, Any]) -> dict[str, Any]:
        """정규화된 Bug 문맥을 신규 Issue의 한국어 title·description으로 변환한다."""

        return self.issue_drafter.invoke(
            "Create a Korean issue draft from this normalized report.\n"
            + json.dumps({"normalized_report": normalized_report})
        )

    def __init__(self) -> None:
        self.match_agent = ToolCallingAgent(
            name="report_matcher",
            system_prompt=(
                "You match a normalized bug report to existing issues. "
                "Never create, link, or modify an issue. "
                "Return create_new when no existing issue is supported, needs_review when "
                "evidence is insufficient, and link_existing only with strong evidence. Write "
                "all user-facing narrative fields in Korean and preserve technical identifiers."
            ),
            tools=[],
            response_model=MatchDecision,
        )
        self.issue_drafter = ToolCallingAgent(
            name="issue_drafter",
            system_prompt=(
                "You write concise Korean software issue content. Return a Korean title of no "
                "more than 200 characters and a detailed Markdown description. The description "
                "must use these headings in this order: ## 증상, ## 기대 동작, ## 재현 절차, "
                "## 영향 범위, ## 오류 신호, ## 조사 메모. Derive content only from the supplied "
                "normalized report; state '정보 없음' when a section is unavailable. Preserve code "
                "identifiers, URLs, error codes, paths, and stack frames exactly as supplied."
            ),
            tools=[],
            response_model=KoreanIssueDraft,
        )
