"""ReportNormalizer를 LangGraph 노드 함수로 연결한다."""

from collections.abc import Callable
from typing import Any, Protocol

from clio_agent_graph.workflows.reporting.normalization.models import NormalizeReportInput
from clio_agent_graph.workflows.reporting.normalization.service import ReportNormalizer


class NormalizationState(Protocol):
    """정규화 노드가 실제로 요구하는 최소 상태 계약."""

    def __getitem__(self, key: str) -> Any: ...


def create_normalize_report_node(
    normalizer: ReportNormalizer,
) -> Callable[[NormalizationState], dict[str, Any]]:
    """테스트와 운영에서 서로 다른 모델을 주입할 수 있는 NM 노드를 만든다.

    반환된 내부 함수가 `normalizer` 변수를 기억하는 방식을 Python에서는 closure라고 부른다.
    """

    def normalize_report(state: NormalizationState) -> dict[str, Any]:
        """JSON 형태의 그래프 입력을 검증하고 정규화 결과를 상태에 기록한다."""

        report = NormalizeReportInput.model_validate(state["bug_report"])
        normalized_report = normalizer.normalize(report)
        return {
            "normalized_report": normalized_report,
            "normalization_tool_calls": normalizer.last_tool_calls,
        }

    return normalize_report
