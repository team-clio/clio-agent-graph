"""리포트 조사를 위한 읽기 전용 Agent Tool."""

from langchain_core.tools import tool

from clio_agent_graph.context.mock import mock_service


@tool
def load_report(project_id: str, report_id: str) -> dict[str, object]:
    """원본 버그 리포트를 정규화된 조사 입력으로 가져온다."""

    return mock_service.load_report(project_id, report_id)


@tool
def search_issue_candidates(
    project_id: str, normalized_report: dict[str, object]
) -> list[dict[str, object]]:
    """정규화된 리포트와 유사한 기존 이슈 후보를 검색한다."""

    return mock_service.search_issue_candidates(project_id, normalized_report)
