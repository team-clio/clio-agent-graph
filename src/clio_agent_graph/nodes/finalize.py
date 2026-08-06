"""최종 응답 생성 노드."""

from langchain_core.messages import AIMessage

from clio_agent_graph.state import ClioState


def finalize(state: ClioState) -> dict[str, list[AIMessage]]:
    """최종 상태를 Agent Server가 바로 돌려줄 채팅 메시지로 변환한다."""

    # 사람이 읽기 쉬운 요약과 계획 목록을 하나의 AIMessage로 묶어 반환한다.
    lines = [state["result"], "", "Plan:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(state["plan"], start=1))
    return {"messages": [AIMessage(content="\n".join(lines))]}
