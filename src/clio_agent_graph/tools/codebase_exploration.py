"""High-level, snapshot-bound codebase exploration tool for issue analysis agents."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from clio_agent_graph.analysis.agentic_explorer import build_agentic_code_exploration_graph
from clio_agent_graph.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    ExplorationRequest,
)
from clio_agent_graph.normalization.models import NormalizedReport
from clio_agent_graph.services.pcm.models import ProjectContextSnapshot
from clio_agent_graph.tools.repository import RepositoryToolFactory


class CodebaseExplorationToolFactory:
    """Expose autonomous evidence exploration without exposing filesystem primitives."""

    def __init__(self, repository_tools: RepositoryToolFactory) -> None:
        self._repository_tools = repository_tools

    def create_tools(self, snapshot: ProjectContextSnapshot) -> list[BaseTool]:
        low_level_tools = self._repository_tools.create_tools(snapshot)
        exploration_graph = build_agentic_code_exploration_graph(tools=low_level_tools)

        @tool
        async def explore_codebase(
            objective: str,
            exploration_context: str | None = None,
        ) -> dict[str, Any]:
            """Autonomously explore snapshot-pinned code and return structured cited evidence.

            Supply the investigation objective and optional prior context only. This tool chooses
            repository listing, file listing, search, and bounded file reads internally.
            """

            request = ExplorationRequest(
                project_id=1,
                issue=AnalysisIssue(issue_id=1, title=objective, summary=exploration_context),
                bugs=[
                    AnalysisBug(
                        bug_id=1,
                        normalized_report=NormalizedReport(
                            bug_report_id=1,
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
