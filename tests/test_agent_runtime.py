from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from clio_agent_graph.agent_runtime import StructuredToolAgent


class AgentResult(BaseModel):
    answer: str


class FakeCompiledAgent:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []

    def invoke(self, value: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
        self.inputs.append(value)
        self.configs.append(config)
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lookup_context",
                            "args": {"query": "payment"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ],
            "structured_response": {"answer": "found"},
        }


def test_structured_agent_records_llm_selected_tools(monkeypatch) -> None:
    @tool
    def lookup_context(query: str) -> dict[str, str]:
        """Lookup project context."""

        return {"query": query}

    compiled = FakeCompiledAgent()
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return compiled

    monkeypatch.setattr("clio_agent_graph.agent_runtime.create_agent", fake_create_agent)
    agent = StructuredToolAgent(
        model=object(),
        tools=[lookup_context],
        system_prompt="Investigate the issue.",
        response_model=AgentResult,
        name="test_agent",
    )

    result = agent.invoke("Find the relevant context")

    assert result == AgentResult(answer="found")
    assert agent.last_tool_calls == [
        {
            "name": "lookup_context",
            "arguments": {"query": "payment"},
            "call_id": "call-1",
        }
    ]
    assert captured["tools"] == [lookup_context]
    assert captured["response_format"] is AgentResult
    assert "Decide which of the provided tools" in captured["system_prompt"]
    assert compiled.configs == [{"recursion_limit": 40}]
