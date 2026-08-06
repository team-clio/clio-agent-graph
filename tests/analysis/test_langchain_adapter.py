from unittest.mock import Mock, patch

from clio_agent_graph.analysis.langchain_adapter import (
    LangChainInitialJudgmentModel,
)
from clio_agent_graph.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    AnalysisMode,
    ExplorationDirective,
    JudgmentContext,
)
from clio_agent_graph.normalization.models import NormalizedReport


def _context() -> JudgmentContext:
    return JudgmentContext(
        mode=AnalysisMode.INITIAL,
        analysis_job_id=501,
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="결제 오류"),
        bugs=[
            AnalysisBug(
                bug_id=72,
                normalized_report=NormalizedReport(
                    bug_report_id=351,
                    observed_behavior="주문이 보이지 않는다.",
                ),
            )
        ],
        trigger_bug_id=72,
    )


def test_judgment_model_is_created_lazily() -> None:
    plan_model = Mock()
    plan_model.invoke.return_value = ExplorationDirective(questions=[])
    chat_model = Mock()
    chat_model.with_structured_output.return_value = plan_model

    with patch(
        "clio_agent_graph.analysis.langchain_adapter.build_chat_model",
        return_value=chat_model,
    ) as build_chat_model:
        adapter = LangChainInitialJudgmentModel()
        build_chat_model.assert_not_called()

        result = adapter.plan(_context(), [], [])

    build_chat_model.assert_called_once_with()
    chat_model.with_structured_output.assert_called_once_with(ExplorationDirective)
    assert result.questions == []
