"""고정 Issue Retrieval 평가셋의 Recall@5와 MRR을 계산한다."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from clio_agent_graph.workflows.reporting.matching.models import (
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.workflows.reporting.normalization.models import ContractModel, NonEmptyText


class RetrievalEvaluationCase(ContractModel):
    """하나의 query와 정답 Issue를 묶은 평가 사례."""

    case_id: NonEmptyText
    request: IssueRetrievalRequest
    expected_issue_id: int = Field(gt=0)


class RetrievalEvaluationMetrics(ContractModel):
    """검색 후보 회수 품질을 확률처럼 과장하지 않는 순위 지표."""

    case_count: int = Field(ge=0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(ge=0.0, le=1.0)


Retriever = Callable[[IssueRetrievalRequest], IssueRetrievalResponse]


def evaluate_retrieval(
    cases: list[RetrievalEvaluationCase], retriever: Retriever
) -> RetrievalEvaluationMetrics:
    """각 정답 Issue의 top-5 포함 여부와 첫 순위 역수를 평균 낸다."""

    if not cases:
        return RetrievalEvaluationMetrics(
            case_count=0,
            recall_at_5=0.0,
            mean_reciprocal_rank=0.0,
        )
    recalled = 0
    reciprocal_rank_sum = 0.0
    for case in cases:
        response = IssueRetrievalResponse.model_validate(retriever(case.request))
        issue_ids = [candidate.issue_id for candidate in response.candidates]
        if case.expected_issue_id in issue_ids[:5]:
            recalled += 1
            reciprocal_rank_sum += 1.0 / (issue_ids.index(case.expected_issue_id) + 1)
    return RetrievalEvaluationMetrics(
        case_count=len(cases),
        recall_at_5=recalled / len(cases),
        mean_reciprocal_rank=reciprocal_rank_sum / len(cases),
    )


def load_evaluation_cases(path: Path) -> list[RetrievalEvaluationCase]:
    """JSON 파일을 extra field가 허용되지 않는 평가 계약으로 읽는다."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [RetrievalEvaluationCase.model_validate(item) for item in payload]


def main() -> int:
    """실제 DB·embedding 설정으로 평가하고 설정 누락은 SKIPPED로 출력한다."""

    if len(sys.argv) != 2:
        print("usage: python -m reporting.retrieval.evaluation <cases.json>")
        return 2
    from clio_agent_graph.workflows.reporting.matching.errors import (
        IssueRetrievalNotConfiguredError,
    )
    from clio_agent_graph.workflows.reporting.matching.retrieval_subgraph import (
        build_issue_retrieval_subgraph,
    )

    cases = load_evaluation_cases(Path(sys.argv[1]))
    graph = build_issue_retrieval_subgraph()

    def retrieve(request: IssueRetrievalRequest) -> IssueRetrievalResponse:
        result = graph.invoke(request.model_dump())
        return IssueRetrievalResponse(candidates=result["issue_candidates"])

    try:
        metrics = evaluate_retrieval(cases, retrieve)
    except IssueRetrievalNotConfiguredError as error:
        print(json.dumps({"status": "SKIPPED", "reason": str(error)}, ensure_ascii=False))
        return 0
    print(
        json.dumps(
            {"status": "COMPLETED", **metrics.model_dump()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
