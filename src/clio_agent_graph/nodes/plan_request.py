"""실행 계획 생성 노드."""

from langchain_core.runnables import RunnableConfig

from clio_agent_graph.configuration import GraphConfig
from clio_agent_graph.state import ClioState


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
