"""이슈 분석 Agent에 snapshot-bound 코드 탐색을 제공하는 상위 Tool."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from clio_agent_graph.context.pcm.models import ProjectContextSnapshot
from clio_agent_graph.context.tools.repository import RepositoryToolFactory
from clio_agent_graph.workflows.analysis.agentic_explorer import (
    build_agentic_code_exploration_graph,
)
from clio_agent_graph.workflows.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    ExplorationRequest,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


class CodebaseExplorationToolFactory:
    """파일시스템 원시 기능을 숨기고 자율적인 근거 탐색만 노출한다."""

    def __init__(self, repository_tools: RepositoryToolFactory) -> None:
        self._repository_tools = repository_tools

    def create_tools(self, snapshot: ProjectContextSnapshot) -> list[BaseTool]:
        """저수준 Repository Tool을 내부 탐색 Agent 하나로 감싸서 반환한다."""

        low_level_tools = self._repository_tools.create_tools(snapshot)
        exploration_graph = build_agentic_code_exploration_graph(tools=low_level_tools)

        @tool
        async def explore_codebase(
            objective: str,
            exploration_context: str | None = None,
        ) -> dict[str, Any]:
            """고정된 코드 snapshot을 자율 조사해 인용 가능한 구조화 근거를 반환한다.

            호출자는 조사 목적과 선택적인 선행 맥락만 제공한다. Repository·파일 목록,
            검색, 제한된 파일 읽기 중 어떤 기능을 쓸지는 내부 탐색 Agent가 결정한다.
            """

            request = ExplorationRequest(
                project_id=1,
                issue=AnalysisIssue(issue_id=1, title=objective, summary=exploration_context),
                bugs=[
                    AnalysisBug(
                        bug_id=1,
                        normalized_report=NormalizedReport(
                            bug_id=1,
                            observed_behavior=objective,
                        ),
                    )
                ],
                questions=[objective],
            )
            result = await exploration_graph.ainvoke(
                {"exploration_request": request.model_dump(mode="json")}
            )
            response = result["exploration_response"]
            return {
                "evidence": response.model_dump(mode="json"),
                "tool_calls": result.get("exploration_tool_calls", []),
            }

        return [explore_codebase]
