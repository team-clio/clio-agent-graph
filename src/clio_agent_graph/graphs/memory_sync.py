"""Project Context Memory를 갱신하는 서브그래프들."""

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.nodes.memory_sync import (
    build_repository_index,
    calculate_code_changes,
    commit_code_revision,
    commit_document_revision,
    commit_repository_revision,
    prepare_document_sync,
    prepare_repository_sync,
    sync_document_knowledge,
    update_changed_code_index,
    update_document_index,
    validate_code_change,
)
from clio_agent_graph.state import ClioState


def _linear_graph(name: str, nodes: list[tuple[str, object]]):
    builder = StateGraph(ClioState)
    for node_name, node in nodes:
        builder.add_node(node_name, node)
    builder.add_edge(START, nodes[0][0])
    for (before, _), (after, _) in zip(nodes[:-1], nodes[1:], strict=True):
        builder.add_edge(before, after)
    builder.add_edge(nodes[-1][0], END)
    return builder.compile()


def build_document_sync_graph():
    builder = StateGraph(ClioState)
    builder.add_node("sync_document_knowledge", sync_document_knowledge)
    builder.add_node("prepare_document_sync", prepare_document_sync)
    builder.add_node("update_document_index", update_document_index)
    builder.add_node("commit_document_revision", commit_document_revision)
    builder.add_conditional_edges(
        START,
        lambda state: state["request_type"],
        {
            "document_added": "sync_document_knowledge",
            "document_deleted": "prepare_document_sync",
        },
    )
    builder.add_edge("sync_document_knowledge", END)
    builder.add_edge("prepare_document_sync", "update_document_index")
    builder.add_edge("update_document_index", "commit_document_revision")
    builder.add_edge("commit_document_revision", END)
    return builder.compile()


def build_repository_sync_graph():
    return _linear_graph(
        "repository_sync",
        [
            ("prepare_repository_sync", prepare_repository_sync),
            ("build_repository_index", build_repository_index),
            ("commit_repository_revision", commit_repository_revision),
        ],
    )


def build_code_change_sync_graph():
    return _linear_graph(
        "code_change_sync",
        [
            ("validate_code_change", validate_code_change),
            ("calculate_code_changes", calculate_code_changes),
            ("update_changed_code_index", update_changed_code_index),
            ("commit_code_revision", commit_code_revision),
        ],
    )
