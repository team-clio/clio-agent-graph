"""고정 PCM snapshot을 사용하는 이슈 분석 서브그래프 노드."""

import asyncio
from typing import Any, Literal

from clio_agent_graph.context.application import get_application_services
from clio_agent_graph.context.pcm.models import KnowledgeSearchRequest, ProjectContextSnapshot
from clio_agent_graph.context.tools.codebase_exploration import CodebaseExplorationToolFactory
from clio_agent_graph.context.tools.pcm import PCMToolContext, PCMToolFactory
from clio_agent_graph.context.tools.repository import RepositoryToolFactory
from clio_agent_graph.runtime.agent_runtime import AgentExecutionLimitError
from clio_agent_graph.workflows.analysis.risk import map_risk_to_priority
from clio_agent_graph.workflows.orchestration.agents.issue_analysis import IssueAnalysisAgent
from clio_agent_graph.workflows.orchestration.nodes import report_processing
from clio_agent_graph.workflows.orchestration.state import ClioState
from clio_agent_graph.workflows.reporting.normalization.models import NormalizeReportInput


def _snapshot(state: ClioState) -> ProjectContextSnapshot:
    return ProjectContextSnapshot.model_validate(state["context_snapshot"])


def _agent(state: ClioState) -> IssueAnalysisAgent:
    services = get_application_services()
    snapshot = _snapshot(state)
    tools = []
    if not state.get("code_evidence"):
        tools = PCMToolFactory(services.pcm).create_tools(
            PCMToolContext(
                project_id=state["project_id"],
                request_id=state["request_id"],
                snapshot=snapshot,
            )
        )
    if services.repositories is not None and not state.get("code_evidence"):
        repository_tools = RepositoryToolFactory(services.repositories)
        tools.extend(CodebaseExplorationToolFactory(repository_tools).create_tools(snapshot))
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
    server = get_application_services().clio_server
    if server is None:
        raise RuntimeError("Clio Server service is not configured.")
    bug_context = await asyncio.to_thread(
        server.load_issue_representative_bug, state["project_id"], state["issue_id"]
    )
    normalization_input = NormalizeReportInput.model_validate(
        {
            "bug_report_id": bug_context["bug_id"],
            "title": bug_context.get("title"),
            "description": bug_context.get("description"),
            "source": bug_context.get("source"),
            "error_type": bug_context.get("error_type"),
            "message": bug_context.get("message"),
            "stack_trace": bug_context.get("stack_trace") or [],
            "occurred_at": bug_context.get("occurred_at"),
            "raw_payload": bug_context.get("raw_payload") or {},
        }
    )
    normalized_report = (
        await asyncio.to_thread(
            report_processing.build_report_normalizer().normalize, normalization_input
        )
    ).model_dump(mode="json")
    context_state = {**state, "normalized_report": normalized_report, "bug_context": bug_context}
    queries = state.get(
        "analysis_queries",
        {
            "documents": [state["issue_id"]],
            "code": _code_search_queries(context_state),
            "history": [state["issue_id"]],
        },
    )
    return {
        "context_snapshot": snapshot.model_dump(mode="json"),
        "bug_context": bug_context or {},
        "normalized_report": normalized_report,
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

    try:
        analysis = await _agent(state).analyze(
            state["issue_id"],
            {
                "documents": state.get("document_evidence", []),
                "code": state.get("code_evidence", []),
                "history": state.get("history_evidence", []),
            },
            state.get("bug_context"),
        )
    except AgentExecutionLimitError as error:
        return {
            "analysis_error": _analysis_limit_message(error),
            "issue_analysis": _limited_analysis(state),
            "completed_nodes": {"analyze_issue": True},
        }
    return {"issue_analysis": analysis, "completed_nodes": {"analyze_issue": True}}


async def plan_resolution(state: ClioState) -> dict[str, object]:
    """검증된 분석을 구현 및 테스트 가능한 해결 계획으로 변환한다."""

    return {
        "resolution_plan": await _agent(state).plan(state["issue_id"], state["issue_analysis"]),
        "completed_nodes": {"plan_resolution": True},
    }


async def assess_risk(state: ClioState) -> dict[str, object]:
    """분석 결과와 Bug 문맥으로 이슈 위험도(0-100)와 P0~P4 우선순위를 산출한다."""

    try:
        risk = await _agent(state).assess_risk(
            state["issue_id"],
            state.get("issue_analysis", {}),
            state.get("bug_context"),
        )
    except Exception:
        # 위험도 산출은 핵심 분석과 무관한 부가 신호이므로 실패해도 분석 저장을 막지 않는다.
        risk = None
    if risk is None:
        return {"risk_assessment": None, "completed_nodes": {"assess_risk": True}}
    risk_score = int(risk["risk_score"])
    return {
        "risk_assessment": {**risk, "priority": map_risk_to_priority(risk_score)},
        "completed_nodes": {"assess_risk": True},
    }


async def quality_gate(state: ClioState) -> dict[str, object]:
    """결과 계약과 Knowledge citation의 snapshot 일치 여부를 검사한다."""

    has_contract = "issue_analysis" in state and "resolution_plan" in state
    requested_status = state.get("quality_result", {}).get("requested_status")
    attempt = state.get("quality_attempt", 0)
    reasons: list[str] = []
    warnings: list[str] = []
    valid_citations: list[dict[str, Any]] = []
    if not has_contract:
        reasons.append("Analysis contract is incomplete.")
    analysis = state.get("issue_analysis", {})
    citations = analysis.get("citations", [])
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
            elif not _has_structured_code_location(citation):
                warnings.append("Dropped a repository citation without a structured code location.")
            else:
                valid_citations.append(citation)
            continue
        if source_type not in {"knowledge", "pcm_knowledge"}:
            continue
        knowledge_id = citation.get("knowledge_id")
        if not knowledge_id:
            warnings.append("Dropped a knowledge citation without knowledge_id.")
            continue
        try:
            document = await get_application_services().pcm.read_knowledge(
                snapshot=_snapshot(state), knowledge_id=knowledge_id
            )
        except (KeyError, ValueError):
            warnings.append(f"Dropped a knowledge citation outside the snapshot: {knowledge_id}.")
            continue
        if citation.get("knowledge_revision") != document.knowledge_revision:
            reasons.append(f"Knowledge citation revision does not match: {knowledge_id}.")
            continue
        valid_citations.append(citation)
    if analysis.get("facts") and not valid_citations:
        reasons.append("Factual claims require valid citations.")

    if requested_status == "retry" and attempt == 0:
        status = "retry"
        reasons.append("Quality gate requested one analysis retry.")
    elif requested_status == "retry":
        status = "needs_review"
        reasons.append("Retry limit reached; human review is required.")
    else:
        status = "needs_review" if reasons else "passed"
    return {
        "issue_analysis": {**analysis, "citations": valid_citations},
        "quality_result": {"status": status, "reasons": reasons, "warnings": warnings},
        "quality_attempt": attempt + 1,
        "completed_nodes": {"quality_gate": True},
    }


def _has_structured_code_location(citation: dict[str, Any]) -> bool:
    """IDE가 추측 없이 하이라이트할 수 있는 위치 계약을 확인한다."""

    path = citation.get("file_path")
    start = citation.get("start_line")
    end = citation.get("end_line")
    return (
        isinstance(path, str)
        and bool(path)
        and isinstance(start, int)
        and start >= 1
        and isinstance(end, int)
        and end >= start
    )


def route_quality_result(
    state: ClioState,
) -> Literal["save_analysis", "retry_analysis", "needs_review"]:
    """Quality Gate 결과를 저장 또는 사람 검토 상태로 분기한다."""

    if state["quality_result"]["status"] == "passed":
        return "save_analysis"
    if state["quality_result"]["status"] == "retry":
        return "retry_analysis"
    return "needs_review"


def route_after_analysis(state: ClioState) -> Literal["plan_resolution", "needs_review"]:
    """탐색 상한에 도달한 분석은 추가 모델 호출 없이 검토로 종료한다."""

    return "needs_review" if state.get("analysis_error") else "plan_resolution"


def save_analysis(state: ClioState) -> dict[str, object]:
    """process_report 분석 결과를 API Server에 저장한다."""

    _save_analysis_snapshot(state, "COMPLETED")
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

    if state.get("analysis_error"):
        state = {
            **state,
            "issue_analysis": state.get("issue_analysis", _limited_analysis(state)),
            "resolution_plan": {},
            "quality_result": {"status": "needs_review", "reasons": [state["analysis_error"]]},
        }

    _save_analysis_snapshot(state, "NEEDS_REVIEW")
    return {
        "status": "needs_review",
        "result": {
            "action": "analysis_needs_review",
            "issue_id": state["issue_id"],
            "quality": state["quality_result"],
        },
        "completed_nodes": {"mark_analysis_for_review": True},
    }


def _save_analysis_snapshot(state: ClioState, status: Literal["COMPLETED", "NEEDS_REVIEW"]) -> None:
    workflow_run_id = state.get("workflow_run_id")
    if workflow_run_id is None:
        return
    server = get_application_services().clio_server
    if server is None:
        raise RuntimeError("Clio Server service is not configured.")
    analysis = state["issue_analysis"]
    quality = state["quality_result"]
    server.save_analysis(
        state["project_id"],
        workflow_run_id,
        state["issue_id"],
        {
            "workflow_run_id": workflow_run_id,
            "project_id": int(state["project_id"]),
            "issue_id": int(state["issue_id"]),
            "status": status,
            "evidence": analysis.get("citations", []),
            "relations": [],
            "findings": analysis.get("facts", []),
            "hypotheses": analysis.get("root_cause_hypotheses", []),
            "warnings": quality.get("reasons", []) + quality.get("warnings", []),
            "confidence": analysis.get("confidence", 0.0),
            "resolution_plan": state.get("resolution_plan", {}),
            "risk_assessment": state.get("risk_assessment"),
        },
    )


def _analysis_limit_message(error: AgentExecutionLimitError) -> str:
    labels = {
        "tool_calls": "분석 완료 전에 도구 호출 한도에 도달했습니다.",
        "model_calls": "분석 완료 전에 모델 호출 한도에 도달했습니다.",
        "recursion": "분석 완료 전에 Agent 재귀 한도에 도달했습니다.",
    }
    return labels[error.limit]


def _limited_analysis(state: ClioState) -> dict[str, Any]:
    """한도 전에 확보한 고정 snapshot 코드 검색 결과를 검토용 근거로 보존한다."""

    citations = []
    facts = []
    for hit in state.get("code_evidence", [])[:5]:
        repository_id = hit.get("repository_id")
        commit = hit.get("commit")
        path = hit.get("path")
        line = hit.get("line")
        if not all(isinstance(value, str) and value for value in (repository_id, commit, path)):
            continue
        location = f"{path}:{line}" if isinstance(line, int) else path
        snippet = hit.get("content")
        if not isinstance(snippet, str) or not snippet.strip():
            continue
        observation = f"Repository 검색이 commit {commit[:12]}의 {location}에서 일치했습니다."
        citations.append(
            {
                "source_type": "repository",
                "source_id": repository_id,
                "source_revision": commit,
                "repository_id": repository_id,
                "commit": commit,
                "location": location,
                "snippet": snippet[:500],
                "observation": observation,
            }
        )
        facts.append(f"{observation} 일치한 텍스트: {snippet[:200]}")
    return {
        "facts": facts,
        "citations": citations,
        "root_cause_hypotheses": [],
        "confidence": 0.0,
    }


def _code_search_queries(state: ClioState) -> list[str]:
    """Bug 정규화 신호에서 실제 source에 있을 법한 fixed-string 검색어를 만든다."""

    report = state.get("normalized_report", {})
    signals = report.get("error_signals", {}) if isinstance(report, dict) else {}
    surface = report.get("affected_surface", {}) if isinstance(report, dict) else {}
    candidates: list[object] = [
        *(signals.get("error_codes", []) if isinstance(signals, dict) else []),
        signals.get("error_type") if isinstance(signals, dict) else None,
        surface.get("operation") if isinstance(surface, dict) else None,
        surface.get("endpoint") if isinstance(surface, dict) else None,
    ]
    if isinstance(signals, dict):
        candidates.extend(_stack_frame_symbols(signals.get("stack_frames", [])))

    queries: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        query = candidate.strip()
        if len(query) < 3 or len(query) > 120 or query.casefold() in {
            item.casefold() for item in queries
        }:
            continue
        queries.append(query)
        if len(queries) == 5:
            break
    return queries or [state["issue_id"]]


def _stack_frame_symbols(frames: object) -> list[str]:
    if not isinstance(frames, list):
        return []
    symbols = []
    for frame in frames:
        if not isinstance(frame, str):
            continue
        symbol = frame.split("(", 1)[0].rsplit(".", 1)[-1].strip()
        if symbol:
            symbols.append(symbol)
    return symbols
