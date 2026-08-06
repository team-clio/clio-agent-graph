from langchain_core.messages import AIMessage

from clio_agent_graph.nodes import finalize


def test_returns_result_and_numbered_plan_as_message() -> None:
    result = finalize(
        {
            "result": "Prepared a plan",
            "plan": ["Collect evidence", "Write report"],
        }
    )

    message = result["messages"][0]
    assert isinstance(message, AIMessage)
    assert message.content == ("Prepared a plan\n\nPlan:\n1. Collect evidence\n2. Write report")
