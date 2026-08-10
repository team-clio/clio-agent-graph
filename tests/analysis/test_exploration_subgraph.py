import pytest

from clio_agent_graph.workflows.analysis.errors import (
    CodeExplorationError,
    CodeExplorerNotConfiguredError,
)
from clio_agent_graph.workflows.analysis.exploration_subgraph import (
    build_code_exploration_subgraph,
)
from clio_agent_graph.workflows.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    EvidenceCandidate,
    EvidenceKind,
    ExplorationRequest,
    ExplorationResponse,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


def _request() -> ExplorationRequest:
    return ExplorationRequest(
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="결제 오류"),
        bugs=[
            AnalysisBug(
                bug_id=72,
                normalized_report=NormalizedReport(
                    bug_report_id=351,
                    observed_behavior="결제 완료 후 주문이 보이지 않는다.",
                ),
            )
        ],
        questions=["결제 완료 뒤 주문 상태를 변경하는 심볼을 찾아라."],
    )


def test_placeholder_fails_instead_of_returning_empty_evidence() -> None:
    graph = build_code_exploration_subgraph()

    with pytest.raises(CodeExplorerNotConfiguredError):
        graph.invoke({"exploration_request": _request()})


def test_fake_explorer_receives_request_and_returns_snapshot() -> None:
    def explore(request: ExplorationRequest) -> ExplorationResponse:
        assert request.project_id == 3
        return ExplorationResponse(
            candidates=[
                EvidenceCandidate(
                    candidate_key="payment-service",
                    kind=EvidenceKind.CODE,
                    code_snapshot="order.markPaid();",
                    observation="주문을 PAID 상태로 변경한다.",
                )
            ]
        )

    result = build_code_exploration_subgraph(explore).invoke({"exploration_request": _request()})

    assert result["exploration_response"].candidates[0].candidate_key == "payment-service"


def test_explorer_is_retried_once_then_succeeds() -> None:
    attempts = 0

    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary")
        return ExplorationResponse()

    result = build_code_exploration_subgraph(explore).invoke({"exploration_request": _request()})

    assert attempts == 2
    assert result["exploration_response"].candidates == []


def test_explorer_fails_after_one_retry() -> None:
    attempts = 0

    def explore(_request: ExplorationRequest) -> ExplorationResponse:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("unavailable")

    with pytest.raises(CodeExplorationError):
        build_code_exploration_subgraph(explore).invoke({"exploration_request": _request()})

    assert attempts == 2
