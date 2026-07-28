"""LangGraph Agent Server에 노출할 Clio 도메인 그래프."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.normalization.langchain_adapter import LangChainNormalizationModel
from clio_agent_graph.normalization.node import create_normalize_report_node
from clio_agent_graph.normalization.ports import NormalizationModel
from clio_agent_graph.normalization.service import ReportNormalizer
from clio_agent_graph.state import ClioInput, ClioOutput, ClioState


def build_graph(model: NormalizationModel | None = None):
    """주입된 모델로 NM 그래프를 만들며, 생략하면 실제 LangChain adapter를 사용한다."""

    # `or` 대신 명시적인 None 검사를 사용해 False처럼 평가되는 테스트 객체도 그대로 보존한다.
    normalization_model = model if model is not None else LangChainNormalizationModel()
    normalizer = ReportNormalizer(normalization_model)

    # input/output schema를 분리하면 내부 state가 늘어나도 공개 API 필드는 안정적으로 유지된다.
    builder = StateGraph(
        ClioState,
        input_schema=ClioInput,
        output_schema=ClioOutput,
    )
    builder.add_node("normalize_report", create_normalize_report_node(normalizer))
    builder.add_edge(START, "normalize_report")
    builder.add_edge("normalize_report", END)
    return builder.compile()


# Agent Server는 이 모듈 전역의 `graph`를 읽는다. 실제 chat model은 첫 invoke까지 생성되지 않는다.
graph = build_graph()
