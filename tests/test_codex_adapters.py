from pathlib import Path

from clio_agent_graph.workflows.analysis.codex_adapter import CodexInitialJudgmentModel
from clio_agent_graph.workflows.analysis.codex_explorer import CodexCodeExplorer
from clio_agent_graph.workflows.analysis.models import (
    AnalysisBug,
    AnalysisIssue,
    AnalysisMode,
    EvidenceCandidate,
    EvidenceKind,
    ExplorationDirective,
    ExplorationRequest,
    ExplorationResponse,
    JudgmentContext,
)
from clio_agent_graph.workflows.reporting.matching.codex_adapter import CodexIssueMatchModel
from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    MatchComparisonDraft,
)
from clio_agent_graph.workflows.reporting.normalization.codex_adapter import CodexNormalizationModel
from clio_agent_graph.workflows.reporting.normalization.models import (
    NormalizationDraft,
    NormalizedReport,
)


class _FakeInvoker:
    def __init__(self, payloads: dict[type, dict]) -> None:
        self._payloads = payloads
        self.calls: list[dict] = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        output_type = kwargs["output_type"]
        return output_type.model_validate(self._payloads[output_type])


def _normalized_report() -> NormalizedReport:
    return NormalizedReport(
        bug_id=351,
        observed_behavior="결제 완료 후 주문이 보이지 않는다.",
    )


def _judgment_context() -> JudgmentContext:
    return JudgmentContext(
        mode=AnalysisMode.INITIAL,
        workflow_run_id=501,
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="결제 오류"),
        bugs=[AnalysisBug(bug_id=72, normalized_report=_normalized_report())],
        trigger_bug_id=72,
    )


def test_codex_nm_rm_and_ia_adapters_preserve_structured_contracts() -> None:
    invoker = _FakeInvoker(
        {
            NormalizationDraft: {"observed_behavior": "주문이 보이지 않는다."},
            MatchComparisonDraft: {"comparisons": [{"issue_id": 19, "confidence": 0.97}]},
            ExplorationDirective: {"questions": ["주문 상태를 저장하는 코드를 찾아라."]},
        }
    )

    normalization = CodexNormalizationModel(invoker).extract("결제 오류")
    matching = CodexIssueMatchModel(invoker).compare(
        _normalized_report(),
        [IssueCandidate(issue_id=19, title="결제 오류", retrieval_score=0.9)],
    )
    directive = CodexInitialJudgmentModel(invoker).plan(_judgment_context(), [], [])

    assert normalization.observed_behavior == "주문이 보이지 않는다."
    assert matching.comparisons[0].issue_id == 19
    assert directive.questions == ["주문 상태를 저장하는 코드를 찾아라."]
    assert [call["output_type"] for call in invoker.calls] == [
        NormalizationDraft,
        MatchComparisonDraft,
        ExplorationDirective,
    ]


def test_codex_code_explorer_uses_configured_repository(tmp_path: Path) -> None:
    invoker = _FakeInvoker(
        {
            ExplorationResponse: {
                "candidates": [
                    {
                        "candidate_key": "controller",
                        "kind": EvidenceKind.CODE,
                        "code_snapshot": "return NOT_IMPLEMENTED;",
                        "observation": "endpoint is a stub",
                    }
                ]
            }
        }
    )
    request = ExplorationRequest(
        project_id=3,
        issue=AnalysisIssue(issue_id=19, title="수집 API 오류"),
        bugs=[AnalysisBug(bug_id=72, normalized_report=_normalized_report())],
        questions=["수집 endpoint 구현을 찾아라."],
    )

    response = CodexCodeExplorer(tmp_path, invoker)(request)

    assert isinstance(response.candidates[0], EvidenceCandidate)
    assert invoker.calls[0]["output_type"] is ExplorationResponse
    assert invoker.calls[0]["working_directory"] == tmp_path.resolve()
