import pytest
from langchain_core.tools import tool

from clio_agent_graph.analysis.models import ExplorationResponse
from clio_agent_graph.services.pcm.models import ProjectContextSnapshot
from clio_agent_graph.tools.codebase_exploration import CodebaseExplorationToolFactory


class _RepositoryTools:
    def create_tools(self, snapshot: ProjectContextSnapshot):
        @tool
        async def list_project_repositories() -> dict[str, object]:
            """List repositories."""

            return {"repositories": []}

        return [list_project_repositories]


def test_explore_codebase_hides_low_level_tool_inputs() -> None:
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
    )

    tool_instance = CodebaseExplorationToolFactory(_RepositoryTools()).create_tools(snapshot)[0]

    assert tool_instance.name == "explore_codebase"
    assert set(tool_instance.args_schema.model_json_schema()["properties"]) == {
        "objective",
        "exploration_context",
    }


@pytest.mark.asyncio
async def test_explore_codebase_returns_explorer_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Graph:
        async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
            captured.update(state)
            return {
                "exploration_response": ExplorationResponse(),
                "exploration_tool_calls": [{"name": "list_project_repositories", "args": {}}],
            }

    monkeypatch.setattr(
        "clio_agent_graph.tools.codebase_exploration.build_agentic_code_exploration_graph",
        lambda *, tools: _Graph(),
    )
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
    )
    tool_instance = CodebaseExplorationToolFactory(_RepositoryTools()).create_tools(snapshot)[0]

    result = await tool_instance.ainvoke(
        {"objective": "Find the authorization check.", "exploration_context": "Admins fail."}
    )

    request = captured["exploration_request"]
    assert request["issue"]["title"] == "Find the authorization check."
    assert request["issue"]["summary"] == "Admins fail."
    assert result == {
        "evidence": {"candidates": [], "relations": []},
        "tool_calls": [{"name": "list_project_repositories", "args": {}}],
    }
