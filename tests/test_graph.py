from langchain_core.messages import AIMessage, HumanMessage

from clio_agent_graph.graph import graph


def test_graph_accepts_a_chat_message() -> None:
    # 대화 메시지 하나만 들어와도 normalize_request가 요청 문자열을 추출해야 한다.
    result = graph.invoke({"messages": [HumanMessage(content="Analyze an issue")]})

    assert result["request"] == "Analyze an issue"
    assert len(result["plan"]) == 4
    assert isinstance(result["messages"][-1], AIMessage)


def test_graph_honors_max_steps_configuration() -> None:
    # configurable.max_steps가 계획 길이와 완료 단계 수를 함께 제한하는지 확인한다.
    result = graph.invoke(
        {"request": "Prepare a report"},
        {"configurable": {"max_steps": 2}},
    )

    assert len(result["plan"]) == 2
    assert len(result["completed_steps"]) == 2
