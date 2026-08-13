from clio_agent_graph.runtime.agent_runtime import ToolCallRecord
from clio_agent_graph.workflows.analysis.agentic_explorer import (
    build_agentic_code_exploration_graph,
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


class FakeExplorationAgent:
    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        return [
            {
                "name": "search_repository_code",
                "arguments": {"query": "PaymentService"},
                "call_id": "code-1",
            },
            {
                "name": "read_repository_file",
                "arguments": {"path": "payment.py", "start_line": 10, "end_line": 12},
                "call_id": "code-2",
            },
        ]

    def invoke(self, user_prompt: str) -> ExplorationResponse:
        assert "PaymentService" in user_prompt
        return ExplorationResponse(
            candidates=[
                EvidenceCandidate(
                    candidate_key="payment-call",
                    kind=EvidenceKind.CODE,
                    code_snapshot="order = payment.approve()",
                    observation="결제 승인 결과를 주문에 반영한다.",
                    file_path="payment.py",
                    start_line=11,
                    end_line=11,
                )
            ]
        )

    async def ainvoke(self, user_prompt: str) -> ExplorationResponse:
        return self.invoke(user_prompt)


def test_agentic_explorer_returns_evidence_and_selected_tool_trace() -> None:
    graph = build_agentic_code_exploration_graph(agent=FakeExplorationAgent())
    request = ExplorationRequest(
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="결제 오류"),
        bugs=[
            AnalysisBug(
                bug_id=72,
                normalized_report=NormalizedReport(
                    bug_id=351,
                    observed_behavior="결제 승인 후 주문이 보이지 않는다.",
                ),
            )
        ],
        questions=["PaymentService의 승인 결과가 어디에 반영되는가?"],
    )

    result = graph.invoke({"exploration_request": request})

    assert result["exploration_response"].candidates[0].candidate_key == "payment-call"
    assert [item["name"] for item in result["exploration_tool_calls"]] == [
        "search_repository_code",
        "read_repository_file",
    ]
