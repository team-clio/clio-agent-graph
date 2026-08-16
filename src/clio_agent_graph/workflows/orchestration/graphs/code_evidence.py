"""분석 snapshot의 코드 근거를 읽는 bounded read subgraph."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.workflows.orchestration.nodes.code_evidence import read_code_evidence
from clio_agent_graph.workflows.orchestration.state import ClioState


def build_code_evidence_graph():
    builder = StateGraph(ClioState)
    builder.add_node("read_code_evidence", read_code_evidence)
    builder.add_edge(START, "read_code_evidence")
    builder.add_edge("read_code_evidence", END)
    return builder.compile()
