from clio_agent_graph.nodes import execute_plan


def test_marks_each_plan_step_as_prepared() -> None:
    result = execute_plan(
        {
            "request": "Prepare a report",
            "plan": ["Collect evidence", "Write report"],
        }
    )

    assert result["completed_steps"] == [
        "Prepared: Collect evidence",
        "Prepared: Write report",
    ]
    assert result["error"] is None
