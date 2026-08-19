"""버그 리포트 매칭과 신규 이슈 분석을 연결하는 서브그래프."""

import asyncio
import logging

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from clio_agent_graph.workflows.orchestration.graphs.issue_analysis import (
    build_issue_analysis_graph,
)
from clio_agent_graph.workflows.orchestration.nodes.report_processing import (
    apply_match_decision,
    complete_workflow,
    fail_workflow,
    index_normalized_report,
    load_and_normalize_report,
    match_report,
    route_after_match,
    route_after_match_application,
    route_after_workflow_start,
    search_issue_candidates,
    start_workflow,
)
from clio_agent_graph.workflows.orchestration.state import ReportWorkflowState

logger = logging.getLogger(__name__)


def build_report_processing_graph():
    """신규 이슈일 때 동일한 Issue Analysis Graph를 재사용한다."""

    issue_analysis_graph = build_issue_analysis_graph()
    processing = StateGraph(ReportWorkflowState)
    processing.add_node("load_and_normalize_report", load_and_normalize_report)
    processing.add_node("search_issue_candidates", search_issue_candidates)
    processing.add_node("match_report", match_report)
    processing.add_node("apply_match_decision", apply_match_decision)
    processing.add_node("issue_analysis", issue_analysis_graph)
    processing.add_node("index_normalized_report", index_normalized_report)

    processing.add_edge(START, "load_and_normalize_report")
    processing.add_edge("load_and_normalize_report", "search_issue_candidates")
    processing.add_edge("search_issue_candidates", "match_report")
    processing.add_conditional_edges(
        "match_report",
        route_after_match,
        {
            "index_report": "index_normalized_report",
            "report_complete": "apply_match_decision",
        },
    )
    processing.add_edge("index_normalized_report", "apply_match_decision")
    processing.add_conditional_edges(
        "apply_match_decision",
        route_after_match_application,
        {"issue_analysis": "issue_analysis", "report_complete": END},
    )
    processing.add_edge("issue_analysis", END)
    processing_graph = processing.compile()

    def mark_failed(state: ReportWorkflowState, error: Exception) -> None:
        try:
            fail_workflow(state, error)
        except Exception:
            logger.exception(
                "Failed to record workflow failure. project_id=%s workflow_run_id=%s",
                state.get("project_id"),
                state.get("workflow_run_id"),
            )

    def run_processing(state: ReportWorkflowState) -> dict[str, object]:
        try:
            return asyncio.run(processing_graph.ainvoke(state))
        except Exception as error:
            mark_failed(state, error)
            raise

    async def arun_processing(state: ReportWorkflowState) -> dict[str, object]:
        try:
            return await processing_graph.ainvoke(state)
        except Exception as error:
            mark_failed(state, error)
            raise

    builder = StateGraph(ReportWorkflowState)
    builder.add_node("start_workflow", start_workflow)
    builder.add_node("run_processing", RunnableLambda(run_processing, arun_processing))
    builder.add_node("complete_workflow", complete_workflow)
    builder.add_edge(START, "start_workflow")
    builder.add_conditional_edges(
        "start_workflow",
        route_after_workflow_start,
        {"process": "run_processing", "replayed": END},
    )
    builder.add_edge("run_processing", "complete_workflow")
    builder.add_edge("complete_workflow", END)
    return builder.compile()
