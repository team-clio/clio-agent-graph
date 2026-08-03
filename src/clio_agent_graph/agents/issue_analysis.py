"""이슈 조사를 위한 LLM Tool-calling Agent."""

import json
from typing import Any, Literal

from clio_agent_graph.agents.models import IssueAnalysisOutput, ResolutionPlan
from clio_agent_graph.llm import ToolCallingAgent
from clio_agent_graph.tools.context import (
    resolve_project_snapshot,
    search_code_evidence,
    search_document_evidence,
    search_resolution_history,
)


class IssueAnalysisAgent:
    """읽기 Tool만 보유한 조사 Agent; 쓰기 권한은 Graph Node에 남긴다."""

    def prepare(
        self, project_id: str, issue_id: str
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        snapshot = resolve_project_snapshot.invoke({"project_id": project_id})
        queries = {"documents": [issue_id], "code": [issue_id], "history": [issue_id]}
        return snapshot, queries

    def search(
        self, source: Literal["documents", "code", "history"], project_id: str, queries: list[str]
    ) -> list[dict[str, Any]]:
        tools = {
            "documents": search_document_evidence,
            "code": search_code_evidence,
            "history": search_resolution_history,
        }
        return tools[source].invoke({"project_id": project_id, "queries": queries})

    def analyze(self, issue_id: str, evidence: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        llm_result = self.analysis_agent.invoke(
            "Investigate this issue. Existing evidence is supplied, but use tools when it "
            "is insufficient.\n" + json.dumps({"issue_id": issue_id, "evidence": evidence})
        )
        return {"status": "llm", **llm_result}

    def plan(self, issue_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
        llm_result = self.planning_agent.invoke(
            "Create a resolution plan from this issue analysis.\n"
            + json.dumps({"issue_id": issue_id, "analysis": analysis})
        )
        return {"status": "llm", **llm_result}

    def __init__(self) -> None:
        research_tools = [
            resolve_project_snapshot,
            search_document_evidence,
            search_code_evidence,
            search_resolution_history,
        ]
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
