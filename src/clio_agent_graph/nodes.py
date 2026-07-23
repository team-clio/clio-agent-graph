"""Small, independently testable graph nodes.

The deterministic implementation keeps local development operational without
credentials. Replace ``plan_request`` and ``execute_plan`` with model/tool-backed
implementations while preserving their state contracts.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from clio_agent_graph.configuration import GraphConfig
from clio_agent_graph.state import ClioState


def normalize_request(state: ClioState) -> dict[str, str]:
    """Extract the most recent human request into a stable state field."""

    request = state.get("request", "").strip()
    if not request:
        for message in reversed(state.get("messages", [])):
            if isinstance(message, HumanMessage) and isinstance(message.content, str):
                request = message.content.strip()
                break

    if not request:
        raise ValueError("A non-empty request or human message is required.")
    return {"request": request}


def plan_request(state: ClioState, config: RunnableConfig) -> dict[str, list[str]]:
    """Create a bounded starter plan.

    This is the intended seam for an LLM structured-output planner.
    """

    graph_config = GraphConfig.from_runnable_config(config)
    steps = [
        f"Clarify the expected outcome for: {state['request']}",
        "Collect the minimum evidence and repository context",
        "Perform the requested work",
        "Verify the result and report remaining risks",
    ]
    return {"plan": steps[: graph_config.max_steps]}


def execute_plan(state: ClioState) -> dict[str, object]:
    """Execute the placeholder workflow and expose an integration seam for tools."""

    completed = [f"Prepared: {step}" for step in state["plan"]]
    result = f"Prepared an execution plan with {len(completed)} step(s) for: {state['request']}"
    return {"completed_steps": completed, "result": result, "error": None}


def finalize(state: ClioState) -> dict[str, list[AIMessage]]:
    """Return a chat-compatible response for Agent Server clients."""

    lines = [state["result"], "", "Plan:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(state["plan"], start=1))
    return {"messages": [AIMessage(content="\n".join(lines))]}
