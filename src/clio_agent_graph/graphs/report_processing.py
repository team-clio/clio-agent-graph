"""버그 리포트 매칭과 신규 이슈 분석을 연결하는 서브그래프."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.graphs.issue_analysis import build_issue_analysis_graph
from clio_agent_graph.nodes.report_processing import (
    apply_match_decision,
    load_and_normalize_report,
    match_report,
    route_after_match,
    search_issue_candidates,
)
from clio_agent_graph.state import ClioState


def build_report_processing_graph():
    """신규 이슈일 때 동일한 Issue Analysis Graph를 재사용한다."""

    issue_analysis_graph = build_issue_analysis_graph()
    builder = StateGraph(ClioState)
    builder.add_node("load_and_normalize_report", load_and_normalize_report)
    builder.add_node("search_issue_candidates", search_issue_candidates)
    builder.add_node("match_report", match_report)
    builder.add_node("apply_match_decision", apply_match_decision)
    builder.add_node("issue_analysis", issue_analysis_graph)

    builder.add_edge(START, "load_and_normalize_report")
    builder.add_edge("load_and_normalize_report", "search_issue_candidates")
    builder.add_edge("search_issue_candidates", "match_report")
    builder.add_edge("match_report", "apply_match_decision")
    builder.add_conditional_edges(
        "apply_match_decision",
        route_after_match,
        {
            "issue_analysis": "issue_analysis",
            "report_complete": END,
        },
    )
    builder.add_edge("issue_analysis", END)
    return builder.compile()
