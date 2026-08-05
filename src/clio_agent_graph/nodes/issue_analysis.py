"""고정 PCM snapshot을 사용하는 이슈 분석 서브그래프 노드."""

from typing import Literal

from clio_agent_graph.agents.issue_analysis import IssueAnalysisAgent
from clio_agent_graph.services.application import get_application_services
from clio_agent_graph.services.mock import mock_service
from clio_agent_graph.services.pcm.models import KnowledgeSearchRequest, ProjectContextSnapshot
from clio_agent_graph.state import ClioState
from clio_agent_graph.tools.pcm import PCMToolContext, PCMToolFactory
from clio_agent_graph.tools.repository import RepositoryToolFactory


def _snapshot(state: ClioState) -> ProjectContextSnapshot:
    return ProjectContextSnapshot.model_validate(state["context_snapshot"])


def _agent(state: ClioState) -> IssueAnalysisAgent:
    services = get_application_services()
    snapshot = _snapshot(state)
    tools = PCMToolFactory(services.pcm).create_tools(
        PCMToolContext(
            project_id=state["project_id"],
            request_id=state["request_id"],
            snapshot=snapshot,
        )
    )
    if services.repositories is not None:
        tools.extend(RepositoryToolFactory(services.repositories).create_tools(snapshot))
    return IssueAnalysisAgent(tools)


async def prepare_analysis(state: ClioState) -> dict[str, object]:
    """Graph가 project 범위와 PCM revision을 한 번 선택해 이후 호출에 고정한다."""

    if state.get("context_snapshot"):
        snapshot = _snapshot(state)
        if snapshot.project_id != state["project_id"]:
            raise ValueError("context snapshot project does not match the request project")
    else:
        snapshot = await get_application_services().pcm.resolve_snapshot(state["project_id"])
        repositories = get_application_services().repositories
        if repositories is not None:
            snapshot = snapshot.model_copy(
                update={
                    "repository_revisions": await repositories.list_revisions(state["project_id"])
                }
            )
    queries = state.get(
        "analysis_queries",
        {
            "documents": [state["issue_id"]],
            "code": [state["issue_id"]],
            "history": [state["issue_id"]],
        },
    )
    return {
        "context_snapshot": snapshot.model_dump(mode="json"),
        "analysis_queries": queries,
        "completed_nodes": {"prepare_analysis": True},
    }


async def search_documents(state: ClioState) -> dict[str, object]:
    """동일 PCM snapshot에서 초기 장기지식 근거를 검색한다."""

    evidence = state.get("document_evidence")
    if not evidence:
        evidence = []
        reader = get_application_services().pcm
        for query in state["analysis_queries"]["documents"]:
            page = await reader.search_knowledge(
                snapshot=_snapshot(state),
                request=KnowledgeSearchRequest(query=query),
            )
            evidence.extend(result.model_dump(mode="json") for result in page.results)
    return {
        "document_evidence": evidence,
        "completed_nodes": {"search_documents": True},
    }


async def search_code(state: ClioState) -> dict[str, object]:
    """고정 repository commit에서 초기 코드 근거를 검색한다."""

    evidence = state.get("code_evidence")
    repositories = get_application_services().repositories
    if not evidence and repositories is not None:
        evidence = []
        for query in state["analysis_queries"]["code"]:
            hits = await repositories.search(snapshot=_snapshot(state), query=query)
            evidence.extend(hit.model_dump(mode="json") for hit in hits)
    return {
        "code_evidence": evidence or [],
        "completed_nodes": {"search_code": True},
    }


def search_history(state: ClioState) -> dict[str, object]:
    """해결 이력은 PCM 검색 결과 또는 요청에 명시된 근거로 분석 Agent가 조회한다."""

    return {
        "history_evidence": state.get("history_evidence", []),
        "completed_nodes": {"search_history": True},
    }


async def analyze_issue(state: ClioState) -> dict[str, object]:
    """snapshot-bound 읽기 Tool만 가진 Agent로 이슈를 분석한다."""

    analysis = await _agent(state).analyze(
        state["issue_id"],
        {
            "documents": state.get("document_evidence", []),
            "code": state.get("code_evidence", []),
            "history": state.get("history_evidence", []),
        },
    )
    return {"issue_analysis": analysis, "completed_nodes": {"analyze_issue": True}}


async def plan_resolution(state: ClioState) -> dict[str, object]:
    """검증된 분석을 구현 및 테스트 가능한 해결 계획으로 변환한다."""

    return {
        "resolution_plan": await _agent(state).plan(state["issue_id"], state["issue_analysis"]),
        "completed_nodes": {"plan_resolution": True},
    }


async def quality_gate(state: ClioState) -> dict[str, object]:
    """결과 계약과 Knowledge citation의 snapshot 일치 여부를 검사한다."""

    has_contract = "issue_analysis" in state and "resolution_plan" in state
    requested_status = state.get("quality_result", {}).get("requested_status")
    attempt = state.get("quality_attempt", 0)
    reasons: list[str] = []
    if not has_contract:
        reasons.append("Analysis contract is incomplete.")
    analysis = state.get("issue_analysis", {})
    citations = analysis.get("citations", [])
    if analysis.get("facts") and not citations:
        reasons.append("Factual claims require citations.")
    for citation in citations:
        source_type = citation.get("source_type", "")
        if source_type in {"repository", "source_code", "repository_file", "code"}:
            repository_id = citation.get("repository_id") or citation.get("source_id")
            commit = citation.get("commit") or citation.get("source_revision")
            expected = _snapshot(state).repository_revisions.get(repository_id or "")
            if not repository_id or not expected:
                reasons.append("Repository citation is not available in the bound snapshot.")
            elif commit != expected:
                reasons.append(f"Repository citation commit does not match: {repository_id}.")
            continue
        if source_type not in {"knowledge", "pcm_knowledge"}:
            continue
        knowledge_id = citation.get("knowledge_id")
        if not knowledge_id:
            reasons.append("Knowledge citation is missing knowledge_id.")
            continue
        try:
            document = await get_application_services().pcm.read_knowledge(
                snapshot=_snapshot(state), knowledge_id=knowledge_id
            )
        except (KeyError, ValueError):
            reasons.append(f"Knowledge citation is not visible in snapshot: {knowledge_id}.")
            continue
        if citation.get("knowledge_revision") != document.knowledge_revision:
            reasons.append(f"Knowledge citation revision does not match: {knowledge_id}.")

    if requested_status == "retry" and attempt == 0:
        status = "retry"
        reasons.append("Quality gate requested one analysis retry.")
    elif requested_status == "retry":
        status = "needs_review"
        reasons.append("Retry limit reached; human review is required.")
    else:
        status = "needs_review" if reasons else "passed"
    return {
        "quality_result": {"status": status, "reasons": reasons},
        "quality_attempt": attempt + 1,
        "completed_nodes": {"quality_gate": True},
    }


def route_quality_result(
    state: ClioState,
) -> Literal["save_analysis", "retry_analysis", "needs_review"]:
    """Quality Gate 결과를 저장 또는 사람 검토 상태로 분기한다."""

    if state["quality_result"]["status"] == "passed":
        return "save_analysis"
    if state["quality_result"]["status"] == "retry":
        return "retry_analysis"
    return "needs_review"


def save_analysis(state: ClioState) -> dict[str, object]:
    """추후 API Server 저장 호출로 교체할 외부 부작용 경계."""

    mock_service.save_analysis(state["project_id"], state["issue_id"])
    return {
        "status": "completed",
        "result": {
            "action": "analysis_completed",
            "issue_id": state["issue_id"],
            "analysis": state["issue_analysis"],
            "resolution_plan": state["resolution_plan"],
            "quality": state["quality_result"],
        },
        "completed_nodes": {"save_analysis": True},
    }


def mark_analysis_for_review(state: ClioState) -> dict[str, object]:
    """Quality Gate가 통과하지 못한 실행을 검토 필요 상태로 남긴다."""

    return {
        "status": "needs_review",
        "result": {
            "action": "analysis_needs_review",
            "issue_id": state["issue_id"],
            "quality": state["quality_result"],
        },
        "completed_nodes": {"mark_analysis_for_review": True},
    }
