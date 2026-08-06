from clio_agent_graph.agent_runtime import ToolCallRecord
from clio_agent_graph.matching.agentic_retrieval import build_agentic_issue_retrieval_graph
from clio_agent_graph.matching.models import (
    IssueCandidate,
    IssueRetrievalResponse,
)
from clio_agent_graph.normalization.models import NormalizedReport


class FakeRetrievalAgent:
    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        return [
            {
                "name": "semantic_issue_search",
                "arguments": {"query": "PAY-500"},
                "call_id": "search-1",
            }
        ]

    def invoke(self, user_prompt: str) -> IssueRetrievalResponse:
        assert '"bug_id": 72' in user_prompt
        return IssueRetrievalResponse(
            candidates=[
                IssueCandidate(
                    issue_id=19,
                    title="결제 승인 실패",
                    retrieval_score=0.91,
                )
            ]
        )


def test_agentic_retrieval_returns_candidates_and_tool_trace() -> None:
    graph = build_agentic_issue_retrieval_graph(agent=FakeRetrievalAgent())

    result = graph.invoke(
        {
            "project_id": 3,
            "bug_id": 72,
            "normalized_report": NormalizedReport(
                bug_report_id=351,
                observed_behavior="결제 승인 요청이 실패한다.",
            ),
        }
    )

    assert result["issue_candidates"][0].issue_id == 19
    assert result["retrieval_tool_calls"][0]["name"] == "semantic_issue_search"
