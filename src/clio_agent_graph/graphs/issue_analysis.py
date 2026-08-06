"""문서·코드·해결 이력을 병렬 탐색하는 이슈 분석 서브그래프."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.nodes.issue_analysis import (
    analyze_issue,
    mark_analysis_for_review,
    plan_resolution,
    prepare_analysis,
    quality_gate,
    route_quality_result,
    save_analysis,
    search_code,
    search_documents,
    search_history,
)
from clio_agent_graph.state import ClioState


def build_issue_analysis_graph():
    """직접 분석 요청과 신규 이슈 경로가 공유하는 서브그래프를 만든다."""

    builder = StateGraph(ClioState)
    builder.add_node("prepare_analysis", prepare_analysis)
    builder.add_node("search_documents", search_documents)
    builder.add_node("search_code", search_code)
    builder.add_node("search_history", search_history)
    builder.add_node("analyze_issue", analyze_issue)
    builder.add_node("plan_resolution", plan_resolution)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("save_analysis", save_analysis)
    builder.add_node("mark_analysis_for_review", mark_analysis_for_review)

    builder.add_edge(START, "prepare_analysis")
    builder.add_edge("prepare_analysis", "search_documents")
    builder.add_edge("prepare_analysis", "search_code")
    builder.add_edge("prepare_analysis", "search_history")
    # 세 검색이 모두 끝난 뒤에만 하나의 분석 노드를 실행한다.
    builder.add_edge(
        ["search_documents", "search_code", "search_history"],
        "analyze_issue",
    )
    builder.add_edge("analyze_issue", "plan_resolution")
    builder.add_edge("plan_resolution", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        route_quality_result,
        {
            "save_analysis": "save_analysis",
            "retry_analysis": "analyze_issue",
            "needs_review": "mark_analysis_for_review",
        },
    )
    builder.add_edge("save_analysis", END)
    builder.add_edge("mark_analysis_for_review", END)
    return builder.compile()
