"""LangGraph Agent Server에 노출할 Clio 도메인 그래프."""

import os
from typing import Any

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.matching.defaults import load_default_issue_match_model
from clio_agent_graph.matching.models import MatchPolicySettings
from clio_agent_graph.matching.node import (
    create_apply_match_policy_node,
    create_judge_issue_match_node,
    route_after_retrieval,
)
from clio_agent_graph.matching.ports import IssueMatchModel
from clio_agent_graph.matching.retrieval_subgraph import (
    build_issue_retrieval_subgraph,
)
from clio_agent_graph.matching.service import ReportMatcher, load_match_policy_settings
from clio_agent_graph.normalization.defaults import load_default_normalization_model
from clio_agent_graph.normalization.node import create_normalize_report_node
from clio_agent_graph.normalization.ports import NormalizationModel
from clio_agent_graph.normalization.service import (
    DEFAULT_MAX_RAW_PAYLOAD_BYTES,
    ReportNormalizer,
)
from clio_agent_graph.state import ClioInput, ClioOutput, ClioState


def build_graph(
    model: NormalizationModel | None = None,
    *,
    max_raw_payload_bytes: int | None = None,
    retrieval_subgraph: Any | None = None,
    match_model: IssueMatchModel | None = None,
    match_policy: MatchPolicySettings | None = None,
):
    """주입 가능한 NM·RAG·RM 구성요소로 Clio 도메인 그래프를 만든다."""

    # `or` 대신 명시적인 None 검사를 사용해 False처럼 평가되는 테스트 객체도 그대로 보존한다.
    normalization_model = model if model is not None else load_default_normalization_model()
    payload_limit = (
        max_raw_payload_bytes
        if max_raw_payload_bytes is not None
        else int(os.getenv("CLIO_MAX_RAW_PAYLOAD_BYTES", DEFAULT_MAX_RAW_PAYLOAD_BYTES))
    )
    normalizer = ReportNormalizer(
        normalization_model,
        max_raw_payload_bytes=payload_limit,
    )
    issue_retrieval_graph = (
        retrieval_subgraph if retrieval_subgraph is not None else build_issue_retrieval_subgraph()
    )
    issue_match_model = match_model if match_model is not None else load_default_issue_match_model()
    policy_settings = match_policy if match_policy is not None else load_match_policy_settings()
    matcher = ReportMatcher(issue_match_model, settings=policy_settings)

    # input/output schema를 분리하면 내부 state가 늘어나도 공개 API 필드는 안정적으로 유지된다.
    builder = StateGraph(
        ClioState,
        input_schema=ClioInput,
        output_schema=ClioOutput,
    )
    builder.add_node("normalize_report", create_normalize_report_node(normalizer))
    # 컴파일된 LangGraph를 노드로 추가하면 해당 그래프가 하위 에이전트처럼 실행된다.
    builder.add_node("issue_retrieval_subgraph", issue_retrieval_graph)
    builder.add_node("judge_issue_match", create_judge_issue_match_node(matcher))
    builder.add_node("apply_match_policy", create_apply_match_policy_node(matcher))
    builder.add_edge(START, "normalize_report")
    builder.add_edge("normalize_report", "issue_retrieval_subgraph")
    builder.add_conditional_edges(
        "issue_retrieval_subgraph",
        route_after_retrieval,
        {
            "judge": "judge_issue_match",
            "policy": "apply_match_policy",
        },
    )
    builder.add_edge("judge_issue_match", "apply_match_policy")
    builder.add_edge("apply_match_policy", END)
    return builder.compile()


# Agent Server는 이 모듈 전역의 `graph`를 읽는다. 실제 chat model은 첫 invoke까지 생성되지 않는다.
graph = build_graph()
