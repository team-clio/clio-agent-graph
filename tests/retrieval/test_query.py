from clio_agent_graph.matching.models import IssueRetrievalRequest
from clio_agent_graph.normalization.models import (
    AffectedSurface,
    Environment,
    ErrorSignals,
    NormalizedReport,
    Reproduction,
)
from clio_agent_graph.retrieval.query import (
    build_search_query,
    build_search_text,
    calculate_document_hash,
)


def _report() -> NormalizedReport:
    return NormalizedReport(
        bug_report_id=351,
        observed_behavior="결제 버튼을 누르면 500 오류가 발생한다.",
        reproduction=Reproduction(steps=["결제 버튼 클릭"]),
        environment=Environment(app_version="3.14.1", additional={"region": "kr"}),
        affected_surface=AffectedSurface(feature="결제", endpoint="POST /payments"),
        error_signals=ErrorSignals(
            error_type=" PaymentException ",
            message="Internal Server Error",
            error_codes=["PAY-500", "pay-500"],
            stack_frames=["PaymentService.approve"],
        ),
    )


def test_search_text_uses_only_normalized_report_fields_in_fixed_order() -> None:
    text = build_search_text(_report())

    assert text.splitlines() == [
        "observed_behavior: 결제 버튼을 누르면 500 오류가 발생한다.",
        "reproduction_step: 결제 버튼 클릭",
        "environment.app_version: 3.14.1",
        "environment.region: kr",
        "affected_surface.feature: 결제",
        "affected_surface.endpoint: POST /payments",
        "error_type: PaymentException",
        "error_message: Internal Server Error",
        "error_code: PAY-500",
        "error_code: pay-500",
        "stack_frame: PaymentService.approve",
    ]
    assert "raw_payload" not in text


def test_search_query_normalizes_and_deduplicates_exact_signals() -> None:
    query = build_search_query(
        IssueRetrievalRequest(project_id=3, bug_id=72, normalized_report=_report())
    )

    assert query.error_type == "paymentexception"
    assert query.error_codes == ["pay-500"]
    assert query.stack_frames == ["paymentservice.approve"]


def test_document_hash_is_deterministic_and_changes_with_snapshot() -> None:
    report = _report()
    search_text = build_search_text(report)

    first = calculate_document_hash(report, search_text)
    second = calculate_document_hash(report, search_text)
    changed = report.model_copy(update={"observed_behavior": "다른 현상"})

    assert first == second
    assert first != calculate_document_hash(changed, build_search_text(changed))
    assert len(first) == 64
