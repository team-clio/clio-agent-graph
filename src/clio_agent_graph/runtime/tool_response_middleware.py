"""구조화 출력 재시도에서 실행되지 않은 Tool 호출도 명시적으로 응답한다."""

from dataclasses import replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage


def complete_tool_responses(response: Any) -> Any:
    """일반 Tool과 출력 Tool의 혼합 응답에서 미실행 호출을 숨기지 않는다."""
    messages = response.result
    if not any(isinstance(message, ToolMessage) for message in messages):
        return response
    answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
    missing = [
        call
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["id"] not in answered
    ]
    if not missing:
        return response
    return replace(
        response,
        **{
            "result": [
                *messages,
                *[
                    ToolMessage(
                        tool_call_id=call["id"],
                        name=call["name"],
                        status="error",
                        content=(
                            "This tool was not executed because a structured output call "
                            "was returned in the same response. Call this tool separately "
                            "before returning the final structured output."
                        ),
                    )
                    for call in missing
                ],
            ],
            "structured_response": None,
        },
    )


class CompleteToolResponsesMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        return complete_tool_responses(handler(request))

    async def awrap_model_call(self, request, handler):
        return complete_tool_responses(await handler(request))
