from typing import Any

from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel

from clio_agent_graph.structured_output import bind_structured_output, tool_strategy


class ExampleResult(BaseModel):
    value: int


def test_structured_output_uses_portable_function_calling() -> None:
    captured: dict[str, Any] = {}

    class FakeModel:
        def with_structured_output(self, schema: type, *, method: str) -> object:
            captured.update(schema=schema, method=method)
            return object()

    result = bind_structured_output(FakeModel(), ExampleResult)

    assert result is not None
    assert captured == {"schema": ExampleResult, "method": "function_calling"}


def test_agent_response_uses_portable_tool_strategy() -> None:
    assert isinstance(tool_strategy(ExampleResult), ToolStrategy)
