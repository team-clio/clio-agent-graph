from clio_agent_graph.graph import build_graph
from clio_agent_graph.normalization.models import (
    ErrorSignals,
    NormalizationDraft,
    NormalizedReport,
)


class FakeNormalizationModel:
    """외부 API 없이 그래프 배선만 검증하는 NM 모델."""

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        assert "결제 버튼을 누르면" in report_text
        assert correction_feedback is None
        return NormalizationDraft(
            observed_behavior="결제 버튼 클릭 시 500 오류가 발생한다.",
            error_signals=ErrorSignals(error_codes=["500"]),
        )


def test_graph_normalizes_a_bug_report_with_injected_model() -> None:
    graph = build_graph(FakeNormalizationModel())

    result = graph.invoke(
        {
            "bug_report": {
                "bug_report_id": 351,
                "title": "결제 실패",
                "description": "결제 버튼을 누르면 500 오류가 발생합니다.",
            }
        }
    )

    normalized_report = result["normalized_report"]
    assert isinstance(normalized_report, NormalizedReport)
    assert normalized_report.bug_report_id == 351
    assert normalized_report.observed_behavior == "결제 버튼 클릭 시 500 오류가 발생한다."
    assert normalized_report.error_signals.error_codes == ["500"]
    assert "bug_report" not in result


def test_graph_contains_only_the_report_normalizer_domain_node() -> None:
    graph = build_graph(FakeNormalizationModel())

    node_names = set(graph.get_graph().nodes)

    assert node_names == {"__start__", "normalize_report", "__end__"}
