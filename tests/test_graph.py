from langchain_core.messages import AIMessage, HumanMessage

from clio_agent_graph.graph import graph


def test_graph_accepts_a_chat_message() -> None:
    result = graph.invoke({"messages": [HumanMessage(content="Analyze an issue")]})

    assert result["request"] == "Analyze an issue"
    assert len(result["plan"]) == 4
    assert isinstance(result["messages"][-1], AIMessage)


def test_graph_honors_max_steps_configuration() -> None:
    result = graph.invoke(
        {"request": "Prepare a report"},
        {"configurable": {"max_steps": 2}},
    )

    assert len(result["plan"]) == 2
    assert len(result["completed_steps"]) == 2
