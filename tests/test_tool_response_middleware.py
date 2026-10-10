from langchain.agents.middleware import ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_openai.chat_models.base import _convert_message_to_dict
from pydantic import BaseModel

from clio_agent_graph.runtime import llm
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


def test_invalid_tool_calls_are_answered_so_the_next_request_stays_valid():
    response = ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[{"id": "read", "name": "read_file", "args": {}}],
                invalid_tool_calls=[
                    {"id": "broken", "name": "Result", "args": '{"answer": "tru', "error": None}
                ],
            )
        ]
    )
    repaired = complete_tool_responses(response)
    tool_messages = [m for m in repaired.result if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_messages] == ["broken"]
    assert tool_messages[0].status == "error"
    assert "invalid JSON" in tool_messages[0].content


def test_agent_recovers_when_model_mixes_valid_and_invalid_tool_calls(monkeypatch):
    requests: list[list[dict]] = []

    class Result(BaseModel):
        answer: str

    @tool
    def read_file(path: str) -> str:
        """Read a file."""
        return "content"

    class ScriptedChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            requests.append([_convert_message_to_dict(m) for m in messages])
            if len(requests) == 1:
                message = AIMessage(
                    content="",
                    tool_calls=[{"id": "read", "name": "read_file", "args": {"path": "a"}}],
                    invalid_tool_calls=[
                        {"id": "broken", "name": "Result", "args": '{"answer": "tru', "error": None}
                    ],
                )
            else:
                message = AIMessage(
                    content="",
                    tool_calls=[{"id": "final", "name": "Result", "args": {"answer": "done"}}],
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

    monkeypatch.setattr(llm, "build_chat_model", ScriptedChatModel)
    agent = llm.ToolCallingAgent(
        name="test", system_prompt="test", tools=[read_file], response_model=Result
    )

    assert agent.invoke("investigate") == {"answer": "done"}
    second_request = requests[1]
    sent = [
        call["id"]
        for message in second_request
        if message["role"] == "assistant"
        for call in message.get("tool_calls", [])
    ]
    answered = {m["tool_call_id"] for m in second_request if m["role"] == "tool"}
    assert set(sent) <= answered


def test_valid_structured_output_is_kept_when_another_call_has_invalid_arguments():
    response = ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[{"id": "output", "name": "Result", "args": {}}],
                invalid_tool_calls=[
                    {"id": "broken", "name": "read_file", "args": "{", "error": None}
                ],
            ),
            ToolMessage(content="Returning structured response", tool_call_id="output"),
        ],
        structured_response={"answer": "done"},
    )
    repaired = complete_tool_responses(response)
    assert [m.tool_call_id for m in repaired.result if isinstance(m, ToolMessage)] == [
        "output",
        "broken",
    ]
    assert repaired.structured_response == {"answer": "done"}
