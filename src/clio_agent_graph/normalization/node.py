"""ReportNormalizer를 LangGraph 노드 함수로 연결한다."""

from collections.abc import Callable
from typing import Any

from clio_agent_graph.normalization.models import NormalizeReportInput
from clio_agent_graph.normalization.service import ReportNormalizer
from clio_agent_graph.state import ClioState


def create_normalize_report_node(
    normalizer: ReportNormalizer,
) -> Callable[[ClioState], dict[str, Any]]:
    """테스트와 운영에서 서로 다른 모델을 주입할 수 있는 NM 노드를 만든다.

    반환된 내부 함수가 `normalizer` 변수를 기억하는 방식을 Python에서는 closure라고 부른다.
    """

    def normalize_report(state: ClioState) -> dict[str, Any]:
        """JSON 형태의 그래프 입력을 검증하고 정규화 결과를 상태에 기록한다."""

        report = NormalizeReportInput.model_validate(state["bug_report"])
        return {"normalized_report": normalizer.normalize(report)}

    return normalize_report
