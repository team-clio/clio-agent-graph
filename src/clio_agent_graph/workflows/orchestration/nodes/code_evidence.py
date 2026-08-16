"""IDE 코드 근거용 snapshot-bound 읽기 노드."""

from collections import defaultdict

from clio_agent_graph.context.application import get_application_services
from clio_agent_graph.context.pcm.models import ProjectContextSnapshot
from clio_agent_graph.context.repository import RepositoryError
from clio_agent_graph.workflows.orchestration.state import ClioState

CONTEXT_LINES = 8


async def read_code_evidence(state: ClioState) -> dict[str, object]:
    """각 citation의 앞뒤 문맥만 읽고, commit 불일치는 거부한다."""

    citations = state["code_evidence_citations"]
    revisions = {item["repository_id"]: item["commit"] for item in citations}
    snapshot = ProjectContextSnapshot(project_id=state["project_id"], repository_revisions=revisions)
    repositories = get_application_services().repositories
    if repositories is None:
        raise RepositoryError("repository service is not configured")

    files: dict[tuple[str, str], dict[str, object]] = {}
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for citation in citations:
        grouped[(citation["repository_id"], citation["file_path"])].append(citation)
    for (repository_id, path), items in grouped.items():
        start = max(1, min(item["start_line"] for item in items) - CONTEXT_LINES)
        end = max(item["end_line"] for item in items) + CONTEXT_LINES
        excerpt = await repositories.read_file(
            snapshot=snapshot,
            repository_id=repository_id,
            path=path,
            start_line=start,
            end_line=min(end, start + 399),
        )
        if int(excerpt["end_line"]) < min(item["start_line"] for item in items):
            raise RepositoryError(f"citation line is outside file: {path}")
        files[(repository_id, path)] = {
            **excerpt,
            "citations": [
                {
                    "evidence_id": item["evidence_id"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "observation": item.get("observation"),
                }
                for item in items
            ],
        }
    return {
        "result": {"files": list(files.values())},
        "completed_nodes": {"read_code_evidence": True},
    }
