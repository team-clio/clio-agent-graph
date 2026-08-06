from unittest.mock import Mock, patch

from langchain_core.tools import tool

from clio_agent_graph.matching.langchain_adapter import LangChainIssueMatchModel
from clio_agent_graph.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchComparisonDraft,
)
from clio_agent_graph.normalization.models import NormalizedReport


def test_model_is_created_lazily_on_first_comparison() -> None:
    structured_model = Mock()
    structured_model.invoke.return_value = MatchComparisonDraft(
        comparisons=[CandidateComparison(issue_id=19, confidence=0.8)]
    )
    chat_model = Mock()
    chat_model.with_structured_output.return_value = structured_model

    with patch(
        "clio_agent_graph.matching.langchain_adapter.build_chat_model",
        return_value=chat_model,
    ) as build_chat_model:
        adapter = LangChainIssueMatchModel()
        build_chat_model.assert_not_called()

        result = adapter.compare(
            NormalizedReport(bug_report_id=351, observed_behavior="오류가 발생한다."),
            [IssueCandidate(issue_id=19, title="기존 오류", retrieval_score=0.8)],
        )

    build_chat_model.assert_called_once_with()
    chat_model.with_structured_output.assert_called_once_with(
        MatchComparisonDraft, method="function_calling"
    )
    assert result.comparisons[0].issue_id == 19


def test_matcher_uses_candidate_investigation_tools() -> None:
    @tool
    def read_issue_history(issue_id: int) -> dict[str, int]:
        """Read the selected issue history."""

        return {"issue_id": issue_id}

    fake_agent = Mock()
    fake_agent.invoke.return_value = MatchComparisonDraft(
        comparisons=[CandidateComparison(issue_id=19, confidence=0.9)]
    )
    fake_agent.last_tool_calls = [
        {
            "name": "read_issue_history",
            "arguments": {"issue_id": 19},
            "call_id": "call-1",
        }
    ]

    with (
        patch(
            "clio_agent_graph.matching.langchain_adapter.build_chat_model",
            return_value=object(),
        ),
        patch(
            "clio_agent_graph.matching.langchain_adapter.StructuredToolAgent",
            return_value=fake_agent,
        ) as agent_class,
    ):
        adapter = LangChainIssueMatchModel(
            tools=[read_issue_history],
        )
        result = adapter.compare(
            NormalizedReport(bug_report_id=351, observed_behavior="오류가 발생한다."),
            [IssueCandidate(issue_id=19, title="기존 오류", retrieval_score=0.8)],
        )

    assert result.comparisons[0].confidence == 0.9
    assert agent_class.call_args.kwargs["tools"] == [read_issue_history]
    assert adapter.last_tool_calls[0]["name"] == "read_issue_history"
