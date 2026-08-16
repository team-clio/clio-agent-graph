from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clio_agent_graph.workflows.reporting.normalization import (
    AffectedSurface,
    Environment,
    ErrorSignals,
    MissingField,
    NormalizationDraft,
    NormalizedReport,
    NormalizeReportInput,
    Reproduction,
)


def test_normalize_report_input_accepts_server_collection_fields() -> None:
    report = NormalizeReportInput(
        bug_id=351,
        title="결제 실패",
        description="결제 버튼을 누르면 500 오류가 발생합니다.",
        source="USER_REPORT",
        error_type="NullPointerException",
        message="payment must not be null",
        stack_trace=["PaymentService.pay(PaymentService.java:42)"],
        occurred_at=datetime(2026, 7, 28, tzinfo=UTC),
        raw_payload={"appVersion": "3.14.1"},
    )

    assert report.bug_id == 351
    assert report.stack_trace == ["PaymentService.pay(PaymentService.java:42)"]


def test_normalize_report_input_rejects_report_without_content() -> None:
    with pytest.raises(ValidationError, match="at least one report content field"):
        NormalizeReportInput(bug_id=351, source="USER_REPORT")


def test_normalized_report_exposes_the_approved_minimum_contract() -> None:
    report = NormalizedReport(
        bug_id=351,
        observed_behavior="결제 요청 시 500 오류가 발생한다.",
        reproduction=Reproduction(steps=["결제 버튼 클릭"]),
        environment=Environment(os="iOS", os_version="18.2"),
        affected_surface=AffectedSurface(feature="결제", operation="결제 승인"),
        error_signals=ErrorSignals(
            message="Internal Server Error",
            error_codes=["500"],
        ),
        missing_fields=[
            MissingField.EXPECTED_BEHAVIOR,
            MissingField.ERROR_TYPE,
            MissingField.STACK_TRACE,
        ],
    )

    result = report.model_dump(mode="json")

    assert result["bug_id"] == 351
    assert result["expected_behavior"] is None
    assert result["reproduction"]["steps"] == ["결제 버튼 클릭"]
    assert result["error_signals"]["error_codes"] == ["500"]
    assert result["missing_fields"] == [
        "EXPECTED_BEHAVIOR",
        "ERROR_TYPE",
        "STACK_TRACE",
    ]


def test_normalized_report_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NormalizedReport(
            bug_id=351,
            root_cause="PaymentService is broken",
        )


def test_normalization_draft_does_not_accept_application_owned_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NormalizationDraft(
            observed_behavior="결제에 실패한다.",
            bug_id=351,
            missing_fields=[MissingField.EXPECTED_BEHAVIOR],
        )


def test_normalized_report_rejects_duplicate_missing_fields() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        NormalizedReport(
            bug_id=351,
            missing_fields=[
                MissingField.ERROR_TYPE,
                MissingField.ERROR_TYPE,
            ],
        )
