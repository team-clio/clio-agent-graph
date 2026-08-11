"""이슈 조사를 위한 LLM Tool-calling Agent."""

import json
from typing import Any

from langchain_core.tools import BaseTool

from clio_agent_graph.runtime.llm import ToolCallingAgent
from clio_agent_graph.workflows.orchestration.agents.models import (
    IssueAnalysisOutput,
    ResolutionPlan,
)


class IssueAnalysisAgent:
    """읽기 Tool만 보유한 조사 Agent; 쓰기 권한은 Graph Node에 남긴다."""

    async def analyze(
        self, issue_id: str, evidence: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """초기 근거를 바탕으로 부족한 부분을 Tool로 보완해 원인을 분석한다."""

        llm_result = await self.analysis_agent.ainvoke(
            "Investigate this issue. Existing evidence is supplied, but use tools when it "
            "is insufficient. Cite every durable claim. For PCM citations, include the "
            "knowledge_id and knowledge_revision returned by tools. For repository citations, "
            "include repository_id, commit, and path from the tool result.\n"
            + json.dumps({"issue_id": issue_id, "evidence": evidence})
        )
        return {"status": "llm", **llm_result}

    async def plan(self, issue_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
        """검증된 분석을 구현·테스트 가능한 해결 단계로 변환한다."""

        llm_result = await self.planning_agent.ainvoke(
            "Create a resolution plan from this issue analysis.\n"
            + json.dumps({"issue_id": issue_id, "analysis": analysis})
        )
        return {"status": "llm", **llm_result}

    def __init__(self, research_tools: list[BaseTool]) -> None:
        self.analysis_agent = ToolCallingAgent(
            name="issue_analyst",
            system_prompt=(
                "You investigate software issues. Use read-only tools to collect enough "
                "evidence before returning facts, hypotheses, and calibrated confidence. "
                "Do not claim unverified facts and do not modify external systems."
            ),
            tools=research_tools,
            response_model=IssueAnalysisOutput,
        )
        self.planning_agent = ToolCallingAgent(
            name="resolution_planner",
            system_prompt=(
                "You create an implementable and testable resolution plan from supplied "
                "issue analysis. Do not modify external systems."
            ),
            tools=research_tools,
            response_model=ResolutionPlan,
        )
