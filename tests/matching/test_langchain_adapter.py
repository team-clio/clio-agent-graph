from unittest.mock import Mock, patch

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
        "clio_agent_graph.matching.langchain_adapter.init_chat_model",
        return_value=chat_model,
    ) as init_chat_model:
        adapter = LangChainIssueMatchModel("test:model")
        init_chat_model.assert_not_called()

        result = adapter.compare(
            NormalizedReport(bug_report_id=351, observed_behavior="오류가 발생한다."),
            [IssueCandidate(issue_id=19, title="기존 오류", retrieval_score=0.8)],
        )

    init_chat_model.assert_called_once_with("test:model")
    chat_model.with_structured_output.assert_called_once_with(MatchComparisonDraft)
    assert result.comparisons[0].issue_id == 19
