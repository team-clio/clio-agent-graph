import pytest

from clio_agent_graph.context.application import (
    ApplicationServices,
    DocumentKnowledgePipeline,
)
from clio_agent_graph.context.pcm import InMemoryPCM
from clio_agent_graph.context.pcm.models import ProjectContextSnapshot
from clio_agent_graph.runtime.agent_runtime import AgentExecutionLimitError
from clio_agent_graph.workflows.orchestration.nodes import issue_analysis


class _RepositoryService:
    pass


def _services() -> ApplicationServices:
    pcm = InMemoryPCM()
    return ApplicationServices(
        pcm=pcm,
        document_pipeline=DocumentKnowledgePipeline(
            reader=pcm,
            writer=pcm,
            knowledge_model=object(),  # type: ignore[arg-type]
        ),
        repositories=_RepositoryService(),  # type: ignore[arg-type]
    )


def test_issue_analysis_exposes_high_level_exploration_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = _services()
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
    )

    agent = issue_analysis._agent(
        {
            "project_id": "PROJECT-1",
            "request_id": "REQ-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
        }
    )

    tool_names = {tool.name for tool in agent.analysis_agent.tools}
    assert "Korean" in agent.analysis_agent.system_prompt
    assert "Korean" in agent.planning_agent.system_prompt
    assert tool_names == {
        "search_project_knowledge",
        "read_project_knowledge",
        "trace_knowledge_sources",
        "explore_codebase",
    }
    assert not tool_names.intersection(
        {
            "resolve_project_snapshot",
            "search_document_evidence",
            "search_code_evidence",
            "search_resolution_history",
            "list_project_repositories",
            "list_repository_files",
            "search_repository_code",
            "read_repository_file",
        }
    )


def test_issue_analysis_keeps_high_level_exploration_when_code_evidence_is_only_a_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = _services()
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
        repository_revisions={"backend": "a" * 40},
    )

    agent = issue_analysis._agent(
        {
            "project_id": "PROJECT-1",
            "request_id": "REQ-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
            "code_evidence": [{"path": "src/payment.py"}],
        }
    )

    tool_names = {tool.name for tool in agent.analysis_agent.tools}
    assert tool_names == {"explore_codebase"}


def test_issue_analysis_skips_exploration_when_search_found_actionable_layout_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = _services()
    monkeypatch.setattr(issue_analysis, "get_application_services", lambda: services)
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
        repository_revisions={"frontend": "a" * 40},
    )

    agent = issue_analysis._agent(
        {
            "project_id": "PROJECT-1",
            "request_id": "REQ-1",
            "context_snapshot": snapshot.model_dump(mode="json"),
            "code_evidence": [
                {
                    "path": "src/pages/News/NewsPage.tsx",
                    "content": '<main className="flex px-32 py-10 gap-10">',
                }
            ],
        }
    )

    assert {tool.name for tool in agent.analysis_agent.tools} == set()


@pytest.mark.asyncio
async def test_analysis_limit_preserves_initial_repository_search_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LimitedAgent:
        async def analyze(self, *args: object) -> dict[str, object]:
            raise AgentExecutionLimitError("model_calls")

    monkeypatch.setattr(issue_analysis, "_agent", lambda state: LimitedAgent())

    result = await issue_analysis.analyze_issue(
        {
            "issue_id": "7",
            "code_evidence": [
                {
                    "repository_id": "backend",
                    "commit": "a" * 40,
                    "path": "src/payment.py",
                    "line": 42,
                    "content": "payment.approve()",
                }
            ],
        }
    )

    assert result["analysis_error"] == "분석 완료 전에 모델 호출 한도에 도달했습니다."
    assert result["issue_analysis"]["citations"] == [
        {
            "source_type": "repository",
            "source_id": "backend",
            "source_revision": "a" * 40,
            "repository_id": "backend",
            "commit": "a" * 40,
            "location": "src/payment.py:42",
            "snippet": "payment.approve()",
            "observation": (
                "Repository 검색이 commit aaaaaaaaaaaa의 src/payment.py:42에서 일치했습니다."
            ),
        }
    ]


def test_code_search_queries_prefer_normalized_bug_signals() -> None:
    queries = issue_analysis._code_search_queries(
        {
            "issue_id": "7",
            "normalized_report": {
                "error_signals": {
                    "error_codes": ["PAY-500"],
                    "error_type": "PaymentApprovalException",
                    "stack_frames": ["PaymentApprovalService.approve(Payment.java:42)"],
                },
                "affected_surface": {"operation": "completePayment", "endpoint": "/checkout"},
            },
        }
    )

    assert queries == [
        "PAY-500",
        "PaymentApprovalException",
        "completePayment",
        "/checkout",
        "approve",
    ]


def test_code_search_queries_include_korean_feature_and_screen_terms() -> None:
    queries = issue_analysis._code_search_queries(
        {
            "issue_id": "1",
            "normalized_report": {
                "error_signals": {},
                "affected_surface": {
                    "feature": "뉴스토론",
                    "screen": "뉴스토론 페이지",
                    "operation": "화면 축소",
                },
            },
        }
    )

    assert queries == ['className="flex px-', "w-1/4", "min-w-", "뉴스", "토론"]


def test_code_search_queries_detect_responsive_bug_from_observed_behavior() -> None:
    queries = issue_analysis._code_search_queries(
        {
            "issue_id": "1",
            "normalized_report": {
                "observed_behavior": "브라우저 폭을 축소하면 화면이 깨진다",
                "error_signals": {},
                "affected_surface": {"feature": "뉴스토론"},
            },
        }
    )

    assert 'className="flex px-' in queries
    assert "w-1/4" in queries


def test_code_search_queries_detect_responsive_bug_from_original_description() -> None:
    queries = issue_analysis._code_search_queries(
        {
            "issue_id": "1",
            "normalized_report": {
                "error_signals": {},
                "affected_surface": {"feature": "뉴스토론 페이지"},
            },
            "bug_context": {
                "title": "뉴스토론 화면이 깨짐",
                "description": "뉴스토론 페이지에서 화면을 줄이면 ui가 다 깨짐",
            },
        }
    )

    assert queries[:3] == ['className="flex px-', "w-1/4", "min-w-"]
