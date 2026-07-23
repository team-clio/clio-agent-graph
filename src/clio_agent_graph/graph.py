"""Compiled graph exported to the LangGraph Agent Server."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.nodes import execute_plan, finalize, normalize_request, plan_request
from clio_agent_graph.state import ClioState


def build_graph():
    """Build the graph separately so tests can compile a fresh instance."""

    builder = StateGraph(ClioState)
    builder.add_node("normalize_request", normalize_request)
    builder.add_node("plan_request", plan_request)
    builder.add_node("execute_plan", execute_plan)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "normalize_request")
    builder.add_edge("normalize_request", "plan_request")
    builder.add_edge("plan_request", "execute_plan")
    builder.add_edge("execute_plan", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


graph = build_graph()
