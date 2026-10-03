from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from clio_agent_graph.runtime.tool_response_middleware import complete_tool_responses


def test_mixed_structured_output_reports_unexecuted_calls_before_retry():
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "read", "name": "read_file", "args": {}},
            {"id": "output", "name": "Result", "args": {}},
        ],
    )
    response = ModelResponse(
        result=[
            message,
            ToolMessage(content="Invalid structured output", tool_call_id="output", name="Result"),
        ]
    )
    repaired = complete_tool_responses(response)
    assert [m.tool_call_id for m in repaired.result if isinstance(m, ToolMessage)] == [
        "output",
        "read",
    ]
    assert repaired.result[-1].status == "error"
    assert "not executed" in repaired.result[-1].content
    assert repaired.structured_response is None


def test_ordinary_pending_tool_calls_are_executed_by_the_agent():
    response = ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "read", "name": "read_file", "args": {}},
                ],
            )
        ]
    )
    assert complete_tool_responses(response) is response
