from clio_agent_graph.nodes import plan_request


def test_limits_plan_to_configured_max_steps() -> None:
    result = plan_request(
        {"request": "Prepare a report"},
        {"configurable": {"max_steps": 2}},
    )

    assert len(result["plan"]) == 2
    assert "Prepare a report" in result["plan"][0]
