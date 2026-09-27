"""문서·코드·해결 이력을 병렬 탐색하는 이슈 분석 서브그래프."""

from functools import partial

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.observability.instrumentation import observe_node
from clio_agent_graph.workflows.orchestration.analysis_profile import (
    AnalysisProfileSettings,
)
from clio_agent_graph.workflows.orchestration.nodes.issue_analysis import (
    analyze_issue,
    assess_risk,
    mark_analysis_for_review,
    plan_resolution,
    prepare_analysis,
    quality_gate,
    route_after_analysis,
    route_quality_result,
    save_analysis,
    search_code,
    search_documents,
    search_history,
)
from clio_agent_graph.workflows.orchestration.state import IssueWorkflowState


def build_issue_analysis_graph(settings: AnalysisProfileSettings | None = None):
    """직접 분석 요청과 신규 이슈 경로가 공유하는 서브그래프를 만든다."""

    selected = settings or AnalysisProfileSettings.from_env()
    topology = selected.topology
    builder = StateGraph(IssueWorkflowState)
    builder.add_node(
        "prepare_analysis",
        observe_node("prepare_analysis", partial(prepare_analysis, settings=selected)),
    )
    if topology.search_documents:
        builder.add_node(
            "search_documents", observe_node("search_documents", search_documents)
        )
    if topology.search_code:
        builder.add_node("search_code", observe_node("search_code", search_code))
    if topology.search_history:
        builder.add_node("search_history", observe_node("search_history", search_history))
    builder.add_node("analyze_issue", observe_node("analyze_issue", analyze_issue))
    builder.add_node("plan_resolution", observe_node("plan_resolution", plan_resolution))
    if topology.quality_gate:
        builder.add_node("quality_gate", observe_node("quality_gate", quality_gate))
    builder.add_node("assess_risk", observe_node("assess_risk", assess_risk))
    builder.add_node("save_analysis", observe_node("save_analysis", save_analysis))
    builder.add_node(
        "mark_analysis_for_review",
        observe_node("mark_analysis_for_review", mark_analysis_for_review),
    )

    builder.add_edge(START, "prepare_analysis")
    search_nodes = [
        name
        for name, enabled in (
            ("search_documents", topology.search_documents),
            ("search_code", topology.search_code),
            ("search_history", topology.search_history),
        )
        if enabled
    ]
    if not search_nodes:
        builder.add_edge("prepare_analysis", "analyze_issue")
    elif len(search_nodes) == 1:
        builder.add_edge("prepare_analysis", search_nodes[0])
        builder.add_edge(search_nodes[0], "analyze_issue")
    else:
        for search_node in search_nodes:
            builder.add_edge("prepare_analysis", search_node)
        builder.add_edge(search_nodes, "analyze_issue")
    builder.add_conditional_edges(
        "analyze_issue",
        route_after_analysis,
        {"plan_resolution": "plan_resolution", "needs_review": "mark_analysis_for_review"},
    )
    if topology.quality_gate:
        builder.add_edge("plan_resolution", "quality_gate")
        builder.add_conditional_edges(
            "quality_gate",
            route_quality_result,
            {
                "save_analysis": "assess_risk",
                "retry_analysis": "analyze_issue",
                "needs_review": "mark_analysis_for_review",
            },
        )
    else:
        builder.add_edge("plan_resolution", "assess_risk")
    builder.add_edge("assess_risk", "save_analysis")
    builder.add_edge("save_analysis", END)
    builder.add_edge("mark_analysis_for_review", END)
    return builder.compile()
