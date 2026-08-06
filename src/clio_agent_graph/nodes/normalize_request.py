"""사용자 요청 정규화 노드."""

from langchain_core.messages import HumanMessage

from clio_agent_graph.state import ClioState


def normalize_request(state: ClioState) -> dict[str, str]:
    """입력 상태에서 가장 최근 사용자 요청을 꺼내 공통 필드로 정규화한다."""

    # API 호출자가 request 필드를 직접 넘긴 경우를 가장 우선한다.
    request = state.get("request", "").strip()
    if not request:
        # request가 비어 있으면 대화 이력에서 마지막 사람 메시지를 찾아 보강한다.
        for message in reversed(state.get("messages", [])):
            if isinstance(message, HumanMessage) and isinstance(message.content, str):
                request = message.content.strip()
                break

    if not request:
        raise ValueError("A non-empty request or human message is required.")
    return {"request": request}
