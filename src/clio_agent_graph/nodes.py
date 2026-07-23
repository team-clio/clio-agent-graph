"""작게 나뉜 그래프 노드 모음.

로컬 개발 환경에서도 바로 동작하도록 결정적 로직만 사용한다.
실제 모델/도구 연동으로 교체하더라도 상태 계약은 그대로 유지하는 것이 핵심이다.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from clio_agent_graph.configuration import GraphConfig
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


def plan_request(state: ClioState, config: RunnableConfig) -> dict[str, list[str]]:
    """요청을 작고 검증 가능한 초기 실행 계획으로 바꾼다."""

    graph_config = GraphConfig.from_runnable_config(config)
    # 아직 LLM을 붙이지 않았기 때문에 항상 같은 뼈대 계획을 만든다.
    steps = [
        f"Clarify the expected outcome for: {state['request']}",
        "Collect the minimum evidence and repository context",
        "Perform the requested work",
        "Verify the result and report remaining risks",
    ]
    # 실행별 설정으로 최대 단계 수만 잘라 내면 테스트가 단순해진다.
    return {"plan": steps[: graph_config.max_steps]}


def execute_plan(state: ClioState) -> dict[str, object]:
    """임시 실행 로직을 돌려 후속 도구 연동 지점을 드러낸다."""

    # 실제 작업 대신 각 단계를 준비 완료 상태로 표기해 그래프 연결만 검증한다.
    completed = [f"Prepared: {step}" for step in state["plan"]]
    result = f"Prepared an execution plan with {len(completed)} step(s) for: {state['request']}"
    return {"completed_steps": completed, "result": result, "error": None}


def finalize(state: ClioState) -> dict[str, list[AIMessage]]:
    """최종 상태를 Agent Server가 바로 돌려줄 채팅 메시지로 변환한다."""

    # 사람이 읽기 쉬운 요약과 계획 목록을 하나의 AIMessage로 묶어 반환한다.
    lines = [state["result"], "", "Plan:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(state["plan"], start=1))
    return {"messages": [AIMessage(content="\n".join(lines))]}
