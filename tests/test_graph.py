import json
from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from clio_agent_graph.context.application import ApplicationServices
from clio_agent_graph.context.clio_server import WorkflowStart
from clio_agent_graph.context.pcm import DocumentKnowledgePipeline, InMemoryPCM
from clio_agent_graph.context.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    KnowledgeCandidate,
    KnowledgeChangeDraft,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    TopicExtractionResult,
)
from clio_agent_graph.context.tools import reports
from clio_agent_graph.graph import graph
from clio_agent_graph.runtime.agent_runtime import AgentExecutionLimitError
from clio_agent_graph.runtime.llm import ToolCallingAgent
from clio_agent_graph.workflows.orchestration.nodes import (
    issue_analysis,
    memory_sync,
    report_processing,
)
from clio_agent_graph.workflows.reporting.matching.models import IssueCandidate
from clio_agent_graph.workflows.reporting.normalization.models import (
    ErrorSignals,
    NormalizedReport,
)


class FakeClioServer:
    def __init__(self) -> None:
        self.completed_runs: list[tuple[str, int, dict[str, object]]] = []
        self.failed_runs: list[tuple[str, int, str, str]] = []
        self.saved_analyses: list[dict[str, object]] = []
        self.created_issues: list[tuple[str, int, str, float]] = []
        self.load_error: Exception | None = None
        self.complete_error: Exception | None = None
        self.workflow_start = WorkflowStart(501, "RUNNING")
        self.completed_repository_syncs: list[tuple[str, str]] = []
        self.failed_repository_syncs: list[tuple[str, str]] = []

    def start_workflow(
        self,
        project_id: str,
        request_id: str,
        request_type: str,
        request_payload: dict[str, object],
    ) -> WorkflowStart:
        return self.workflow_start

    def complete_workflow(
        self, project_id: str, workflow_run_id: int, result: dict[str, object]
    ) -> None:
        if self.complete_error is not None:
            raise self.complete_error
        self.completed_runs.append((project_id, workflow_run_id, result))

    def fail_workflow(
        self,
        project_id: str,
        workflow_run_id: int,
        *,
        failure_code: str,
        failure_message: str,
    ) -> None:
        self.failed_runs.append((project_id, workflow_run_id, failure_code, failure_message))

    def complete_repository_sync(self, project_id: str, repository_id: str) -> None:
        self.completed_repository_syncs.append((project_id, repository_id))

    def fail_repository_sync(self, project_id: str, repository_id: str) -> None:
        self.failed_repository_syncs.append((project_id, repository_id))

    def load_bug(self, project_id: str, bug_id: str) -> dict[str, object]:
        if self.load_error is not None:
            raise self.load_error
        return {
            "bug_id": int(bug_id),
            "project_id": project_id,
            "title": "Saved search fails",
            "description": "Submitting the form returns HTTP 500.",
            "source": "API",
            "message": "HTTP 500",
            "stack_trace": [],
            "raw_payload": {},
        }

    def load_issue_representative_bug(self, project_id: str, issue_id: str) -> dict[str, object]:
        return self.load_bug(project_id, "1")

    def create_issue(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        confidence: float,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, object]:
        assert title == "저장된 검색이 HTTP 500으로 실패합니다"
        assert description is not None and "## 증상" in description
        self.created_issues.append((project_id, workflow_run_id, bug_id, confidence))
        return {"issue_id": 101, "bug_id": int(bug_id), "issue_created": True}

    def link_bug(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        issue_id: str,
        confidence: float,
    ) -> dict[str, object]:
        return {"issue_id": issue_id, "bug_id": int(bug_id), "bug_linked": True}

    def save_analysis(
        self,
        project_id: str,
        workflow_run_id: int,
        issue_id: str,
        issue_analysis: dict[str, object],
    ) -> dict[str, object]:
        self.saved_analyses.append(issue_analysis)
        return {"analysis_result_id": 601}


class FakeRetrievalGraph:
    def __init__(self, candidates: list[IssueCandidate] | None = None) -> None:
        self.candidates = candidates or []
        self.requests: list[dict[str, object]] = []

    def invoke(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return {"issue_candidates": self.candidates}


class FakeReportNormalizer:
    def normalize(self, report) -> NormalizedReport:
        assert report.description == "Submitting the form returns HTTP 500."
        return NormalizedReport(
            bug_id=report.bug_id,
            observed_behavior="Saving a search returns HTTP 500.",
            error_signals=ErrorSignals(
                error_type=report.error_type,
                message="HTTP 500",
                stack_frames=report.stack_trace,
            ),
        )


class FakeIndexerGraph:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def invoke(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return {"index_result": {"status": "CREATED"}}


class FailingIndexerGraph:
    def invoke(self, request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("index unavailable")


@pytest.fixture(autouse=True)
def fake_llm_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep graph-routing tests independent of a live LLM provider."""

    def invoke(self: ToolCallingAgent, prompt: str) -> dict[str, object]:
        payload = json.loads(prompt.split("\n", 1)[1])
        if self.name == "report_matcher":
            assert payload["normalized_report"]["observed_behavior"] == (
                "Saving a search returns HTTP 500."
            )
            candidates = payload["candidates"]
            if not candidates:
                return {
                    "action": "create_new",
                    "issue_id": None,
                    "confidence": 1.0,
                    "reason": "No matching issue was found.",
                }
            candidate = candidates[0]
            if candidate.get("requires_review"):
                return {
                    "action": "needs_review",
                    "issue_id": candidate["issue_id"],
                    "confidence": candidate["confidence"],
                    "reason": "The candidate requires human review.",
                }
            return {
                "action": "link_existing",
                "issue_id": candidate["issue_id"],
                "confidence": candidate.get("confidence") or candidate["retrieval_score"],
                "reason": "The candidate is a strong match.",
            }
        if self.name == "issue_drafter":
            return {
                "title": "저장된 검색이 HTTP 500으로 실패합니다",
                "description": (
                    "## 증상\n저장 요청이 HTTP 500으로 실패합니다.\n\n"
                    "## 기대 동작\n정보 없음\n\n## 재현 절차\n정보 없음\n\n"
                    "## 영향 범위\n정보 없음\n\n## 오류 신호\nHTTP 500\n\n"
                    "## 조사 메모\n정규화된 Bug report를 기준으로 생성했습니다."
                ),
            }
        if self.name == "issue_analyst":
            evidence = payload["evidence"]
            code_evidence = evidence["code"]
            if code_evidence and code_evidence[0].get("repository_id"):
                hit = code_evidence[0]
                location = f"{hit['path']}:{hit['line']}"
                return {
                    "issue_id": payload["issue_id"],
                    "evidence_counts": {
                        source: len(items) for source, items in evidence.items()
                    },
                    "facts": [
                        {
                            "fact": "Payment approval reaches the failing code path.",
                            "verified": True,
                        }
                    ],
                    "citations": [
                        {
                            "source_type": "repository",
                            "repository_id": hit["repository_id"],
                            "commit": hit["commit"],
                            "location": location,
                            "snippet": hit["content"],
                        }
                    ],
                    "root_cause_hypotheses": [
                        {
                            "hypothesis": "The approval path does not handle PAY-500.",
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                }
            return {
                "issue_id": payload["issue_id"],
                "evidence_counts": {source: len(items) for source, items in evidence.items()},
                "root_cause_hypotheses": [],
                "confidence": 0.0,
            }
        if self.name == "risk_assessor":
            return {
                "risk_score": 72,
                "factors": [
                    {"name": "영향 범위", "score": 80, "rationale": "결제 경로 전체에 영향을 준다."}
                ],
                "rationale": "핵심 결제 기능이 차단되어 위험도가 높다.",
            }
        return {
            "issue_id": payload["issue_id"],
            "steps": ["Handle the provider's PAY-500 response in the approval path."],
            "acceptance_criteria": ["PAY-500 produces a recoverable approval result."],
        }

    monkeypatch.setattr(ToolCallingAgent, "invoke", invoke)

    async def ainvoke(self: ToolCallingAgent, prompt: str) -> dict[str, object]:
        return invoke(self, prompt)

    monkeypatch.setattr(ToolCallingAgent, "ainvoke", ainvoke)

    class FakeKnowledgeModel:
        async def extract_topics(
            self,
            *,
            document_title: str,
            source_units: Sequence[DocumentSourceUnit],
            validation_errors: Sequence[str] = (),
        ) -> TopicExtractionResult:
            return TopicExtractionResult(
                topics=(
                    ExtractedTopic(
                        topic_key="saved-search-permissions",
                        title="Saved Search permissions",
                        knowledge_type="domain_rule",
                        summary=document_title,
                        source_unit_ids=(source_units[0].source_unit_id,),
                        suggested_search_queries=("saved search permissions",),
                    ),
                )
            )

        async def generate_change_set(
            self,
            *,
            source_event_id: str,
            snapshot: ProjectContextSnapshot,
            topics: Sequence[ExtractedTopic],
            source_units: Sequence[DocumentSourceUnit],
            candidates: Mapping[str, Sequence[KnowledgeCandidate]],
            validation_errors: Sequence[str] = (),
        ) -> KnowledgeChangeDraftSet:
            candidate = next(iter(candidates[topics[0].topic_key]), None)
            if candidate:
                change = KnowledgeChangeDraft(
                    operation="update",
                    target_knowledge_id=candidate.knowledge_id,
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown=source_units[0].content,
                    source_unit_ids=(source_units[0].source_unit_id,),
                    reason="The document updates an existing rule.",
                )
            else:
                change = KnowledgeChangeDraft(
                    operation="create",
                    logical_key="saved-search-permissions",
                    knowledge_type="domain_rule",
                    title="Saved Search permissions",
                    body_markdown=source_units[0].content,
                    source_unit_ids=(source_units[0].source_unit_id,),
                    reason="The document defines a durable rule.",
                )
            return KnowledgeChangeDraftSet(
                source_event_id=source_event_id,
                base_pcm_revision=snapshot.pcm_revision,
                changes=(change,),
            )

    pcm = InMemoryPCM()
    clio_server = FakeClioServer()
    services = ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=FakeKnowledgeModel(),
        ),
        clio_server=clio_server,
    )
    monkeypatch.setattr(memory_sync, "get_application_services", lambda: services)
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    monkeypatch.setattr(report_processing, "get_application_services", lambda: services)
    monkeypatch.setattr(report_processing, "build_report_normalizer", FakeReportNormalizer)
    monkeypatch.setattr(report_processing, "build_issue_retrieval_subgraph", FakeRetrievalGraph)
    monkeypatch.setattr(report_processing, "build_bug_retrieval_indexer_graph", FakeIndexerGraph)
    monkeypatch.setattr(reports, "get_application_services", lambda: services)


@pytest.mark.asyncio
async def test_routes_analyze_issue_directly_to_reusable_analysis_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-1",
                "request_type": "analyze_issue",
                "project_id": "1",
                "payload": {"issue_id": "1"},
            },
            "document_evidence": [{"id": "DOC-1"}],
            "code_evidence": [{"id": "CODE-1"}],
            "history_evidence": [{"id": "HISTORY-1"}],
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "1"
    assert result["result"]["analysis"]["evidence_counts"] == {
        "documents": 1,
        "code": 1,
        "history": 1,
    }
    assert "load_and_normalize_report" not in result["completed_nodes"]
    assert result["completed_nodes"]["prepare_analysis"] is True
    assert result["bug_context"]["description"] == "Submitting the form returns HTTP 500."


@pytest.mark.asyncio
async def test_new_report_reuses_issue_analysis_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-2",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "1"},
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "101"
    assert result["workflow_run_id"] == 501
    assert result["completed_nodes"]["match_report"] is True
    assert result["completed_nodes"]["prepare_analysis"] is True
    assert result["completed_nodes"]["save_analysis"] is True
    assert result["completed_nodes"]["index_normalized_report"] is True
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    assert server.saved_analyses[0]["status"] == "COMPLETED"
    assert server.saved_analyses[0]["evidence"] == []
    assert "analysis" not in server.saved_analyses[0]


@pytest.mark.asyncio
async def test_new_report_persists_complete_analysis_with_repository_citation() -> None:
    commit = "a" * 40
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-COMPLETE-ANALYSIS",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "10"},
            },
            "context_snapshot": ProjectContextSnapshot(
                project_id="1",
                pcm_revision=0,
                knowledge_index_revision=0,
                repository_revisions={"backend": commit},
            ).model_dump(mode="json"),
            "code_evidence": [
                {
                    "repository_id": "backend",
                    "commit": commit,
                    "path": "src/payment.py",
                    "line": 42,
                    "content": "raise PaymentApprovalError('PAY-500')",
                }
            ],
        }
    )

    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    saved = server.saved_analyses[-1]
    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["quality_result"]["status"] == "passed"
    assert saved["status"] == "COMPLETED"
    assert saved["findings"]
    assert saved["hypotheses"]
    assert saved["resolution_plan"]["steps"]
    assert saved["risk_assessment"]["risk_score"] == 72
    assert saved["risk_assessment"]["priority"] == "P1"
    assert saved["evidence"] == [
        {
            "source_type": "repository",
            "repository_id": "backend",
            "commit": commit,
            "location": "src/payment.py:42",
            "snippet": "raise PaymentApprovalError('PAY-500')",
        }
    ]


def test_new_report_supports_synchronous_graph_execution() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-SYNC",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "4"},
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"


def test_no_candidates_create_an_issue_without_matcher_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object) -> dict[str, object]:
        raise AssertionError("matcher must not run without candidates")

    monkeypatch.setattr(report_processing.report_agent, "decide_match", fail_if_called)

    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-NO-CANDIDATES",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "5"},
            }
        }
    )

    assert result["result"]["action"] == "analysis_completed"


def test_analysis_limit_completes_workflow_as_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LimitedAnalysisAgent:
        async def analyze(self, *args: object) -> dict[str, object]:
            raise AgentExecutionLimitError("tool_calls")

    monkeypatch.setattr(issue_analysis, "_agent", lambda state: LimitedAnalysisAgent())

    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-ANALYSIS-LIMIT",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "6"},
            }
        }
    )

    assert result["status"] == "needs_review"
    assert result["result"]["action"] == "analysis_needs_review"
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    assert server.saved_analyses[0]["status"] == "NEEDS_REVIEW"


def test_existing_issue_match_skips_issue_analysis_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-3",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "2"},
            },
            "issue_candidates": [
                {
                    "issue_id": "19",
                    "confidence": 0.97,
                }
            ],
        }
    )

    assert result["status"] == "completed"
    assert result["result"] == {
        "action": "link_existing",
        "bug_id": "2",
        "issue_id": "19",
    }
    assert "prepare_analysis" not in result["completed_nodes"]
    assert result["completed_nodes"]["index_normalized_report"] is True


def test_retrieval_candidates_are_used_for_existing_issue_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval = FakeRetrievalGraph(
        [
            IssueCandidate(
                issue_id=19,
                title="Saved search failure",
                retrieval_score=0.97,
                retrieval_reasons=["matching error signal"],
            )
        ]
    )
    monkeypatch.setattr(report_processing, "build_issue_retrieval_subgraph", lambda: retrieval)

    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-RETRIEVED",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "2"},
            }
        }
    )

    assert result["result"] == {
        "action": "link_existing",
        "bug_id": "2",
        "issue_id": "19",
    }
    assert retrieval.requests[0]["project_id"] == 1
    assert retrieval.requests[0]["bug_id"] == 2
    assert retrieval.requests[0]["normalized_report"].bug_id == 2
    assert retrieval.requests[0]["normalized_report"].observed_behavior == (
        "Saving a search returns HTTP 500."
    )
    assert result["completed_nodes"]["index_normalized_report"] is True


def test_uncertain_match_finishes_as_needs_review() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-4",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "3"},
            },
            "issue_candidates": [
                {
                    "issue_id": "ISSUE-CANDIDATE",
                    "confidence": 0.55,
                    "requires_review": True,
                }
            ],
        }
    )

    assert result["status"] == "needs_review"
    assert result["result"]["action"] == "needs_review"
    assert "prepare_analysis" not in result["completed_nodes"]
    assert "index_normalized_report" not in result["completed_nodes"]


def test_completed_workflow_replay_skips_agent_execution() -> None:
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    server.workflow_start = WorkflowStart(
        501,
        "COMPLETED",
        {"action": "link_existing", "bug_id": "2", "issue_id": 19},
    )

    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-REPLAY",
                "request_type": "process_report",
                "project_id": "1",
                "payload": {"bug_id": "2"},
            }
        }
    )

    assert result["result"]["issue_id"] == "19"
    assert "load_and_normalize_report" not in result["completed_nodes"]
    assert server.completed_runs == []


def test_processing_error_marks_workflow_failed() -> None:
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    server.load_error = RuntimeError("bug lookup failed")

    with pytest.raises(RuntimeError, match="bug lookup failed"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-FAIL",
                    "request_type": "process_report",
                    "project_id": "1",
                    "payload": {"bug_id": "2"},
                }
            }
        )

    assert server.failed_runs == [("1", 501, "RUNTIMEERROR", "bug lookup failed")]


def test_indexing_error_prevents_issue_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(report_processing, "build_bug_retrieval_indexer_graph", FailingIndexerGraph)
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)

    with pytest.raises(RuntimeError, match="index unavailable"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-INDEX-FAIL",
                    "request_type": "process_report",
                    "project_id": "1",
                    "payload": {"bug_id": "2"},
                }
            }
        )

    assert server.created_issues == []
    assert server.failed_runs == [("1", 501, "RUNTIMEERROR", "index unavailable")]


def test_completion_error_marks_workflow_failed() -> None:
    server = report_processing.get_application_services().clio_server
    assert isinstance(server, FakeClioServer)
    server.complete_error = RuntimeError("completion failed")

    with pytest.raises(RuntimeError, match="completion failed"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-COMPLETE-FAIL",
                    "request_type": "process_report",
                    "project_id": "1",
                    "payload": {"bug_id": "2"},
                },
                "issue_candidates": [
                    {"issue_id": "19", "confidence": 0.97},
                ],
            }
        )

    assert server.failed_runs == [("1", 501, "RUNTIMEERROR", "completion failed")]


def test_rejects_legacy_report_id_before_routing() -> None:
    with pytest.raises(ValidationError, match="bug_id"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-LEGACY",
                    "request_type": "process_report",
                    "project_id": "PROJECT-1",
                    "payload": {"report_id": "REPORT-1"},
                }
            }
        )


def test_rejects_unknown_request_type_before_routing() -> None:
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-5",
                    "request_type": "unknown",
                    "project_id": "PROJECT-1",
                    "payload": {},
                }
            }
        )


@pytest.mark.asyncio
async def test_routes_document_event_to_pcm_knowledge_pipeline() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-6",
                "request_type": "document_added",
                "project_id": "PROJECT-1",
                "payload": {
                    "document_id": "DOC-1",
                    "revision": "REV-1",
                    "title": "Saved Search requirements",
                    "markdown": "# Permissions\n\nOnly owners can edit a saved search.",
                },
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "document_synced"
    assert result["result"]["pcm_revision"] == 1
    assert len(result["result"]["created_knowledge_ids"]) == 1
    assert result["completed_nodes"]["sync_document_knowledge"] is True


@pytest.mark.asyncio
async def test_replaying_document_event_returns_same_pcm_commit() -> None:
    request = {
        "request": {
            "request_id": "REQ-DOCUMENT-REPLAY",
            "request_type": "document_added",
            "project_id": "PROJECT-REPLAY",
            "payload": {
                "document_id": "DOC-1",
                "revision": "REV-1",
                "title": "Saved Search requirements",
                "markdown": "# Permissions\n\nOnly owners can edit a saved search.",
            },
        }
    }

    first = await graph.ainvoke(request)
    replay = await graph.ainvoke(request)

    assert first["result"]["pcm_revision"] == 1
    assert replay["result"]["pcm_revision"] == 1
    assert replay["result"]["idempotent_replay"] is True


def test_document_added_requires_normalized_markdown() -> None:
    with pytest.raises(ValidationError, match="markdown"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-DOCUMENT-MISSING-CONTENT",
                    "request_type": "document_added",
                    "project_id": "PROJECT-1",
                    "payload": {
                        "document_id": "DOC-1",
                        "revision": "REV-1",
                        "title": "Saved Search requirements",
                    },
                }
            }
        )


def test_repository_added_requires_source_uri() -> None:
    with pytest.raises(ValidationError, match="source_uri"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-REPOSITORY-MISSING-SOURCE",
                    "request_type": "repository_added",
                    "project_id": "PROJECT-1",
                    "payload": {
                        "repository_id": "REPO-1",
                        "branch": "main",
                    },
                }
            }
        )


@pytest.mark.asyncio
async def test_routes_repository_change_to_incremental_mock_sync_graph() -> None:
    result = await graph.ainvoke(
        {
            "request": {
                "request_id": "REQ-7",
                "request_type": "repository_changed",
                "project_id": "PROJECT-1",
                "payload": {
                    "repository_id": "REPO-1",
                    "branch": "main",
                    "before_commit": "a" * 40,
                    "after_commit": "b" * 40,
                },
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "code_change_synced"
    assert result["completed_nodes"]["validate_code_change"] is True
