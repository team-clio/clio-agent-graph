"""LangGraph Agent Server에 노출할 컴파일된 그래프 정의."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.nodes import execute_plan, finalize, normalize_request, plan_request
from clio_agent_graph.state import ClioState


def build_graph():
    """테스트마다 새 인스턴스를 만들 수 있도록 그래프 조립을 분리한다."""

    # 상태 스키마를 먼저 고정해 두면 각 노드가 어떤 키를 읽고 쓰는지 명확해진다.
    builder = StateGraph(ClioState)
    # 각 노드는 요청 정규화 → 계획 수립 → 실행 → 응답 생성 순서로 이어진다.
    builder.add_node("normalize_request", normalize_request)
    builder.add_node("plan_request", plan_request)
    builder.add_node("execute_plan", execute_plan)
    builder.add_node("finalize", finalize)

    # 시작점과 종료점을 명시적으로 연결해 두면 그래프 흐름을 한눈에 읽을 수 있다.
    builder.add_edge(START, "normalize_request")
    builder.add_edge("normalize_request", "plan_request")
    builder.add_edge("plan_request", "execute_plan")
    builder.add_edge("execute_plan", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


# Agent Server는 이 모듈 전역의 `graph` 객체를 진입점으로 사용한다.
graph = build_graph()
