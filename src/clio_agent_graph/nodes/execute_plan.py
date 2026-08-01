"""실행 계획 처리 노드."""

from clio_agent_graph.state import ClioState


def execute_plan(state: ClioState) -> dict[str, object]:
    """임시 실행 로직을 돌려 후속 도구 연동 지점을 드러낸다."""

    # 실제 작업 대신 각 단계를 준비 완료 상태로 표기해 그래프 연결만 검증한다.
    completed = [f"Prepared: {step}" for step in state["plan"]]
    result = f"Prepared an execution plan with {len(completed)} step(s) for: {state['request']}"
    return {"completed_steps": completed, "result": result, "error": None}
