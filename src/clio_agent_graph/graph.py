"""LangGraph Agent Server에 노출할 Clio Root Graph."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.graphs import (
    build_issue_analysis_graph,
    build_report_processing_graph,
)
from clio_agent_graph.nodes.common import (
    finalize_request,
    route_request,
    validate_request,
)
from clio_agent_graph.state import ClioState


def build_graph():
    """요청 type으로 결정적으로 서브그래프를 선택하는 Root Graph를 만든다."""

    report_processing_graph = build_report_processing_graph()
    issue_analysis_graph = build_issue_analysis_graph()

    builder = StateGraph(ClioState)
    builder.add_node("validate_request", validate_request)
    builder.add_node("report_processing", report_processing_graph)
    builder.add_node("issue_analysis", issue_analysis_graph)
    builder.add_node("finalize_request", finalize_request)

    builder.add_edge(START, "validate_request")
    builder.add_conditional_edges(
        "validate_request",
        route_request,
        {
            "report_processing": "report_processing",
            "issue_analysis": "issue_analysis",
        },
    )
    builder.add_edge("report_processing", "finalize_request")
    builder.add_edge("issue_analysis", "finalize_request")
    builder.add_edge("finalize_request", END)
    return builder.compile()


# langgraph.json이 이 객체를 Agent Server 진입점으로 사용한다.
graph = build_graph()
