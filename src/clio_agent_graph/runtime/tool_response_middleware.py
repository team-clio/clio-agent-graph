"""구조화 출력 재시도에서 실행되지 않은 Tool 호출도 명시적으로 응답한다."""

from dataclasses import replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

NOT_EXECUTED_MESSAGE = (
    "This tool was not executed because a structured output call "
    "was returned in the same response. Call this tool separately "
    "before returning the final structured output."
)
INVALID_ARGUMENTS_MESSAGE = (
    "This tool call was not executed because its arguments were invalid JSON. "
    "Call the tool again with complete, valid JSON arguments."
)


def complete_tool_responses(response: Any) -> Any:
    """혼합 응답의 미실행 호출과 인자 파싱에 실패한 호출을 숨기지 않는다.

    provider는 ``invalid_tool_calls``도 assistant의 ``tool_calls``로 전송받으므로, 응답하지
    않으면 다음 모델 호출이 짝 없는 tool_call id로 거부된다.
    """
    messages = response.result
    answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
    ai_messages = [message for message in messages if isinstance(message, AIMessage)]
    invalid = [
        call
        for message in ai_messages
        for call in message.invalid_tool_calls
        if call["id"] and call["id"] not in answered
    ]
    # 구조화 출력이 처리된 응답에서만 일반 Tool이 실행되지 않고 남는다.
    unexecuted = (
        [
            call
            for message in ai_messages
            for call in message.tool_calls
            if call["id"] not in answered
        ]
        if answered
        else []
    )
    if not invalid and not unexecuted:
        return response
    repaired = {
        "result": [
            *messages,
            *[
                ToolMessage(
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                    content=NOT_EXECUTED_MESSAGE,
                )
                for call in unexecuted
            ],
            # 출력 Tool 이름이 붙은 ToolMessage는 Agent 루프를 종료시키므로 이름을 생략한다.
            *[
                ToolMessage(
                    tool_call_id=call["id"],
                    status="error",
                    content=INVALID_ARGUMENTS_MESSAGE,
                )
                for call in invalid
            ],
        ]
    }
    if unexecuted:
        repaired["structured_response"] = None
    return replace(response, **repaired)


class CompleteToolResponsesMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        return complete_tool_responses(handler(request))

    async def awrap_model_call(self, request, handler):
        return complete_tool_responses(await handler(request))
